"""Tunable-threshold tests — the valuation growth cap + configurable verdict
thresholds, mirroring the dashboard port's valuationCap.test.ts so both suites
pin the same behavior.

Three config knobs (skill block):
  * `valuation_growth_cap` — ceiling on the growth the VALUATION trusts; the
    row's own `growth_rate` (the displayed true CAGR) is never touched.
  * `payback_max_years`    — the verdict's Payback Time ceiling (default 12).
  * `fcf_yield_min`        — the verdict's FCF-yield floor (default 0).
"""

import math

from core.decision import (
    DecisionThresholds,
    decision_thresholds,
    valuation_criteria,
)
from core.screen import _defaults, valuation_from_row
from core.valuation import Valuation


def _cfg(**skill):
    skill.setdefault("watchlist", [])
    return {"skill": skill}


# A hypergrowth row: 60%/yr would mint an absurd sticker uncapped.
HYPER = {"ticker": "HYP", "price": 200.0, "eps": 6.0, "growth_rate": 0.6,
         "future_pe": 16.0}


# ---- valuation growth cap ---------------------------------------------------


def test_cap_lowers_growth_and_sticker():
    capped = valuation_from_row(HYPER, _defaults(_cfg(valuation_growth_cap=0.25)))
    uncapped = valuation_from_row(HYPER, _defaults(_cfg()))  # no cap key
    assert capped.growth_rate == 0.25
    assert uncapped.growth_rate == 0.6
    assert capped.sticker < uncapped.sticker


def test_cap_leaves_the_rows_own_growth_untouched():
    row = dict(HYPER)
    valuation_from_row(row, _defaults(_cfg(valuation_growth_cap=0.25)))
    # The displayed CAGR is the true growth; only the valuation was capped.
    assert row["growth_rate"] == 0.6


def test_cap_never_raises_a_growth_already_below_it():
    slow = dict(HYPER, growth_rate=0.1)
    v = valuation_from_row(slow, _defaults(_cfg(valuation_growth_cap=0.25)))
    assert v.growth_rate == 0.1


def test_absent_or_nonpositive_cap_means_uncapped():
    assert _defaults(_cfg())["valuation_growth_cap"] == math.inf
    assert _defaults(_cfg(valuation_growth_cap=0))["valuation_growth_cap"] == math.inf
    assert _defaults(_cfg(valuation_growth_cap=-5))["valuation_growth_cap"] == math.inf


# ---- configurable verdict thresholds ----------------------------------------


def test_decision_thresholds_defaults_and_overrides():
    assert decision_thresholds(_cfg()) == DecisionThresholds(
        payback_max_years=12, fcf_yield_min=0)
    assert decision_thresholds(
        _cfg(payback_max_years=10, fcf_yield_min=0.05)
    ) == DecisionThresholds(payback_max_years=10, fcf_yield_min=0.05)
    # A non-positive payback falls back to the default; fcf floor of 0 is kept.
    assert decision_thresholds(_cfg(payback_max_years=0)).payback_max_years == 12


def test_payback_criterion_moves_with_the_threshold():
    # A valuation whose payback lands ~9y: passes at <12, fails at <8.
    v = Valuation(ticker="T", price=200.0, eps=6.34, growth_rate=0.25,
                  future_pe=15.99, years=10, required_return=0.15, margin=0.5)
    pbt = lambda t: valuation_criteria(v, 0.05, t)[0]
    assert pbt(DecisionThresholds(payback_max_years=12, fcf_yield_min=0))["passed"] is True
    assert pbt(DecisionThresholds(payback_max_years=8, fcf_yield_min=0))["passed"] is False


def test_fcf_criterion_tests_the_yield_against_the_floor():
    v = Valuation(ticker="T", price=100.0, eps=5.0, growth_rate=0.1,
                  future_pe=20.0, years=10, required_return=0.15, margin=0.5)

    def fcf(y, floor):
        t = DecisionThresholds(payback_max_years=12, fcf_yield_min=floor)
        return valuation_criteria(v, y, t)[2]

    assert fcf(0.03, 0)["passed"] is True        # positive clears a 0 floor
    assert fcf(0.03, 0.05)["passed"] is False    # 3% < 5% floor
    assert fcf(0.06, 0.05)["passed"] is True     # 6% clears 5% floor
    assert fcf(0.06, 0.05)["name"] == "Free Cash Flow yield"
    assert fcf(0.06, 0.05)["value"] == "6.0%"
    assert fcf(0.06, 0.05)["threshold"] == "≥ 5.0%"
    assert fcf(0.03, 0)["threshold"] == "≥ 0%"
