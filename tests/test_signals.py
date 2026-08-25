"""Floor-signal engine tests against KNOWN series with hand-computed values.

Indicators are checked in isolation on tiny, fully-specified inputs, then the
convergence verdict is checked on three shaped series: a declining-then-turning
series (REACHING FLOOR), a strong uptrend (EXTENDED), and an oscillation (NEUTRAL).
"""

import numpy as np
import pytest

from core import signals as s


# ---- primitives: exact hand-computed values ---------------------------------


def test_sma_matches_hand_value():
    # mean of the last 3 of [1,2,3,4,5] = (3+4+5)/3 = 4.
    out = s.sma([1, 2, 3, 4, 5], 3)
    assert out[-1] == pytest.approx(4.0)
    assert np.isnan(out[0]) and np.isnan(out[1])  # first period-1 are undefined


def test_ema_alpha_one_is_identity():
    # period=1 => alpha=1 => EMA reproduces the series.
    out = s.ema([1.0, 2.0, 3.0], 1)
    assert out.tolist() == [1.0, 2.0, 3.0]


def test_ema_of_constant_is_constant():
    out = s.ema([5.0, 5.0, 5.0, 5.0], 3)
    assert out.tolist() == [5.0, 5.0, 5.0, 5.0]


def test_linreg_slope_recovers_line():
    # closes = 2t + 5 => least-squares slope is exactly 2.
    closes = 2.0 * np.arange(80.0) + 5.0
    ch = s.linreg_channel(closes, period=80)
    assert ch["slope"] == pytest.approx(2.0, abs=1e-6)


def test_stochastic_midpoint_is_fifty():
    # 14-bar high=110, low=90, close pinned at 100 => %K = 100*(100-90)/20 = 50.
    highs = np.full(20, 110.0)
    lows = np.full(20, 90.0)
    closes = np.full(20, 100.0)
    st = s.stochastic(highs, lows, closes)
    assert st["k"] == pytest.approx(50.0)
    assert st["d"] == pytest.approx(50.0)


def test_stochastic_oversold_and_overbought():
    highs = np.full(20, 110.0)
    lows = np.full(20, 90.0)
    # close at 92 => %K = 100*(2/20) = 10 (oversold, < 20).
    assert s.stochastic(highs, lows, np.full(20, 92.0))["k"] == pytest.approx(10.0)
    # close at 108 => %K = 90 (overbought).
    assert s.stochastic(highs, lows, np.full(20, 108.0))["k"] == pytest.approx(90.0)


def test_macd_histogram_turns_up_on_reversal():
    # Decline that capitulates then ticks up => histogram change positive.
    closes = np.linspace(100.0, 70.0, 160)
    closes[-12:] += -np.linspace(0.0, 9.0, 12)
    closes[-1] = closes[-2] + 0.6
    assert s.macd(closes)["hist_change"] > 0.0

    # Steady rise with a final down-tick => histogram change negative.
    rise = np.linspace(60.0, 120.0, 160).copy()
    rise[-1] = rise[-2] - 1.5
    assert s.macd(rise)["hist_change"] < 0.0


# ---- convergence verdicts on shaped series ----------------------------------


def _floor_series():
    closes = np.linspace(100.0, 70.0, 160)
    closes[-12:] += -np.linspace(0.0, 9.0, 12)  # capitulation
    closes[-1] = closes[-2] + 0.6               # final up-tick
    highs = closes * 1.005
    lows = closes * 0.995
    return highs, lows, closes


def test_declining_then_turning_is_reaching_floor():
    highs, lows, closes = _floor_series()
    t = s.timing_signals(closes, highs=highs, lows=lows)
    assert t["verdict"] == "REACHING FLOOR"
    assert t["met"] >= 3
    by_name = {sig["name"]: sig["met"] for sig in t["signals"]}
    # The three signals the prompt calls out must all fire.
    assert by_name["Stochastic 14,5,3"] is True       # oversold
    assert by_name["LinReg Channel"] is True           # at/below lower rail
    assert by_name["MACD 8,17,9"] is True              # histogram turning up
    assert t["score"].endswith("floor conditions met")


def test_strong_uptrend_is_extended():
    up = np.linspace(60.0, 120.0, 160)
    t = s.timing_signals(up, highs=up * 1.004, lows=up * 0.996)
    assert t["verdict"] == "EXTENDED"
    assert t["met"] == 0


def test_oscillation_is_neutral():
    x = np.linspace(0.0, 6.0 * np.pi, 160)
    osc = 100.0 + 5.0 * np.sin(x)
    t = s.timing_signals(osc, highs=osc * 1.004, lows=osc * 0.996)
    assert t["verdict"] == "NEUTRAL"
    assert 1 <= t["met"] <= 2


