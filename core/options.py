"""Black-Scholes European option pricing — deterministic, no LLM.

Standard Black-Scholes-Merton model for European calls and puts on a
non-dividend-paying underlying:

    d1 = (ln(S/K) + (r + sigma^2/2) T) / (sigma sqrt(T))
    d2 = d1 - sigma sqrt(T)
    C  = S N(d1) - K e^(-rT) N(d2)
    P  = K e^(-rT) N(-d2) - S N(-d1)        (equivalently, via put-call parity)

N() is the standard normal CDF (scipy.stats.norm.cdf).

At expiry (T == 0) an option is worth exactly its intrinsic value, which we
return directly to avoid division by zero.
"""

from __future__ import annotations

import math

from scipy.stats import norm


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float) -> tuple[float, float]:
    """Compute the Black-Scholes d1 and d2 terms."""
    denom = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / denom
    d2 = d1 - denom
    return d1, d2


def black_scholes_call(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Price of a European call.

    Args:
        S: current underlying price.
        K: strike price.
        T: time to expiry in years.
        r: continuously-compounded risk-free rate (decimal).
        sigma: annualized volatility (decimal).

    Returns:
        The call premium. At T == 0 (or sigma == 0) returns intrinsic value
        max(S - K, 0).
    """
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0)
    d1, d2 = _d1_d2(S, K, T, r, sigma)
    return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)


def black_scholes_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Price of a European put, via put-call parity.

    parity:  C - P = S - K e^(-rT)   =>   P = C - S + K e^(-rT)

    At T == 0 (or sigma == 0) returns intrinsic value max(K - S, 0).
    """
    if T <= 0 or sigma <= 0:
        return max(K - S, 0.0)
    call = black_scholes_call(S, K, T, r, sigma)
    return call - S + K * math.exp(-r * T)


def delta(S: float, K: float, T: float, r: float, sigma: float,
          kind: str = "call") -> float:
    """Option delta — sensitivity of price to a $1 move in the underlying.

    Call delta = N(d1) in [0, 1]; put delta = N(d1) - 1 in [-1, 0].

    At T == 0 (or sigma == 0) delta collapses to the step function: 1/0 for a
    call depending on whether it is in the money, and 0/-1 for a put.
    """
    if kind not in ("call", "put"):
        raise ValueError("kind must be 'call' or 'put'")

    if T <= 0 or sigma <= 0:
        if kind == "call":
            return 1.0 if S > K else 0.0
        return -1.0 if S < K else 0.0

    d1, _ = _d1_d2(S, K, T, r, sigma)
    nd1 = norm.cdf(d1)
    return nd1 if kind == "call" else nd1 - 1.0


def price_option(S: float, K: float, T: float, r: float, sigma: float,
                 kind: str = "call") -> dict:
    """Convenience: price + delta for one option as a dict (dashboard-friendly)."""
    if kind == "call":
        premium = black_scholes_call(S, K, T, r, sigma)
    elif kind == "put":
        premium = black_scholes_put(S, K, T, r, sigma)
    else:
        raise ValueError("kind must be 'call' or 'put'")
    return {
        "kind": kind,
        "S": S,
        "K": K,
        "T": T,
        "r": r,
        "sigma": sigma,
        "premium": round(premium, 4),
        "delta": round(delta(S, K, T, r, sigma, kind), 4),
    }
