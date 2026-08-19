"""Screening tests — the deterministic ranking of the sample watchlist."""

from pathlib import Path

import pytest

from core.screen import load_config, screen, valuations_from_config

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.example.json"


@pytest.fixture
def cfg():
    return load_config(CONFIG)


def test_screen_ranks_by_margin_of_safety_descending(cfg):
    rows = screen(cfg, sort_by="margin_of_safety")
    mos = [r["margin_of_safety"] for r in rows]
    assert mos == sorted(mos, reverse=True)
    # NVDA has the deepest discount in the sample set => ranked first.
    assert rows[0]["ticker"] == "NVDA"
    assert rows[0]["verdict"] == "BUY"


def test_screen_ranks_by_payback_ascending(cfg):
    rows = screen(cfg, sort_by="payback_years")
    pbt = [r["payback_years"] for r in rows]
    assert pbt == sorted(pbt)
    # JPM has the shortest payback (highest EPS relative to price).
    assert rows[0]["ticker"] == "JPM"


def test_screen_covers_whole_watchlist(cfg):
    rows = screen(cfg)
    tickers = {r["ticker"] for r in rows}
    assert tickers == {"AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
                       "JPM", "XOM", "JNJ", "WMT"}


def test_valuations_use_config_defaults(cfg):
    vals = {v.ticker: v for v in valuations_from_config(cfg)}
    # JNJ omits future_pe override? No — every row has one here; default is 15.
    assert vals["NVDA"].required_return == 0.15
    assert vals["NVDA"].margin == 0.50
    assert vals["NVDA"].years == 10


def test_screen_rejects_bad_sort_key(cfg):
    with pytest.raises(ValueError):
        screen(cfg, sort_by="alphabetical")
