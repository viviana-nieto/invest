"""Floor/ceiling timing engine (Part 2: TIMING, "when to buy — and when to trim").

Four *independent* technical signals computed from a price series with numpy —
no TA library, no network. Each answers a yes/no question about whether a name is
pressing against a floor. Their convergence is the call; the LLM never decides.

  1. Linear-regression channel  — is price at/below the lower rail of a least-
     squares channel drawn over the last N bars?
  2. Stochastic(14,5,3)         — is the slow %K oversold (< 20)?
  3. MACD(8,17,9)               — is the histogram turning up (momentum inflecting)?
  4. SMA position (vs 50-day)   — is price below its longer-term average (depressed)?

Convergence verdict (`timing_signals`, the floor-only lens used by core.decision):
  REACHING FLOOR  >= 3 of 4 met
  NEUTRAL          1 or 2 met
  EXTENDED         0 met     (nothing says floor; the tape is stretched)

The same checks also read in the *sell* direction. `rail_checks` runs both sides
at once — floor (buy) confirmations near the lower channel rail, ceiling
(sell/trim) confirmations near the upper rail — and folds them into one overall
timing verdict: REACHING FLOOR / NEUTRAL / REACHING CEILING.

All functions take plain 1-D numpy arrays (oldest -> newest) and return floats or
booleans. `timing_signals` wraps the floor side into the dashboard-ready dict.
"""

from __future__ import annotations

import numpy as np

# ---- indicator primitives ---------------------------------------------------


def _as_array(x) -> np.ndarray:
    return np.asarray(x, dtype=float)


def sma(values, period: int) -> np.ndarray:
    """Simple moving average; result aligned to the input (leading NaNs).

    NaN-safe: a window that contains any NaN yields NaN at that position without
    poisoning later windows (so smoothing chains over indicators that have their
    own warm-up NaNs still compute correctly once enough data is present).
    """
    v = _as_array(values)
    out = np.full(v.shape, np.nan)
    if period <= 0 or len(v) < period:
        return out
    for i in range(period - 1, len(v)):
        w = v[i - period + 1:i + 1]
        if not np.isnan(w).any():
            out[i] = w.mean()
    return out


def ema(values, period: int) -> np.ndarray:
    """Exponential moving average, seeded with the first value (leading values
    are the running EMA, not NaN — standard for MACD chains)."""
    v = _as_array(values)
    out = np.full(v.shape, np.nan)
    if len(v) == 0:
        return out
    alpha = 2.0 / (period + 1.0)
    out[0] = v[0]
    for i in range(1, len(v)):
        out[i] = alpha * v[i] + (1.0 - alpha) * out[i - 1]
    return out


def linreg_channel(closes, period: int = 100, num_std: float = 2.0) -> dict:
    """Least-squares regression channel over the last `period` bars.

    Fits close ~ a*t + b, then draws rails at the regression line +/- num_std *
    (std of residuals). Returns the endpoint values plus the price's position in
    the channel (0 == lower rail, 1 == upper rail).
    """
    c = _as_array(closes)
    n = min(period, len(c))
    window = c[-n:]
    t = np.arange(n, dtype=float)
    a, b = np.polyfit(t, window, 1)
    line = a * t + b
    resid_std = float(np.std(window - line))
    mid = float(line[-1])
    upper = mid + num_std * resid_std
    lower = mid - num_std * resid_std
    price = float(window[-1])
    span = upper - lower
    position = 0.5 if span == 0 else (price - lower) / span
    return {
        "slope": float(a),
        "mid": mid,
        "upper": upper,
        "lower": lower,
        "price": price,
        "position": position,  # 0=lower rail, 1=upper rail
    }


