"""Access-layer tests: the MCP tool functions.

The four tool bodies are plain functions wrapping the deterministic core, so
they are tested directly — no MCP SDK required. Building the actual FastMCP
server is exercised only when the `mcp` package happens to be installed.
"""

import pytest

from adapters.mcp import server as srv
from core.screen import _resolve_config, load_config

VERDICTS = ("BUY", "WATCH", "PASS")
TIMING_VERDICTS = ("REACHING FLOOR", "NEUTRAL", "EXTENDED")

# Read the configured watchlist dynamically (same resolution the server uses)
# so a reseed of the sample config can never break these tests.
CFG = load_config(_resolve_config(None))
KNOWN = [r["ticker"] for r in CFG["skill"]["watchlist"]]
TICKER = KNOWN[0]           # guaranteed on the watchlist, whatever the seed
ABSENT = "ZZZZ"             # guaranteed off it
assert ABSENT not in KNOWN


# ---- screen_watchlist ---------------------------------------------------------


def test_screen_watchlist_shape():
    out = srv.screen_watchlist()
    assert out["count"] == len(out["ranked"]) > 0
    assert "deterministic" in out["governance"]

    for i, row in enumerate(out["ranked"], start=1):
        assert row["rank"] == i                          # ranked, 1-based, ordered
        assert row["verdict"] in VERDICTS
        assert 0 <= row["conviction"] <= 100
        assert row["timing_verdict"] in TIMING_VERDICTS
        assert len(row["criteria"]) == 3                 # the evidence checklist
        for c in row["criteria"]:
            assert set(c) == {"name", "value", "threshold", "passed"}


def test_screen_watchlist_verdict_matches_criteria():
    # Trust pillar: the verdict must be recomputable from the shown evidence.
    for row in srv.screen_watchlist()["ranked"]:
        passed = sum(1 for c in row["criteria"] if c["passed"])
        expected = "BUY" if passed == 3 else "WATCH" if passed == 2 else "PASS"
        assert row["verdict"] == expected


def test_screen_watchlist_is_deterministic():
    a = srv.screen_watchlist()
    b = srv.screen_watchlist()
    assert [r["ticker"] for r in a["ranked"]] == [r["ticker"] for r in b["ranked"]]
    assert [r["verdict"] for r in a["ranked"]] == [r["verdict"] for r in b["ranked"]]


# ---- analyze_ticker -------------------------------------------------------------


def test_analyze_ticker_evidence_trail():
    out = srv.analyze_ticker(TICKER.lower())             # case-insensitive
    assert out["ticker"] == TICKER
    assert out["valuation"]["verdict"] in VERDICTS
    assert len(out["valuation"]["criteria"]) == 3
    assert "Payback Time" in [c["name"] for c in out["valuation"]["criteria"]]
    assert out["timing"]["verdict"] in TIMING_VERDICTS
    assert 1 <= out["rank"] <= out["universe"]
    assert "governance" in out


def test_analyze_ticker_unknown_is_helpful():
    out = srv.analyze_ticker(ABSENT)
    assert "unknown ticker" in out["error"]
    # The error must list the real, currently configured watchlist.
    assert set(out["known_tickers"]) == set(KNOWN)


# ---- floor_signals ---------------------------------------------------------------


def test_floor_signals_four_signals_and_convergence():
    out = srv.floor_signals(TICKER)
    assert "error" not in out
    assert out["total"] == 4
    assert len(out["signals"]) == 4
    names = [s["name"] for s in out["signals"]]
    assert names == ["LinReg Channel", "Stochastic 14,5,3", "MACD 8,17,9",
                     "Price vs SMA50"]
    for s in out["signals"]:
        assert set(s) == {"name", "value", "met", "detail"}
    # Convergence verdict is a pure function of how many signals fired.
    met = sum(1 for s in out["signals"] if s["met"])
    assert out["met"] == met
    expected = ("REACHING FLOOR" if met >= 3
                else "EXTENDED" if met == 0 else "NEUTRAL")
    assert out["verdict"] == expected


def test_floor_signals_unknown_ticker():
    out = srv.floor_signals("ZZZZ")
    assert "unknown ticker" in out["error"]


# ---- price_option -----------------------------------------------------------------


def test_price_option_matches_core_engine():
    from core.options import price_option as bs

    row = next(r for r in CFG["skill"]["watchlist"] if r["ticker"] == TICKER)
    strike = round(row["price"] * 1.1, 2)       # near the money, whatever the seed

    out = srv.price_option(TICKER, strike=strike, expiry_years=1.0,
                           vol=0.25, rate=0.04, kind="call")
    expected = bs(S=row["price"], K=strike, T=1.0, r=0.04, sigma=0.25, kind="call")
    assert out["premium"] == expected["premium"]
    assert out["delta"] == expected["delta"]
    assert out["premium"] > 0
    assert 0.0 < out["delta"] < 1.0


def test_price_option_put_has_negative_delta():
    S = next(r["price"] for r in CFG["skill"]["watchlist"] if r["ticker"] == TICKER)
    out = srv.price_option(TICKER, strike=S, expiry_years=0.5, kind="put")
    assert -1.0 < out["delta"] < 0.0
    assert out["premium"] > 0


def test_price_option_unknown_ticker():
    out = srv.price_option(ABSENT, strike=100)
    assert "unknown ticker" in out["error"]


# ---- FastMCP wrapper (only when the SDK is installed) -------------------------------


def test_create_server_without_sdk_raises(monkeypatch):
    monkeypatch.setattr(srv, "FastMCP", None)
    with pytest.raises(RuntimeError, match="pip install mcp"):
        srv.create_server()


def test_create_server_with_sdk_registers_tools():
    pytest.importorskip("mcp", reason="MCP SDK not installed (pip install mcp)")
    server = srv.create_server()
    assert server is not None
    assert server.name == "invest-open"
