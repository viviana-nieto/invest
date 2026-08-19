"""Optional live price fetch via yfinance — degrades gracefully when unavailable.

yfinance is an optional dependency and hits the network, so it is imported behind
a guard. If the package is missing or the network fails, callers get None (or the
config's sample price), and the rest of the engine still runs on sample
fundamentals. Nothing here is exercised by the test suite.
"""

from __future__ import annotations

try:  # optional dependency; the engine works without it
    import yfinance as _yf
    _HAVE_YF = True
except Exception:  # pragma: no cover - depends on the environment
    _yf = None
    _HAVE_YF = False


def have_yfinance() -> bool:
    """True if yfinance imported successfully."""
    return _HAVE_YF


def fetch_price(ticker: str) -> float | None:  # pragma: no cover - network
    """Return the latest close for `ticker`, or None if unavailable."""
    if not _HAVE_YF:
        return None
    try:
        hist = _yf.Ticker(ticker).history(period="1d")
        if hist is None or hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


def fetch_prices(tickers: list[str]) -> dict[str, float | None]:  # pragma: no cover - network
    """Fetch latest closes for many tickers. Missing/failed names map to None."""
    return {t: fetch_price(t) for t in tickers}


def fetch_ohlc(ticker: str, period: str = "1y"):  # pragma: no cover - network
    """Return (highs, lows, closes) numpy arrays of daily candles for `ticker`,
    or None if yfinance is unavailable or the fetch fails.

    Feeds `core.signals.timing_signals` with real candles instead of the sample
    series. Guarded import keeps the offline path working with no dependency.
    """
    if not _HAVE_YF:
        return None
    try:
        import numpy as np

        hist = _yf.Ticker(ticker).history(period=period)
        if hist is None or hist.empty:
            return None
        highs = np.asarray(hist["High"], dtype=float)
        lows = np.asarray(hist["Low"], dtype=float)
        closes = np.asarray(hist["Close"], dtype=float)
        return highs, lows, closes
    except Exception:
        return None


def enrich_config_with_live_prices(cfg: dict) -> dict:  # pragma: no cover - network
    """Overlay live prices onto the config watchlist where a fetch succeeds.

    Returns the same cfg object (mutated). Rows with a failed fetch keep their
    sample price, so `screen` always has a price to work with.
    """
    watchlist = cfg.get("skill", {}).get("watchlist", [])
    for row in watchlist:
        live = fetch_price(row["ticker"])
        if live is not None:
            row["price"] = live
    return cfg
