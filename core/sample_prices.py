"""Deterministic sample OHLC series so the timing lens runs with no network.

Each watchlist ticker is tagged with a `shape` (floor | neutral | extended) in the
config. Given a ticker + shape, `sample_ohlc` returns reproducible (highs, lows,
closes) numpy arrays crafted so the `core.signals` convergence verdict lands where
the shape says it should:

    floor    -> REACHING FLOOR   (>= 3 of 4 floor conditions met)
    neutral  -> NEUTRAL          (1-2 met)
    extended -> EXTENDED         (0 met; the tape is stretched)

The shapes are synthetic — illustrative, not real price history — but they are
fixed by a per-ticker seed so the dashboard looks identical every run. For live
candles, `core.fetch_prices.fetch_ohlc` can supply real data via yfinance.
"""

from __future__ import annotations

import numpy as np

N = 160  # bars per series


def _seed(ticker: str) -> int:
    return abs(hash(("invest-open", ticker))) % (2**32)


def _ohlc_from_close(closes: np.ndarray, rng: np.random.Generator):
    """Derive plausible highs/lows around a close path (small intrabar range)."""
    wiggle = np.abs(rng.normal(0.0, 0.004, size=closes.shape)) + 0.003
    highs = closes * (1.0 + wiggle)
    lows = closes * (1.0 - wiggle)
    return highs, lows, closes


def _floor(rng: np.random.Generator) -> np.ndarray:
    """A long decline that capitulates hard in the final bars, then ticks up once
    — puts recent price below the regression channel's lower rail and the 14-bar
    stochastic in oversold, with the MACD histogram just inflecting up."""
    n = N
    base = np.linspace(100.0, 70.0, n)                 # steady downtrend
    tail = np.zeros(n)
    tail[-12:] = -np.linspace(0, 9.0, 12)              # accelerating capitulation
    closes = base + tail + rng.normal(0.0, 0.25, n)
    closes[-1] = closes[-2] + 0.6                      # final up-tick (MACD inflects)
    return closes


def _extended(rng: np.random.Generator) -> np.ndarray:
    """A persistent uptrend that accelerates into the final bars, then eases once
    — price rides the upper rail, stochastic is overbought, MACD histogram rolls
    over, price sits well above its 50-day average. Nothing says 'floor'."""
    n = N
    base = np.linspace(70.0, 108.0, n)
    tail = np.zeros(n)
    tail[-12:] = np.linspace(0, 8.0, 12)               # blow-off top
    closes = base + tail + rng.normal(0.0, 0.25, n)
    closes[-1] = closes[-2] - 0.5                      # final easing (MACD rolls over)
    return closes


def _neutral(rng: np.random.Generator) -> np.ndarray:
    """A broad sideways range with mild waves — a mix of conditions, so the
    convergence lands in the middle (1-2 met)."""
    n = N
    t = np.linspace(0, 6 * np.pi, n)
    closes = 90.0 + 4.0 * np.sin(t) + rng.normal(0.0, 0.4, n)
    # Drift the very end down a touch so ~one or two conditions trip, not zero.
    closes[-10:] -= np.linspace(0, 2.5, 10)
    return closes


_SHAPES = {"floor": _floor, "neutral": _neutral, "extended": _extended}


def sample_closes(ticker: str, shape: str) -> np.ndarray:
    rng = np.random.default_rng(_seed(ticker))
    fn = _SHAPES.get(shape, _neutral)
    return fn(rng)


def sample_ohlc(ticker: str, shape: str):
    """Return (highs, lows, closes) numpy arrays for a ticker's sample series."""
    rng = np.random.default_rng(_seed(ticker) ^ 0x9E3779B9)
    closes = sample_closes(ticker, shape)
    return _ohlc_from_close(closes, rng)
