"""Decision engine — turn a deterministic valuation into a BUY/WATCH/PASS call
with an evidence trail (Part 1: VALUE, "what's worth buying").

The thesis this module makes concrete: **the math makes the call.** A verdict is
a pure function of three pass/fail criteria; the LLM never votes. The only thing
an agent contributes is the one-sentence `narrative` — colour on top of a decision
that was already made by arithmetic.

Criteria (all deterministic):
  1. Payback Time    < 12 years          (a short payback == a cheap business)
  2. Margin of Safety > 0                (price sits below the fair-value sticker)
  3. Free Cash Flow   positive           (the business actually generates cash)

Verdict:
  BUY   = all 3 criteria pass
  WATCH = exactly 2 pass
  PASS  = 1 or 0 pass        ("pass" as in "take a pass on it")

Conviction (0-100) is a smooth, monotonic function of the margin of safety, used
to RANK the universe. Deeper discount == higher conviction == higher rank.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .valuation import Valuation

PAYBACK_MAX_YEARS = 12.0


def _fcf_positive(fcf) -> bool:
    """Normalise a config `fcf` field to a boolean. Accepts 'positive'/'negative'
    strings, booleans, or a raw number."""
    if isinstance(fcf, bool):
        return fcf
    if isinstance(fcf, (int, float)):
        return fcf > 0
    if isinstance(fcf, str):
        return fcf.strip().lower() in ("positive", "pos", "+", "true", "yes")
    return False


def conviction_from_mos(mos: float) -> int:
    """Map margin of safety to a 0-100 conviction score.

    A logistic curve centred at mos=0 (conviction 50): a stock exactly at fair
    value is a coin-flip; a deep discount approaches 100; a rich price approaches
    0. Monotonic in `mos`, so ranking by conviction == ranking by discount.
    """
    return int(round(100.0 / (1.0 + math.exp(-mos))))


def valuation_criteria(v: Valuation, fcf_positive: bool) -> list[dict]:
    """The three-item evidence checklist for a valuation, each with value,
    threshold, and a deterministic pass/fail."""
    pbt = v.payback_years
    mos = v.margin_of_safety
    return [
        {
            "name": "Payback Time",
            "value": f"{pbt:.1f}y",
            "threshold": f"< {PAYBACK_MAX_YEARS:.0f}y",
            "passed": pbt < PAYBACK_MAX_YEARS,
        },
        {
            "name": "Margin of Safety",
            "value": f"{mos * 100:+.0f}%",
            "threshold": "> 0",
            "passed": mos > 0.0,
        },
        {
            "name": "Free Cash Flow",
            "value": "positive" if fcf_positive else "negative",
            "threshold": "positive",
            "passed": bool(fcf_positive),
        },
    ]


def verdict_from_criteria(criteria: list[dict]) -> str:
    """3 pass -> BUY, exactly 2 -> WATCH, <=1 -> PASS. Deterministic."""
    passed = sum(1 for c in criteria if c["passed"])
    if passed == 3:
        return "BUY"
    if passed == 2:
        return "WATCH"
    return "PASS"


def decide_valuation(v: Valuation, fcf_positive: bool,
                     narrative: str = "") -> dict:
    """Build the `valuation` decision block for one stock."""
    criteria = valuation_criteria(v, fcf_positive)
    return {
        "verdict": verdict_from_criteria(criteria),
        "conviction": conviction_from_mos(v.margin_of_safety),
        "criteria": criteria,
        "narrative": narrative,
        # A few raw numbers the dashboard likes to show alongside the checklist.
        "payback_years": round(v.payback_years, 2),
        "sticker_price": round(v.sticker, 2),
        "buy_price": round(v.buy_price, 2),
        "margin_of_safety": round(v.margin_of_safety, 4),
    }


@dataclass
class Stock:
    """One watchlist row's static facts (everything except computed verdicts)."""

    ticker: str
    name: str
    sector: str
    price: float
    valuation: Valuation
    fcf_positive: bool
    narrative: str
    shape: str  # timing sample-series shape: floor | neutral | extended


def stocks_from_config(cfg: dict) -> list[Stock]:
    """Parse the config watchlist into Stock objects, reusing the valuation
    defaults from `core.screen`."""
    from .screen import _defaults

    d = _defaults(cfg)
    out: list[Stock] = []
    for row in cfg.get("skill", {}).get("watchlist", []):
        val = Valuation(
            ticker=row["ticker"],
            price=row["price"],
            eps=row["eps"],
            growth_rate=row["growth_rate"],
            future_pe=row.get("future_pe", d["default_future_pe"]),
            years=d["years"],
            required_return=d["required_return"],
            margin=d["margin"],
        )
        out.append(
            Stock(
                ticker=row["ticker"],
                name=row.get("name", row["ticker"]),
                sector=row.get("sector", ""),
                price=row["price"],
                valuation=val,
                fcf_positive=_fcf_positive(row.get("fcf", "positive")),
                narrative=row.get("narrative", ""),
                shape=row.get("shape", "neutral"),
            )
        )
    return out


def build_decision(stock: Stock, series=None) -> dict:
    """Assemble the full per-stock decision object (both lenses).

    Args:
        stock: parsed watchlist row.
        series: optional (highs, lows, closes) tuple for the timing lens. When
            omitted, the timing block is computed from the stock's sample shape.
    """
    from . import signals as sig
    from . import sample_prices as sp

    valuation = decide_valuation(stock.valuation, stock.fcf_positive,
                                 stock.narrative)

    if series is None:
        highs, lows, closes = sp.sample_ohlc(stock.ticker, stock.shape)
    else:
        highs, lows, closes = series
    timing = sig.timing_signals(closes, highs=highs, lows=lows)

    return {
        "ticker": stock.ticker,
        "name": stock.name,
        "sector": stock.sector,
        "price": round(stock.price, 2),
        "valuation": valuation,
        "timing": timing,
    }


def build_decisions(cfg: dict) -> list[dict]:
    """Full decision objects for the whole watchlist, ranked by conviction desc.

    Tie-break: margin of safety desc, then ticker asc — a total, deterministic
    order so the dashboard cards are stable run to run.
    """
    stocks = stocks_from_config(cfg)
    decisions = [build_decision(s) for s in stocks]
    decisions.sort(
        key=lambda d: (
            -d["valuation"]["conviction"],
            -d["valuation"]["margin_of_safety"],
            d["ticker"],
        )
    )
    for i, d in enumerate(decisions, start=1):
        d["rank"] = i
    return decisions
