"""Emit-contract tests — the emitted JSON must match the documented schema.

Validates data.json (per-stock fundamentals + verdict block), technicals.json
(per-ticker signal fields), screen.json, and macro_data.json for required keys
and correct types, so the dashboard can rely on the shape.
"""

from pathlib import Path

import pytest

from core import emit
from core.screen import load_config

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.example.json"


@pytest.fixture(scope="module")
def cfg():
    return load_config(CONFIG)


@pytest.fixture(scope="module")
def bundle(cfg):
    return emit.build_all(cfg)


REQUIRED_STOCK_KEYS = [
    "ticker", "name", "long_name", "sector", "industry", "website", "summary",
    "price", "prev_close", "day_change", "day_change_pct",
    "sparkline", "sparkline_1wk", "sparkline_1mo", "sparkline_6mo", "sparkline_1y", "sparkline_5y",
    "market_cap", "total_debt", "debt_to_equity", "free_cashflow", "fcf_yield",
    "operating_earnings", "net_earnings", "net_earnings_yield", "earnings_yield",
    "eps_growth_rate", "analyst_eps_growth", "revenue_growth", "growth_years", "growth_label",
    "cagr_periods", "dividend_yield", "insider_ownership", "volatility_6mo", "volatility_1yr",
    "verdict",
]

SPARK_KEYS = ["sparkline", "sparkline_1wk", "sparkline_1mo", "sparkline_6mo", "sparkline_1y", "sparkline_5y"]

TECH_KEYS = [
    "stoch_k", "stoch_d", "stoch_pass", "stoch_sell", "macd_pass", "macd_sell",
    "ma_pass", "ma_sell", "at_lower_rail", "at_upper_rail",
    "channel_position", "channel_position_long", "long_window", "tier", "ceiling_tier",
    "timing",
]


def test_data_is_a_list_of_complete_stock_objects(bundle):
    data = bundle["data"]
    assert isinstance(data, list) and len(data) == 9
    for o in data:
        for k in REQUIRED_STOCK_KEYS:
            assert k in o, f"{o.get('ticker')} missing {k}"
        assert isinstance(o["price"], (int, float))
        assert isinstance(o["market_cap"], (int, float))
        assert isinstance(o["cagr_periods"], dict)
        for p in ("1yr", "3yr", "5yr", "7yr", "10yr"):
            assert p in o["cagr_periods"]


def test_sparklines_are_nonempty_float_arrays(bundle):
    for o in bundle["data"]:
        for k in SPARK_KEYS:
            arr = o[k]
            assert isinstance(arr, list) and len(arr) > 0
            assert all(isinstance(x, (int, float)) for x in arr)


def test_verdict_block_shape(bundle):
    for o in bundle["data"]:
        v = o["verdict"]
        assert v["verdict"] in ("BUY", "WATCH", "PASS")
        assert isinstance(v["conviction"], int) and 0 <= v["conviction"] <= 100
        assert isinstance(v["criteria"], list) and len(v["criteria"]) == 3
        for c in v["criteria"]:
            assert {"name", "value", "threshold", "passed"} <= set(c)
            assert isinstance(c["passed"], bool)


def test_technicals_complete_per_ticker(bundle):
    sigs = bundle["technicals"]["signals"]
    tickers = [o["ticker"] for o in bundle["data"]]
    for tk in tickers:
        assert tk in sigs, f"technicals missing {tk}"
        s = sigs[tk]
        for k in TECH_KEYS:
            assert k in s, f"{tk} technicals missing {k}"
        for b in ("stoch_pass", "stoch_sell", "macd_pass", "macd_sell", "ma_pass",
                  "ma_sell", "at_lower_rail", "at_upper_rail"):
            assert isinstance(s[b], bool)
        assert s["tier"] in ("strong", "setting-up", "watching")
        assert s["ceiling_tier"] in ("strong", "setting-up", "watching")
        assert s["timing"] in ("REACHING FLOOR", "NEUTRAL", "REACHING CEILING")
        assert s["long_window"] == 160


def test_technicals_timing_verdict_matches_shape(bundle, cfg):
    """floor-shape names reach the floor, extended-shape names reach the
    ceiling, neutral-shape names stay neutral."""
    shapes = {r["ticker"]: r.get("shape", "neutral")
              for r in cfg["skill"]["watchlist"]}
    expected = {"floor": "REACHING FLOOR", "neutral": "NEUTRAL",
                "extended": "REACHING CEILING"}
    sigs = bundle["technicals"]["signals"]
    for tk, shape in shapes.items():
        assert sigs[tk]["timing"] == expected[shape], (tk, shape, sigs[tk]["timing"])


def test_extended_names_carry_a_real_ceiling_read(bundle, cfg):
    """At the upper rail the sell confirmations must actually fire: overbought
    stochastic + MACD rolling over -> strong ceiling tier."""
    shapes = {r["ticker"]: r.get("shape", "neutral")
              for r in cfg["skill"]["watchlist"]}
    sigs = bundle["technicals"]["signals"]
    extended = [tk for tk, sh in shapes.items() if sh == "extended"]
    assert extended, "config must carry at least one extended-shape name"
    for tk in extended:
        s = sigs[tk]
        assert s["at_upper_rail"] is True
        assert s["stoch_sell"] is True
        assert s["macd_sell"] is True
        assert s["ceiling_tier"] == "strong"


def test_screen_shape(bundle):
    s = bundle["screen"]
    assert set(["generated", "criteria", "universe", "pass", "watch"]) <= set(s)
    assert set(["pbt_max", "fcf_yield_min"]) <= set(s["criteria"])
    assert s["criteria"]["pbt_max"] == 10.0
    assert s["criteria"]["fcf_yield_min"] == 0.05
    assert isinstance(s["universe"], list) and s["universe"]
    for bucket in ("pass", "watch"):
        for e in s[bucket]:
            assert {"ticker", "name", "payback_years", "fcf_yield",
                    "pbt_ok", "fcf_ok"} <= set(e)


def test_screen_buckets_apply_both_cuts(bundle):
    s = bundle["screen"]
    pbt_max = s["criteria"]["pbt_max"]
    fcf_min = s["criteria"]["fcf_yield_min"]
    for e in s["pass"]:
        assert e["payback_years"] <= pbt_max and e["fcf_yield"] >= fcf_min
        assert e["pbt_ok"] and e["fcf_ok"]
    for e in s["watch"]:
        # Watch == meets exactly one of the two cuts.
        assert e["pbt_ok"] != e["fcf_ok"]


def test_macro_shape(bundle):
    m = bundle["macro"]
    assert set(["fed_policy", "inflation", "labor", "market_indicators", "news"]) <= set(m)
    assert isinstance(m["market_indicators"], list) and m["market_indicators"]
    assert isinstance(m["news"], list) and m["news"]
    for n in m["news"]:
        assert {"headline", "source", "sentiment", "summary"} <= set(n)


def test_write_all_produces_every_file(cfg, tmp_path):
    sample_dir = tmp_path / "sample-data"
    data_js = tmp_path / "dash" / "data.js"
    emit.write_all(cfg, sample_dir=sample_dir, data_js=data_js)
    for f in ["data.json", "technicals.json", "screen.json", "macro_data.json"]:
        assert (sample_dir / f).exists(), f
    # The Exploration tab is gone — its file must no longer be emitted.
    assert not (sample_dir / "exploration.json").exists()
    assert data_js.exists()
    assert data_js.read_text().startswith("window.INVEST_DATA =")
    assert '"exploration"' not in data_js.read_text()
