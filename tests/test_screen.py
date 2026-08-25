"""Screening tests — the deterministic ranking of the sample watchlist.

Seed-agnostic: tickers and counts are read from the config, never hardcoded,
so reseeding the sample watchlist cannot break these tests.
"""

from pathlib import Path

import pytest

from core.screen import load_config, screen, valuations_from_config

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.example.json"

# Valuation-level verdicts (core.valuation.Valuation.verdict) — distinct from
# the decision engine's BUY/WATCH/PASS.
VERDICTS = ("BUY", "WATCH", "OVERVALUED")


@pytest.fixture
def cfg():
    return load_config(CONFIG)


def watchlist_tickers(cfg):
    """The configured watchlist tickers, read dynamically from the config."""
    return [row["ticker"] for row in cfg["skill"]["watchlist"]]


def test_screen_ranks_by_margin_of_safety_descending(cfg):
    rows = screen(cfg, sort_by="margin_of_safety")
    mos = [r["margin_of_safety"] for r in rows]
    assert mos == sorted(mos, reverse=True)
    # Whatever the seed: the deepest discount in the universe leads the list
    # (cross-checked against the other sort order of the same universe).
    deepest = max(screen(cfg, sort_by="payback_years"),
                  key=lambda r: r["margin_of_safety"])
    assert rows[0]["ticker"] == deepest["ticker"]
    assert all(r["verdict"] in VERDICTS for r in rows)


def test_screen_ranks_by_payback_ascending(cfg):
    rows = screen(cfg, sort_by="payback_years")
    pbt = [r["payback_years"] for r in rows]
    assert pbt == sorted(pbt)
    # Whatever the seed: the shortest payback in the universe leads the list
    # (cross-checked against the other sort order of the same universe).
    shortest = min(screen(cfg, sort_by="margin_of_safety"),
                   key=lambda r: r["payback_years"])
    assert rows[0]["ticker"] == shortest["ticker"]


def test_screen_covers_whole_watchlist(cfg):
    rows = screen(cfg)
    # Exactly the configured universe: nothing dropped, nothing invented,
    # no duplicates.
    assert sorted(r["ticker"] for r in rows) == sorted(watchlist_tickers(cfg))


def test_valuations_use_config_defaults(cfg):
    skill = cfg["skill"]
    vals = valuations_from_config(cfg)
    assert len(vals) == len(skill["watchlist"])
    # The global valuation assumptions from the config apply to every row.
    for v in vals:
        assert v.required_return == skill["required_return"]
        assert v.margin == skill["margin_of_safety"]
        assert v.years == skill["projection_years"]


def test_screen_rejects_bad_sort_key(cfg):
    with pytest.raises(ValueError):
        screen(cfg, sort_by="alphabetical")
