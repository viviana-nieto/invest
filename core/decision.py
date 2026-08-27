"""Decision engine — turn a deterministic valuation into a BUY/WATCH/PASS call
with an evidence trail (Part 1: VALUE, "what's worth buying").

The thesis this module makes concrete: **the math makes the call.** A verdict is
a pure function of three pass/fail criteria; the LLM never votes. The only thing
an agent contributes is the one-sentence `narrative` — colour on top of a decision
that was already made by arithmetic.

Criteria (all deterministic, thresholds tunable via the config's skill block):
  1. Payback Time     < `payback_max_years` (default 12 — a short payback == a
                        cheap business)
  2. Margin of Safety > 0                   (price sits below the fair-value
                        sticker)
  3. Free Cash Flow yield >= `fcf_yield_min` (default 0 == "positive" — the
                        business actually generates cash)

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
# Default FCF-yield floor for the BUY/WATCH/PASS verdict (0 = "positive").
FCF_YIELD_MIN = 0.0


@dataclass(frozen=True)
class DecisionThresholds:
    """The tunable pass/fail thresholds behind the verdict. Defaults reproduce
    the classic rule (payback < 12y, positive FCF)."""

    payback_max_years: float = PAYBACK_MAX_YEARS
    # FCF-yield floor as a fraction (0.05 = 5%).
    fcf_yield_min: float = FCF_YIELD_MIN


DEFAULT_THRESHOLDS = DecisionThresholds()


def _number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def decision_thresholds(cfg: dict) -> DecisionThresholds:
    """Read the verdict thresholds from a config's skill block, with safe
    defaults (an absent / non-positive `payback_max_years` falls back to 12)."""
    skill = cfg.get("skill", {}) or {}
    pbt = skill.get("payback_max_years")
    fcf = skill.get("fcf_yield_min")
    return DecisionThresholds(
        payback_max_years=pbt if _number(pbt) and pbt > 0 else PAYBACK_MAX_YEARS,
        fcf_yield_min=fcf if _number(fcf) else FCF_YIELD_MIN,
    )


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


def valuation_criteria(v: Valuation, fcf_yield: float,
                       thresholds: DecisionThresholds = DEFAULT_THRESHOLDS,
                       ) -> list[dict]:
    """The three-item evidence checklist for a valuation, each with value,
    threshold, and a deterministic pass/fail. `fcf_yield` is a fraction; the
    thresholds default to the classic rule when omitted."""
    pbt = v.payback_years
    mos = v.margin_of_safety
    pbt_max = thresholds.payback_max_years
    fcf_min = thresholds.fcf_yield_min
    return [
        {
            "name": "Payback Time",
            "value": f"{pbt:.1f}y",
            "threshold": f"< {pbt_max:.0f}y",
            "passed": pbt < pbt_max,
        },
        {
            "name": "Margin of Safety",
            "value": f"{mos * 100:+.0f}%",
            "threshold": "> 0",
            "passed": mos > 0.0,
        },
        {
            "name": "Free Cash Flow yield",
            "value": f"{fcf_yield * 100:.1f}%",
            "threshold": (f"≥ {fcf_min * 100:.0f}%" if fcf_min == 0
                          else f"≥ {fcf_min * 100:.1f}%"),
            "passed": fcf_yield >= fcf_min,
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


def decide_valuation(v: Valuation, fcf_yield: float, narrative: str = "",
                     thresholds: DecisionThresholds = DEFAULT_THRESHOLDS,
                     ) -> dict:
    """Build the `valuation` decision block for one stock."""
    criteria = valuation_criteria(v, fcf_yield, thresholds)
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
    # FCF yield as a fraction — the value the verdict's FCF criterion tests.
    fcf_yield: float
    narrative: str
    shape: str  # timing sample-series shape: floor | neutral | extended


def stocks_from_config(cfg: dict) -> list[Stock]:
    """Parse the config watchlist into Stock objects, reusing the valuation
    defaults + growth-capping adapter from `core.screen` (the valuation trusts
    a capped growth; the row's own `growth_rate` stays the true CAGR)."""
    from .screen import _defaults, valuation_from_row

    d = _defaults(cfg)
    out: list[Stock] = []
    for row in cfg.get("skill", {}).get("watchlist", []):
        out.append(
            Stock(
                ticker=row["ticker"],
                name=row.get("name", row["ticker"]),
                sector=row.get("sector", ""),
                price=row["price"],
                valuation=valuation_from_row(row, d),
                fcf_positive=_fcf_positive(row.get("fcf", "positive")),
                fcf_yield=(row["fcf_yield"]
                           if _number(row.get("fcf_yield")) else 0.0),
                narrative=row.get("narrative", ""),
                shape=row.get("shape", "neutral"),
            )
        )
    return out


def build_decision(stock: Stock, series=None,
                   thresholds: DecisionThresholds = DEFAULT_THRESHOLDS) -> dict:
    """Assemble the full per-stock decision object (both lenses).

    Args:
        stock: parsed watchlist row.
        series: optional (highs, lows, closes) tuple for the timing lens. When
            omitted, the timing block is computed from the stock's sample shape.
        thresholds: verdict thresholds (defaults to the classic rule).
    """
    from . import signals as sig
    from . import sample_prices as sp

    valuation = decide_valuation(stock.valuation, stock.fcf_yield,
                                 stock.narrative, thresholds)

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
    thresholds = decision_thresholds(cfg)
    decisions = [build_decision(s, thresholds=thresholds) for s in stocks]
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
