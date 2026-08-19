"""Black-Scholes tests against textbook reference values."""

import math

import pytest

from core.options import black_scholes_call, black_scholes_put, delta, price_option


# Canonical reference case (S=K=100, T=1, r=5%, sigma=20%).
S, K, T, r, sigma = 100.0, 100.0, 1.0, 0.05, 0.20


def test_call_reference_value():
    # Standard textbook result ~ 10.4506.
    assert black_scholes_call(S, K, T, r, sigma) == pytest.approx(10.4506, abs=0.01)


def test_put_via_parity():
    # Put-call parity: C - P = S - K e^(-rT).
    call = black_scholes_call(S, K, T, r, sigma)
    put = black_scholes_put(S, K, T, r, sigma)
    assert call - put == pytest.approx(S - K * math.exp(-r * T), abs=1e-6)
    # And the direct textbook put value ~ 5.5735.
    assert put == pytest.approx(5.5735, abs=0.01)


def test_call_delta_in_unit_interval():
    d = delta(S, K, T, r, sigma, "call")
    assert 0.0 <= d <= 1.0
    # ATM-ish call delta sits above 0.5 here (drift pulls it up).
    assert d == pytest.approx(0.6368, abs=0.01)


def test_put_delta_in_negative_unit_interval():
    d = delta(S, K, T, r, sigma, "put")
    assert -1.0 <= d <= 0.0


def test_t_zero_returns_intrinsic():
    assert black_scholes_call(110.0, 100.0, 0.0, r, sigma) == pytest.approx(10.0)
    assert black_scholes_call(90.0, 100.0, 0.0, r, sigma) == pytest.approx(0.0)
    assert black_scholes_put(90.0, 100.0, 0.0, r, sigma) == pytest.approx(10.0)
    assert black_scholes_put(110.0, 100.0, 0.0, r, sigma) == pytest.approx(0.0)


def test_t_zero_delta_is_step():
    assert delta(110.0, 100.0, 0.0, r, sigma, "call") == 1.0
    assert delta(90.0, 100.0, 0.0, r, sigma, "call") == 0.0
    assert delta(90.0, 100.0, 0.0, r, sigma, "put") == -1.0


def test_deep_itm_call_approaches_intrinsic():
    # A deep in-the-money call is worth roughly S - K e^(-rT).
    c = black_scholes_call(200.0, 100.0, T, r, sigma)
    assert c == pytest.approx(200.0 - 100.0 * math.exp(-r * T), abs=0.5)


def test_price_option_dict():
    out = price_option(S, K, T, r, sigma, "call")
    assert out["kind"] == "call"
    assert out["premium"] == pytest.approx(10.4506, abs=0.01)
    assert 0.0 <= out["delta"] <= 1.0


def test_invalid_kind_raises():
    with pytest.raises(ValueError):
        delta(S, K, T, r, sigma, "straddle")
    with pytest.raises(ValueError):
        price_option(S, K, T, r, sigma, "straddle")
