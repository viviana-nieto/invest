"""Payback Time (PBT) valuation — a deterministic value-investing engine.

Clean-room implementation of two standard value-investing calculations popularized
by Phil Town's *Payback Time* and *Rule #1*:

1. Payback Time — how many years of cumulative, growing earnings it takes to repay
   the price you pay today. Lower is better (a shorter payback = cheaper business).
2. Sticker price (fair value) — project EPS out N years, apply a future P/E, then
   discount back to today at a required rate of return. Buy only with a margin of
   safety below that number.

No LLM, no network — just arithmetic. The numbers make the call.
"""

from __future__ import annotations

from dataclasses import dataclass


def payback_time(price: float, eps: float, growth_rate: float,
                 max_years: int = 100) -> float:
    """Years for cumulative growing earnings to repay `price`.

    Each future year contributes eps*(1+g)^year (year starts at 1). We sum until
    the running total reaches `price`, then linearly interpolate within the final
    year so the result is a smooth float rather than a whole number of years.

    Args:
        price: what you pay today (per-share price, or total market cap if `eps`
            is total net income).
        eps: current trailing earnings per share (or net income).
        growth_rate: expected annual earnings growth, as a decimal (0.15 == 15%).
        max_years: cap on the search; if earnings never repay price, returns
            `float(max_years)` as a sentinel "too long".

    Returns:
        Payback time in years (float). Lower means cheaper.

    Raises:
        ValueError: if eps <= 0 (a company with no earnings has no payback) or
            price <= 0.
    """
    if price <= 0:
        raise ValueError("price must be positive")
    if eps <= 0:
        raise ValueError("payback time is undefined for non-positive earnings")

    cumulative = 0.0
    for year in range(1, max_years + 1):
        year_earnings = eps * (1.0 + growth_rate) ** year
        prev_cumulative = cumulative
        cumulative += year_earnings
        if cumulative >= price:
            # Linear interpolation within this year for a smooth fractional result.
            remaining = price - prev_cumulative
            fraction = remaining / year_earnings
            return (year - 1) + fraction
    return float(max_years)


def future_eps(eps: float, growth_rate: float, years: int) -> float:
    """Project EPS `years` into the future at a constant growth rate."""
    return eps * (1.0 + growth_rate) ** years


def sticker_price(eps: float, growth_rate: float, future_pe: float,
                  years: int = 10, required_return: float = 0.15) -> float:
    """Fair value ("sticker price") of a share today.

    Standard Rule #1 method:
        future_price = future_eps(eps, g, years) * future_pe
        sticker      = future_price / (1 + required_return)^years

    Args:
        eps: current earnings per share.
        growth_rate: expected annual EPS growth (decimal).
        future_pe: the P/E multiple you expect in `years` (a common heuristic is
            min(2*growth_pct, historical_pe); the caller supplies it directly).
        years: projection horizon (default 10).
        required_return: discount rate / minimum acceptable annual return
            (default 0.15 == 15%).

    Returns:
        Fair value per share today.
    """
    fut_price = future_eps(eps, growth_rate, years) * future_pe
    return fut_price / (1.0 + required_return) ** years


def margin_of_safety_price(sticker: float, margin: float = 0.50) -> float:
    """Buy price = sticker price discounted by a margin of safety (default 50%)."""
    return sticker * (1.0 - margin)


def margin_of_safety(price: float, sticker: float) -> float:
    """How far below fair value the current price sits, as a decimal.

    Positive means the stock trades below sticker (a discount / cushion);
    negative means it trades above fair value (overpriced).
        MoS = (sticker - price) / sticker
    """
    if sticker <= 0:
        raise ValueError("sticker price must be positive")
    return (sticker - price) / sticker


@dataclass
class Valuation:
    """A full deterministic valuation for one ticker."""

    ticker: str
    price: float
    eps: float
    growth_rate: float
    future_pe: float
    years: int
    required_return: float
    margin: float

    @property
    def payback_years(self) -> float:
        return payback_time(self.price, self.eps, self.growth_rate)

    @property
    def sticker(self) -> float:
        return sticker_price(self.eps, self.growth_rate, self.future_pe,
                             self.years, self.required_return)

    @property
    def buy_price(self) -> float:
        return margin_of_safety_price(self.sticker, self.margin)

    @property
    def margin_of_safety(self) -> float:
        return margin_of_safety(self.price, self.sticker)

    @property
    def verdict(self) -> str:
        """A deterministic call: the math decides, not an LLM."""
        if self.price <= self.buy_price:
            return "BUY"
        if self.margin_of_safety > 0:
            return "WATCH"
        return "OVERVALUED"

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "price": round(self.price, 2),
            "eps": round(self.eps, 2),
            "growth_rate": self.growth_rate,
            "future_pe": self.future_pe,
            "payback_years": round(self.payback_years, 2),
            "sticker_price": round(self.sticker, 2),
            "buy_price": round(self.buy_price, 2),
            "margin_of_safety": round(self.margin_of_safety, 4),
            "verdict": self.verdict,
        }
