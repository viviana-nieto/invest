"""Decision-engine tests — the BUY/WATCH/PASS verdict is pure arithmetic.

The math makes the call: 3/3 criteria -> BUY, exactly 2 -> WATCH, <=1 -> PASS.
Conviction is monotonic in margin of safety, so the ranking is deterministic.
"""

from pathlib import Path

import pytest

from core.decision import (
    build_decisions,
    conviction_from_mos,
    decide_valuation,
    verdict_from_criteria,
)
from core.screen import load_config, rank_by_conviction
from core.valuation import Valuation

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.example.json"


def _crit(*passes):
    return [{"name": f"c{i}", "value": "", "threshold": "", "passed": p}
            for i, p in enumerate(passes)]


# ---- verdict logic ----------------------------------------------------------


def test_three_of_three_is_buy():
    assert verdict_from_criteria(_crit(True, True, True)) == "BUY"


def test_exactly_two_is_watch():
    assert verdict_from_criteria(_crit(True, True, False)) == "WATCH"
    assert verdict_from_criteria(_crit(False, True, True)) == "WATCH"


def test_one_or_zero_is_pass():
    assert verdict_from_criteria(_crit(True, False, False)) == "PASS"
    assert verdict_from_criteria(_crit(False, False, False)) == "PASS"


# ---- decide_valuation wires criteria + verdict together ---------------------


def test_decide_valuation_buy_all_pass():
    # sticker=150, buy<=75, price 70 => MoS positive; payback short; FCF positive.
    v = Valuation(ticker="T", price=70.0, eps=10.0, growth_rate=0.15,
                  future_pe=15.0, years=10, required_return=0.15, margin=0.50)
    d = decide_valuation(v, fcf_positive=True, narrative="hi")
    assert d["verdict"] == "BUY"
    assert [c["passed"] for c in d["criteria"]] == [True, True, True]
    assert d["narrative"] == "hi"


def test_decide_valuation_fcf_flips_buy_to_watch():
    v = Valuation(ticker="T", price=70.0, eps=10.0, growth_rate=0.15,
                  future_pe=15.0, years=10, required_return=0.15, margin=0.50)
    d = decide_valuation(v, fcf_positive=False)
    # Payback + MoS still pass, but FCF now fails => exactly 2 => WATCH.
    assert d["verdict"] == "WATCH"


def test_decide_valuation_pass_when_overpriced():
    # price 500 >> sticker 150 => MoS negative AND payback > 12y; only FCF passes
    # => exactly 1 criterion => PASS.
    v = Valuation(ticker="T", price=500.0, eps=10.0, growth_rate=0.15,
                  future_pe=15.0, years=10, required_return=0.15, margin=0.50)
    d = decide_valuation(v, fcf_positive=True)
    assert d["margin_of_safety"] < 0
    assert d["payback_years"] > 12
    assert d["verdict"] == "PASS"


def test_criteria_thresholds_and_values_shape():
    v = Valuation(ticker="T", price=70.0, eps=10.0, growth_rate=0.15,
                  future_pe=15.0, years=10, required_return=0.15, margin=0.50)
    names = [c["name"] for c in decide_valuation(v, True)["criteria"]]
    assert names == ["Payback Time", "Margin of Safety", "Free Cash Flow"]


# ---- conviction is monotonic ------------------------------------------------


def test_conviction_range_and_center():
    assert conviction_from_mos(0.0) == 50
    assert conviction_from_mos(10.0) > 95
    assert conviction_from_mos(-10.0) < 5


def test_conviction_monotonic_in_mos():
    xs = [-2.0, -0.5, 0.0, 0.3, 1.0]
    convs = [conviction_from_mos(x) for x in xs]
    assert convs == sorted(convs)


# ---- ranking on the sample universe -----------------------------------------


@pytest.fixture
def cfg():
    return load_config(CONFIG)


def test_build_decisions_ranked_by_conviction_desc(cfg):
    decisions = build_decisions(cfg)
    convs = [d["valuation"]["conviction"] for d in decisions]
    assert convs == sorted(convs, reverse=True)
    # Ranks are a 1..N sequence in order.
    assert [d["rank"] for d in decisions] == list(range(1, len(decisions) + 1))


def test_sample_top_ranks_are_the_buys(cfg):
    decisions = build_decisions(cfg)
    # NVDA has the deepest discount => highest conviction => rank 1, and BUY.
    assert decisions[0]["ticker"] == "NVDA"
    assert decisions[0]["valuation"]["verdict"] == "BUY"
    assert decisions[1]["ticker"] == "AMZN"
    assert decisions[1]["valuation"]["verdict"] == "BUY"


def test_sample_verdict_distribution(cfg):
    decisions = build_decisions(cfg)
    counts = {}
    for d in decisions:
        counts[d["valuation"]["verdict"]] = counts.get(d["valuation"]["verdict"], 0) + 1
    assert counts == {"BUY": 2, "WATCH": 4, "PASS": 3}


def test_screen_rank_by_conviction_matches(cfg):
    # screen.rank_by_conviction is the public entry point and must agree.
    assert rank_by_conviction(cfg) == build_decisions(cfg)


def test_every_decision_has_timing_block(cfg):
    for d in build_decisions(cfg):
        t = d["timing"]
        assert t["verdict"] in ("REACHING FLOOR", "NEUTRAL", "EXTENDED")
        assert len(t["signals"]) == 4