def stochastic(highs, lows, closes, k_period: int = 14,
               smooth_k: int = 5, smooth_d: int = 3) -> dict:
    """Stochastic oscillator (14,5,3): raw %K over `k_period`, slowed by an
    `smooth_k` SMA, with %D an `smooth_d` SMA of the slow %K."""
    h, l, c = _as_array(highs), _as_array(lows), _as_array(closes)
    n = len(c)
    raw_k = np.full(n, np.nan)
    for i in range(k_period - 1, n):
        hh = np.max(h[i - k_period + 1:i + 1])
        ll = np.min(l[i - k_period + 1:i + 1])
        rng = hh - ll
        raw_k[i] = 50.0 if rng == 0 else 100.0 * (c[i] - ll) / rng
    slow_k = sma(raw_k, smooth_k)
    d = sma(slow_k, smooth_d)
    return {
        "raw_k": float(raw_k[-1]),
        "k": float(slow_k[-1]) if not np.isnan(slow_k[-1]) else float(raw_k[-1]),
        "d": float(d[-1]) if not np.isnan(d[-1]) else float(slow_k[-1]),
    }


def macd(closes, fast: int = 8, slow: int = 17, signal: int = 9) -> dict:
    """MACD(8,17,9): fast EMA - slow EMA, its signal EMA, and the histogram plus
    its one-bar change (positive change == momentum turning up)."""
    c = _as_array(closes)
    macd_line = ema(c, fast) - ema(c, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    hist_prev = hist[-2] if len(hist) >= 2 else hist[-1]
    return {
        "macd": float(macd_line[-1]),
        "signal": float(signal_line[-1]),
        "hist": float(hist[-1]),
        "hist_change": float(hist[-1] - hist_prev),
    }


# ---- floor signal wrappers --------------------------------------------------


def _linreg_signal(closes, period: int, num_std: float) -> dict:
    ch = linreg_channel(closes, period=period, num_std=num_std)
    # "At/below the lower rail": position at or under 0 (price <= lower rail).
    met = ch["position"] <= 0.0
    return {
        "name": "LinReg Channel",
        "value": f"{ch['position'] * 100:.0f}% of channel",
        "met": bool(met),
        "detail": "at/below lower rail" if met else "above lower rail",
    }


def _stochastic_signal(highs, lows, closes) -> dict:
    st = stochastic(highs, lows, closes)
    met = st["k"] < 20.0
    return {
        "name": "Stochastic 14,5,3",
        "value": f"%K {st['k']:.0f}",
        "met": bool(met),
        "detail": "oversold (<20)" if met else "not oversold",
    }


def _macd_signal(closes) -> dict:
    m = macd(closes)
    met = m["hist_change"] > 0.0
    arrow = "up" if met else "down"
    return {
        "name": "MACD 8,17,9",
        "value": f"hist {m['hist']:+.2f}",
        "met": bool(met),
        "detail": f"histogram turning {arrow}",
    }


def _sma_signal(closes, period: int = 50) -> dict:
    c = _as_array(closes)
    s = sma(c, period)
    ref = s[-1]
    price = float(c[-1])
    if np.isnan(ref):  # series shorter than the SMA window
        ref = float(np.mean(c))
    pct = (price / ref - 1.0) * 100.0
    met = price < ref  # below the long average == depressed / near a floor
    return {
        "name": f"Price vs SMA{period}",
        "value": f"{pct:+.0f}% vs SMA",
        "met": bool(met),
        "detail": "below long average" if met else "above long average",
    }


def timing_signals(closes, highs=None, lows=None,
                   channel_period: int = 100, num_std: float = 2.0) -> dict:
    """Compute all four floor signals + a convergence verdict.

    Returns the dashboard-ready `timing` block:
        { verdict, signals: [ {name, value, met, detail}, ... ], score, met, total }
    """
    c = _as_array(closes)
    h = _as_array(highs) if highs is not None else c
    l = _as_array(lows) if lows is not None else c

    signals = [
        _linreg_signal(c, channel_period, num_std),
        _stochastic_signal(h, l, c),
        _macd_signal(c),
        _sma_signal(c, 50),
    ]
    met = sum(1 for s in signals if s["met"])
    total = len(signals)

    if met >= 3:
        verdict = "REACHING FLOOR"
    elif met == 0:
        verdict = "EXTENDED"
    else:
        verdict = "NEUTRAL"

    return {
        "verdict": verdict,
        "signals": signals,
        "score": f"{met}/{total} floor conditions met",
        "met": met,
        "total": total,
    }


# ---- ceiling (sell/trim) mirror + the combined timing read ------------------

# Channel-position rails: which third of the linreg channel makes each read
# "active". position <= DIP_MAX -> the floor (buy) read is live; position >=
# CEILING_MIN -> the ceiling (sell/trim) read is live. Because DIP_MAX <
# CEILING_MIN, a name is near the lower rail OR the upper rail — never both.
DIP_MAX = 0.34       # at/under == pressing the lower third of the channel
CEILING_MIN = 0.66   # at/over  == pressing the upper third of the channel


def confirmation_tier(confirms: int) -> str:
    """Fold a 0–3 confirmation count into the dashboard tier."""
    if confirms >= 2:
        return "strong"
    if confirms == 1:
        return "setting-up"
    return "watching"


def rail_checks(closes, highs=None, lows=None, channel_period: int = 100,
                num_std: float = 2.0, sma_period: int = 50,
                dip_max: float = DIP_MAX, ceiling_min: float = CEILING_MIN) -> dict:
    """Both directions of the timing lens in one deterministic read.

    Floor (buy) confirmations — is a decline exhausting?
      stoch_pass  Stochastic slow %K oversold (< 20)
      macd_pass   MACD histogram turning up (bullish inflection)
      ma_pass     price below its SMA50 (depressed; reclaiming from beneath)

    Ceiling (sell/trim) confirmations — is an advance exhausting?
      stoch_sell  Stochastic slow %K overbought (> 80)
      macd_sell   MACD histogram rolling over (bearish turn)
      ma_sell     price losing the SMA50 (crossing below / below it)

    Rails: ``at_lower_rail`` == channel position <= dip_max, ``at_upper_rail``
    == position >= ceiling_min — mutually exclusive by construction.

    Tiers fold each side's confirmations: strong (>= 2 of 3), setting-up (1),
    watching (0). ``ceiling_tier`` is meaningful when the name is near the
    upper rail; ``tier`` (floor) when near the lower rail.

    Overall ``timing`` verdict:
      REACHING CEILING  near the upper rail with >= 2 ceiling confirmations
      REACHING FLOOR    near the lower rail with >= 2 floor confirmations
      NEUTRAL           anything else
    """
    c = _as_array(closes)
    h = _as_array(highs) if highs is not None else c
    l = _as_array(lows) if lows is not None else c

    st = stochastic(h, l, c)
    m = macd(c)
    s50 = sma(c, sma_period)
    ref = float(s50[-1]) if not np.isnan(s50[-1]) else float(np.mean(c))
    price = float(c[-1])
    ch = linreg_channel(c, period=channel_period, num_std=num_std)
    position = float(ch["position"])

    # Floor (buy) side.
    stoch_pass = st["k"] < 20.0
    macd_pass = m["hist_change"] > 0.0
    ma_pass = price < ref

    # Ceiling (sell/trim) side — the inverted mirror. `ma_sell` is a breakdown
    # check ("the 50-day is lost"), not merely "above the average": a name still
    # riding above its SMA50 has not yet confirmed the sell.
    stoch_sell = st["k"] > 80.0
    macd_sell = m["hist_change"] < 0.0
    ma_sell = price < ref

    at_lower_rail = position <= dip_max
    at_upper_rail = position >= ceiling_min

    floor_confirms = int(stoch_pass) + int(macd_pass) + int(ma_pass)
    ceiling_confirms = int(stoch_sell) + int(macd_sell) + int(ma_sell)

    if at_upper_rail and ceiling_confirms >= 2:
        timing = "REACHING CEILING"
    elif at_lower_rail and floor_confirms >= 2:
        timing = "REACHING FLOOR"
    else:
        timing = "NEUTRAL"

    return {
        "stoch_k": float(st["k"]),
        "stoch_d": float(st["d"]),
        "stoch_pass": bool(stoch_pass),
        "macd_pass": bool(macd_pass),
        "ma_pass": bool(ma_pass),
        "stoch_sell": bool(stoch_sell),
        "macd_sell": bool(macd_sell),
        "ma_sell": bool(ma_sell),
        "channel_position": position,
        "at_lower_rail": bool(at_lower_rail),
        "at_upper_rail": bool(at_upper_rail),
        "floor_confirms": floor_confirms,
        "ceiling_confirms": ceiling_confirms,
        "tier": confirmation_tier(floor_confirms),
        "ceiling_tier": confirmation_tier(ceiling_confirms),
        "timing": timing,
    }
