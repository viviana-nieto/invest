"""MCP server — the deterministic engine, dropped into the tools a team already uses.

Exposes `core/` as four MCP tools so Claude Desktop, Cursor, or any MCP-capable
internal chat can call the SAME deterministic engine everyone else uses. The
client's model may phrase the question and read the result aloud, but every
verdict, rank, and price below comes from arithmetic in `core/` — the LLM never
decides. Each tool returns a structured, evidence-bearing result (criteria
met/failed with the numbers), not a bare opinion.

Run it (requires the official MCP Python SDK):

    pip install mcp
    python3 adapters/mcp/server.py

See adapters/mcp/README.md for the Claude Desktop / Cursor config snippet.

The tool bodies are plain functions; the FastMCP layer is a thin wrapper behind
a guarded import, so this module imports (and the test suite runs) without the
`mcp` package installed.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.decision import build_decisions  # noqa: E402
from core.options import price_option as _bs_price_option  # noqa: E402
from core.screen import _resolve_config, load_config  # noqa: E402

GOVERNANCE = ("Every verdict here is computed by a deterministic engine "
              "(same inputs, same answer); no LLM made or influenced the call. "
              "Not investment advice.")


def _config() -> dict:
    """config.json if present, else the bundled config.example.json."""
    return load_config(_resolve_config(None))


def _known(cfg: dict) -> list[str]:
    return [row["ticker"] for row in cfg.get("skill", {}).get("watchlist", [])]


# ---- tool bodies (plain functions — tested directly, wrapped by FastMCP) ------


def screen_watchlist() -> dict:
    """Screen the whole watchlist: ranked BUY/WATCH/PASS verdicts with the
    three-criterion evidence checklist (Payback Time < 12y, Margin of Safety > 0,
    positive FCF) and the timing verdict per name."""
    cfg = _config()
    decisions = build_decisions(cfg)
    return {
        "count": len(decisions),
        "ranked": [
            {
                "rank": d["rank"],
                "ticker": d["ticker"],
                "name": d["name"],
                "sector": d["sector"],
                "price": d["price"],
                "verdict": d["valuation"]["verdict"],
                "conviction": d["valuation"]["conviction"],
                "criteria": d["valuation"]["criteria"],
                "margin_of_safety": d["valuation"]["margin_of_safety"],
                "payback_years": d["valuation"]["payback_years"],
                "timing_verdict": d["timing"]["verdict"],
            }
            for d in decisions
        ],
        "governance": GOVERNANCE,
    }


def analyze_ticker(ticker: str) -> dict:
    """Full decision for one watchlist name: BUY/WATCH/PASS verdict, conviction,
    the evidence trail (each criterion with value, threshold, pass/fail),
    fair-value numbers, and the timing lens."""
    cfg = _config()
    t = ticker.upper().strip()
    known = _known(cfg)
    if t not in known:
        return {"error": f"unknown ticker {t!r}", "known_tickers": known}
    decisions = build_decisions(cfg)
    d = next(x for x in decisions if x["ticker"] == t)
    return {
        "ticker": d["ticker"],
        "name": d["name"],
        "sector": d["sector"],
        "price": d["price"],
        "rank": d["rank"],
        "universe": len(decisions),
        "valuation": d["valuation"],
        "timing": d["timing"],
        "governance": GOVERNANCE,
    }


def floor_signals(ticker: str) -> dict:
    """The four timing signals for one name (linear-regression channel,
    Stochastic 14,5,3, MACD 8,17,9, price vs SMA50) plus the convergence
    verdict: REACHING FLOOR (3+ met) / NEUTRAL / EXTENDED."""
    cfg = _config()
    t = ticker.upper().strip()
    known = _known(cfg)
    if t not in known:
        return {"error": f"unknown ticker {t!r}", "known_tickers": known}
    d = next(x for x in build_decisions(cfg) if x["ticker"] == t)
    timing = d["timing"]
    return {
        "ticker": t,
        "verdict": timing["verdict"],
        "score": timing["score"],
        "met": timing["met"],
        "total": timing["total"],
        "signals": timing["signals"],
        "governance": GOVERNANCE,
    }


def price_option(ticker: str, strike: float, expiry_years: float = 1.0,
                 vol: float = 0.25, rate: float = 0.04,
                 kind: str = "call") -> dict:
    """Price a European option with textbook Black-Scholes (+ delta). The
    underlying price comes from the config watchlist for the ticker."""
    cfg = _config()
    t = ticker.upper().strip()
    row = next((r for r in cfg["skill"]["watchlist"] if r["ticker"] == t), None)
    if row is None:
        return {"error": f"unknown ticker {t!r}", "known_tickers": _known(cfg)}
    result = _bs_price_option(S=float(row["price"]), K=float(strike),
                              T=float(expiry_years), r=float(rate),
                              sigma=float(vol), kind=kind)
    return {"ticker": t, **result, "governance": GOVERNANCE}


# ---- FastMCP wrapper (guarded — `pip install mcp` to serve) --------------------

try:  # pragma: no cover - exercised only when the SDK is installed
    from mcp.server.fastmcp import FastMCP
except ImportError:  # SDK optional: the repo and tests never require it
    FastMCP = None


def create_server():
    """Build the FastMCP server wrapping the four tool functions."""
    if FastMCP is None:
        raise RuntimeError(
            "The MCP SDK is not installed. Run `pip install mcp` first.")
    server = FastMCP("invest-open")
    server.tool()(screen_watchlist)
    server.tool()(analyze_ticker)
    server.tool()(floor_signals)
    server.tool()(price_option)
    return server


def main() -> int:  # pragma: no cover - stdio server loop
    create_server().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