def test_signals_default_highs_lows_to_closes():
    # Passing only closes must not crash (highs/lows default to closes).
    closes = np.linspace(100.0, 80.0, 60)
    t = s.timing_signals(closes)
    assert t["total"] == 4
    assert len(t["signals"]) == 4


# ---- ceiling (sell/trim) mirror + combined timing verdict -------------------


CEILING_FIELDS = [
    "stoch_sell", "macd_sell", "ma_sell", "at_upper_rail",
    "ceiling_confirms", "ceiling_tier",
]


def _ceiling_series():
    """A persistent uptrend that blows off then eases once — overbought
    stochastic, MACD histogram rolling over, price pressed above the upper
    linreg rail. The synthetic mirror of `_floor_series`."""
    closes = np.linspace(70.0, 108.0, 160)
    closes[-12:] += np.linspace(0.0, 8.0, 12)   # blow-off top
    closes[-1] = closes[-2] - 0.5               # final easing (MACD rolls over)
    highs = closes * 1.005
    lows = closes * 0.995
    return highs, lows, closes


def test_rail_checks_produces_all_ceiling_fields():
    highs, lows, closes = _ceiling_series()
    rc = s.rail_checks(closes, highs=highs, lows=lows)
    for k in CEILING_FIELDS:
        assert k in rc, f"rail_checks missing {k}"
    for b in ("stoch_sell", "macd_sell", "ma_sell", "at_upper_rail", "at_lower_rail"):
        assert isinstance(rc[b], bool)
    assert rc["ceiling_tier"] in ("strong", "setting-up", "watching")
    assert rc["timing"] in ("REACHING FLOOR", "NEUTRAL", "REACHING CEILING")


def test_blowoff_top_is_reaching_ceiling():
    highs, lows, closes = _ceiling_series()
    rc = s.rail_checks(closes, highs=highs, lows=lows)
    assert rc["timing"] == "REACHING CEILING"
    assert rc["at_upper_rail"] is True and rc["at_lower_rail"] is False
    assert rc["stoch_sell"] is True          # overbought (%K > 80)
    assert rc["macd_sell"] is True           # histogram rolling over
    assert rc["ceiling_confirms"] >= 2
    assert rc["ceiling_tier"] == "strong"
    # Still riding above its SMA50 — the 50-day is not yet lost.
    assert rc["ma_sell"] is False


def test_capitulation_is_reaching_floor_in_rail_checks():
    highs, lows, closes = _floor_series()
    rc = s.rail_checks(closes, highs=highs, lows=lows)
    assert rc["timing"] == "REACHING FLOOR"
    assert rc["at_lower_rail"] is True and rc["at_upper_rail"] is False
    assert rc["stoch_pass"] is True          # oversold (%K < 20)
    assert rc["macd_pass"] is True           # histogram turning up
    assert rc["floor_confirms"] >= 2
    assert rc["tier"] == "strong"


def test_oscillation_is_neutral_in_rail_checks():
    x = np.linspace(0.0, 6.0 * np.pi, 160)
    osc = 100.0 + 5.0 * np.sin(x)
    rc = s.rail_checks(osc, highs=osc * 1.004, lows=osc * 0.996)
    assert rc["timing"] == "NEUTRAL"


def test_rails_are_mutually_exclusive():
    # DIP_MAX < CEILING_MIN, so no position can trip both rails.
    assert s.DIP_MAX < s.CEILING_MIN
    for series in (_floor_series(), _ceiling_series()):
        highs, lows, closes = series
        rc = s.rail_checks(closes, highs=highs, lows=lows)
        assert not (rc["at_lower_rail"] and rc["at_upper_rail"])


def test_confirmation_tier_thresholds():
    assert s.confirmation_tier(3) == "strong"
    assert s.confirmation_tier(2) == "strong"
    assert s.confirmation_tier(1) == "setting-up"
    assert s.confirmation_tier(0) == "watching"


def test_floor_side_of_rail_checks_matches_timing_signals():
    # The floor booleans inside rail_checks must agree with the floor-only lens.
    highs, lows, closes = _floor_series()
    rc = s.rail_checks(closes, highs=highs, lows=lows)
    t = s.timing_signals(closes, highs=highs, lows=lows)
    by_name = {x["name"]: x["met"] for x in t["signals"]}
    assert rc["stoch_pass"] == by_name["Stochastic 14,5,3"]
    assert rc["macd_pass"] == by_name["MACD 8,17,9"]
    assert rc["ma_pass"] == by_name["Price vs SMA50"]
