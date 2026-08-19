"""Payback Time + fair-value tests against hand-computed reference values."""

import pytest

from core.valuation import (
    Valuation,
    margin_of_safety,
    margin_of_safety_price,
    payback_time,
    sticker_price,
)


def test_payback_time_zero_growth_is_exact():
    # With g=0, price 100 and eps 10 repay in exactly 10 flat years.
    assert payback_time(100.0, 10.0, 0.0) == pytest.approx(10.0, abs=1e-9)


def test_payback_time_with_growth_reference():
    # Hand-computed: sum_{y=1}^{7} 10*1.1^y crosses 100 partway through year 7.
    # cumulative through y6 = 84.872..., year-7 earnings = 19.487..., so
    # payback = 6 + (100-84.872)/19.487 = 6.7763...
    assert payback_time(100.0, 10.0, 0.10) == pytest.approx(6.7763, abs=1e-3)


def test_payback_time_faster_growth_is_shorter():
    slow = payback_time(100.0, 10.0, 0.05)
    fast = payback_time(100.0, 10.0, 0.25)
    assert fast < slow


def test_payback_time_rejects_nonpositive_eps():
    with pytest.raises(ValueError):
        payback_time(100.0, 0.0, 0.10)
    with pytest.raises(ValueError):
        payback_time(100.0, -5.0, 0.10)


def test_sticker_price_reference():
    # eps=10, g=0.15, future_pe=15, years=10, required_return=0.15.
    # Because required_return == growth, the (1+g)^10 and (1+r)^10 cancel, so
    # sticker = eps * future_pe = 150 exactly.
    assert sticker_price(10.0, 0.15, 15.0, years=10, required_return=0.15) == pytest.approx(150.0, abs=1e-6)


def test_margin_of_safety_price_halves_sticker_by_default():
    assert margin_of_safety_price(150.0) == pytest.approx(75.0)
    assert margin_of_safety_price(200.0, margin=0.25) == pytest.approx(150.0)


def test_margin_of_safety_sign():
    # Price well below sticker => positive cushion.
    assert margin_of_safety(100.0, 200.0) == pytest.approx(0.5)
    # Price above sticker => negative (overpriced).
    assert margin_of_safety(250.0, 200.0) == pytest.approx(-0.25)


def test_valuation_verdict_buy_when_cheap():
    # sticker = 150, buy price (50% MoS) = 75; price 70 <= 75 => BUY.
    v = Valuation(ticker="TEST", price=70.0, eps=10.0, growth_rate=0.15,
                  future_pe=15.0, years=10, required_return=0.15, margin=0.50)
    assert v.sticker == pytest.approx(150.0, abs=1e-6)
    assert v.buy_price == pytest.approx(75.0, abs=1e-6)
    assert v.verdict == "BUY"


def test_valuation_verdict_watch_and_overvalued():
    watch = Valuation(ticker="W", price=120.0, eps=10.0, growth_rate=0.15,
                      future_pe=15.0, years=10, required_return=0.15, margin=0.50)
    # 75 < 120 < 150 => below fair value but not past the margin => WATCH.
    assert watch.verdict == "WATCH"

    over = Valuation(ticker="O", price=200.0, eps=10.0, growth_rate=0.15,
                     future_pe=15.0, years=10, required_return=0.15, margin=0.50)
    # 200 > sticker 150 => OVERVALUED.
    assert over.verdict == "OVERVALUED"


def test_valuation_to_dict_shape():
    v = Valuation(ticker="TEST", price=70.0, eps=10.0, growth_rate=0.15,
                  future_pe=15.0, years=10, required_return=0.15, margin=0.50)
    d = v.to_dict()
    assert d["ticker"] == "TEST"
    assert set(d) >= {"payback_years", "sticker_price", "buy_price",
                      "margin_of_safety", "verdict"}
