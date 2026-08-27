"""Emit the dashboard's JSON contract + a deterministic sample universe.

This turns the deterministic engine's output (core.decision / core.signals /
core.valuation) into the exact JSON the static terminal reads, and ships a
regenerable synthetic sample so the whole thing renders offline with no network
and no live data.

Run it:

    python3 -m core.emit            # writes sample-data/*.json + core/dashboard/data.js

Files written into ``sample-data/``:

  * ``data.json``         — LIST of per-stock objects (watchlist), each with the
                            fundamentals contract + a ``verdict`` block.
  * ``technicals.json``   — ``{generated, signals:{TICKER:{...}}}`` timing fields.
  * ``screen.json``       — ``{generated, criteria, universe, pass, watch}``.
  * ``macro_data.json``   — a small sample macro snapshot.

And ``core/dashboard/data.js`` — ``window.INVEST_DATA = {...}`` so the dashboard
populates every tab when opened as a bare ``file://`` page (where ``fetch()`` of
local JSON is blocked). The dashboard falls back to fetching the JSON files when
served over http.

Everything is deterministic: seeds come from ``zlib.crc32`` (stable across
processes, unlike the builtin ``hash``), and the ``generated`` stamp is a fixed
constant, so two runs are byte-identical. The sample fundamentals are ILLUSTRATIVE
— not real, not current, not investment advice.
"""

from __future__ import annotations

import json
import zlib
from pathlib import Path

import numpy as np

from . import sample_prices as sp
from . import signals as sig
from .decision import (DEFAULT_THRESHOLDS, DecisionThresholds, _number,
                       decide_valuation, decision_thresholds)
from .screen import _defaults, load_config, _resolve_config, valuation_from_row

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = ROOT / "sample-data"
DATA_JS = ROOT / "core" / "dashboard" / "data.js"

# Fixed stamp keeps regeneration byte-identical (determinism tests depend on it).
GENERATED = "sample"

# Timing rails (used by the Signals lens' at_lower_rail / at_upper_rail flags).
# The real thresholds live in core.signals; re-exported here for back-compat.
DIP_MAX = sig.DIP_MAX          # at/under == pressing the lower third (floor read)
CEILING_MIN = sig.CEILING_MIN  # at/over  == pressing the upper third (ceiling read)

# Screen cuts (documented in the dashboard's Screen tab).
# Pass = meets BOTH cuts; Watch = meets exactly one. The Watchlist verdict keeps
# its own PBT < 12y threshold in core.decision — these cuts are Screen-only.
SCREEN_PBT_MAX = 10.0        # Cut A: Payback Time <= this many years
SCREEN_FCF_YIELD_MIN = 0.05  # Cut B: FCF yield >= this (5%)

_INDUSTRY_BY_SECTOR = {
    "Technology": "Consumer Electronics",
    "Semiconductors": "Semiconductors",
    "Consumer Discretionary": "Internet Retail",
    "Communication Services": "Internet Content & Information",
    "Financials": "Banks — Diversified",
    "Energy": "Oil & Gas Integrated",
    "Health Care": "Drug Manufacturers",
    "Consumer Staples": "Discount Stores",
}


def _seed(ticker: str, salt: int = 0) -> int:
    return (zlib.crc32(f"invest-open:{ticker}".encode()) ^ salt) & 0xFFFFFFFF


def _closes(ticker: str, shape: str) -> np.ndarray:
    rng = np.random.default_rng(_seed(ticker))
    fn = sp._SHAPES.get(shape, sp._neutral)
    return fn(rng)


def _ohlc(ticker: str, shape: str):
    closes = _closes(ticker, shape)
    rng = np.random.default_rng(_seed(ticker) ^ 0x9E3779B9)
    return sp._ohlc_from_close(closes, rng)


def _sparkline(closes: np.ndarray, price: float, n: int) -> list[float]:
    """Resample a close path to `n` points and rescale so it ends at `price`."""
    c = np.asarray(closes, dtype=float)
    if c[-1] != 0:
        c = c * (price / c[-1])
    if n >= len(c):
        idx = np.linspace(0, len(c) - 1, n)
    else:
        idx = np.linspace(0, len(c) - 1, n)
    out = np.interp(idx, np.arange(len(c)), c)
    return [round(float(x), 2) for x in out]


def _fundamentals(row: dict) -> dict:
    """Deterministic synthetic fundamentals from a config-style row."""
    ticker = row["ticker"]
    price = float(row["price"])
    eps = float(row["eps"])
    growth = float(row["growth_rate"])
    rng = np.random.default_rng(_seed(ticker, 0xABCD))

    shares = float(rng.uniform(1.0, 16.0)) * 1e9
    market_cap = price * shares
    net_earnings = eps * shares
    net_earnings_yield = net_earnings / market_cap
    operating_earnings = net_earnings * float(rng.uniform(1.1, 1.45))
    if "fcf_yield" in row:
        # The config carries a per-row FCF yield (powers the Screen's Cut B);
        # derive free cash flow from it so the two stay consistent.
        fcf_yield = float(row["fcf_yield"])
        free_cashflow = fcf_yield * market_cap
    else:
        free_cashflow = net_earnings * float(rng.uniform(0.7, 1.2))
        fcf_yield = free_cashflow / market_cap
    total_debt = market_cap * float(rng.uniform(0.05, 0.5))
    equity = market_cap * float(rng.uniform(0.3, 0.8))
    debt_to_equity = total_debt / equity

    eps_growth_rate = min(growth, 0.25)          # tooltip cap: growth capped at 25%
    analyst_eps_growth = min(growth * float(rng.uniform(0.85, 1.1)), 0.25)
    revenue_growth = growth * float(rng.uniform(0.6, 1.0))
    growth_years = int(rng.integers(3, 11))
    growth_label = f"{growth_years}yr EPS CAGR"

    def _cagr(base: float, spread: float) -> float:
        return round(min(max(base * (1.0 + float(rng.uniform(-spread, spread))), -0.1), 0.5), 4)

    cagr_periods = {
        "1yr": _cagr(growth, 0.5),
        "3yr": _cagr(growth, 0.3),
        "5yr": _cagr(growth, 0.2),
        "7yr": _cagr(growth, 0.15),
        "10yr": _cagr(growth, 0.1),
    }

    dividend_yield = round(float(rng.uniform(0.0, 0.03)), 4)
    insider_ownership = round(float(rng.uniform(0.0, 0.09)), 4)
    volatility_6mo = round(float(rng.uniform(0.18, 0.5)), 4)
    volatility_1yr = round(volatility_6mo * float(rng.uniform(0.9, 1.2)), 4)

    day_change_pct = round(float(rng.uniform(-0.03, 0.03)), 4)
    prev_close = round(price / (1.0 + day_change_pct), 2)
    day_change = round(price - prev_close, 2)

    shape = row.get("shape", "neutral")
    closes = _closes(ticker, shape)
    sector = row.get("sector", "")
    industry = row.get("industry") or _INDUSTRY_BY_SECTOR.get(sector, "Diversified")

    return {
        "ticker": ticker,
        "name": row.get("name", ticker),
        "long_name": row.get("name", ticker),
        "sector": sector,
        "industry": industry,
        "website": f"www.example.com/{ticker.lower()}",
        "summary": (f"{row.get('name', ticker)} is used here as an illustrative "
                    "sample issuer so the deterministic engine runs offline. "
                    "Figures are synthetic — not real, not current, not advice."),
        "price": round(price, 2),
        "prev_close": prev_close,
        "day_change": day_change,
        "day_change_pct": day_change_pct,
        "sparkline": _sparkline(closes, price, 30),
        "sparkline_1wk": _sparkline(closes, price, 5),
        "sparkline_1mo": _sparkline(closes, price, 21),
        "sparkline_6mo": _sparkline(closes, price, 126),
        "sparkline_1y": _sparkline(closes, price, 252),
        "sparkline_5y": _sparkline(closes, price, 60),
        "market_cap": round(market_cap, 0),
        "total_debt": round(total_debt, 0),
        "debt_to_equity": round(debt_to_equity, 3),
        "free_cashflow": round(free_cashflow, 0),
        "fcf_yield": round(fcf_yield, 4),
        "operating_earnings": round(operating_earnings, 0),
        "net_earnings": round(net_earnings, 0),
        "net_earnings_yield": round(net_earnings_yield, 4),
        "earnings_yield": round(net_earnings_yield, 4),
        "eps_growth_rate": round(eps_growth_rate, 4),
        "analyst_eps_growth": round(analyst_eps_growth, 4),
        "revenue_growth": round(revenue_growth, 4),
        "growth_years": growth_years,
        "growth_label": growth_label,
        "cagr_periods": cagr_periods,
        "dividend_yield": dividend_yield,
        "insider_ownership": insider_ownership,
        "volatility_6mo": volatility_6mo,
        "volatility_1yr": volatility_1yr,
    }


def _verdict_block(row: dict, defaults: dict,
                   thresholds: DecisionThresholds = DEFAULT_THRESHOLDS) -> dict:
    # valuation_from_row caps the growth the valuation trusts; the fundamentals
    # block above keeps reporting the row's true growth rate.
    val = valuation_from_row(row, defaults)
    fcf_yield = row["fcf_yield"] if _number(row.get("fcf_yield")) else 0.0
    block = decide_valuation(val, fcf_yield, row.get("narrative", ""),
                             thresholds)
    return {
        "verdict": block["verdict"],
        "conviction": block["conviction"],
        "criteria": block["criteria"],
        "narrative": block["narrative"],
        "payback_years": block["payback_years"],
        "sticker_price": block["sticker_price"],
        "buy_price": block["buy_price"],
        "margin_of_safety": block["margin_of_safety"],
    }


def _stock_object(row: dict, defaults: dict,
                  thresholds: DecisionThresholds = DEFAULT_THRESHOLDS) -> dict:
    obj = _fundamentals(row)
    obj["verdict"] = _verdict_block(row, defaults, thresholds)
    return obj


# Confirmation tiers come from the signal engine (strong / setting-up / watching).
_tier = sig.confirmation_tier


def _technicals_for(ticker: str, shape: str) -> dict:
    """Both directions of the timing lens for one name.

    All booleans, tiers, and the overall ``timing`` verdict (REACHING FLOOR /
    NEUTRAL / REACHING CEILING) are computed by ``core.signals.rail_checks`` —
    the floor (buy) read is active near the lower channel rail, the ceiling
    (sell/trim) read near the upper rail.
    """
    highs, lows, closes = _ohlc(ticker, shape)
    rc = sig.rail_checks(closes, highs=highs, lows=lows, channel_period=100)
    ch_long = sig.linreg_channel(closes, period=160)

    return {
        "stoch_k": round(rc["stoch_k"], 1),
        "stoch_d": round(rc["stoch_d"], 1),
        "stoch_pass": rc["stoch_pass"],
        "stoch_sell": rc["stoch_sell"],
        "macd_pass": rc["macd_pass"],
        "macd_sell": rc["macd_sell"],
        "ma_pass": rc["ma_pass"],
        "ma_sell": rc["ma_sell"],
        "at_lower_rail": rc["at_lower_rail"],
        "at_upper_rail": rc["at_upper_rail"],
        "channel_position": round(rc["channel_position"], 4),
        "channel_position_long": round(float(ch_long["position"]), 4),
        "long_window": 160,
        "tier": rc["tier"],
        "ceiling_tier": rc["ceiling_tier"],
        "timing": rc["timing"],
    }


# --- top-level emitters ------------------------------------------------------


def emit_data(cfg: dict) -> list[dict]:
    """Watchlist per-stock objects (data.json contract)."""
    defaults = _defaults(cfg)
    thresholds = decision_thresholds(cfg)
    rows = cfg.get("skill", {}).get("watchlist", [])
    return [_stock_object(r, defaults, thresholds) for r in rows]


def emit_technicals(rows: list[dict]) -> dict:
    """technicals.json — per-ticker timing signal fields for every name shown."""
    signals: dict[str, dict] = {}
    for r in rows:
        signals[r["ticker"]] = _technicals_for(r["ticker"], r.get("shape", "neutral"))
    return {"generated": GENERATED, "signals": signals}


def emit_screen(data: list[dict]) -> dict:
    """screen.json — value screen: pass[] meets both cuts, watch[] exactly one.

    Cut A: Payback Time <= SCREEN_PBT_MAX years.
    Cut B: FCF yield >= SCREEN_FCF_YIELD_MIN.
    """
    passed, watch = [], []
    universe = []
    for obj in data:
        ticker = obj["ticker"]
        universe.append(ticker)
        pbt = obj["verdict"]["payback_years"]
        fcf_yield = obj["fcf_yield"]
        pbt_ok = pbt <= SCREEN_PBT_MAX
        fcf_ok = fcf_yield >= SCREEN_FCF_YIELD_MIN
        entry = {
            "ticker": ticker,
            "name": obj["name"],
            "payback_years": pbt,
            "fcf_yield": fcf_yield,
            "margin_of_safety": obj["verdict"]["margin_of_safety"],
            "pbt_ok": bool(pbt_ok),
            "fcf_ok": bool(fcf_ok),
        }
        if pbt_ok and fcf_ok:
            passed.append(entry)
        elif pbt_ok or fcf_ok:
            watch.append(entry)
    passed.sort(key=lambda e: e["payback_years"])
    watch.sort(key=lambda e: e["payback_years"])
    return {
        "generated": GENERATED,
        "criteria": {"pbt_max": SCREEN_PBT_MAX, "fcf_yield_min": SCREEN_FCF_YIELD_MIN},
        "universe": universe,
        "pass": passed,
        "watch": watch,
    }


def emit_macro() -> dict:
    """A small, clearly-sample macro snapshot for the Macro tab."""
    return {
        "generated": GENERATED,
        "fed_policy": {
            "target_rate": "4.25–4.50%",
            "stance": "Neutral / data-dependent",
            "last_move": "Hold",
            "next_meeting": "sample",
            "note": "Sample values — illustrative only, not a live feed.",
        },
        "inflation": {
            "cpi_yoy": 0.031,
            "core_cpi_yoy": 0.033,
            "pce_yoy": 0.026,
            "trend": "cooling",
        },
        "labor": {
            "unemployment": 0.041,
            "nonfarm_payrolls_k": 165,
            "wage_growth_yoy": 0.039,
            "trend": "steady",
        },
        "market_indicators": [
            {"name": "10Y Treasury", "value": "4.18%", "change": -0.04},
            {"name": "2Y Treasury", "value": "3.92%", "change": -0.02},
            {"name": "VIX", "value": "15.6", "change": -0.8},
            {"name": "US Dollar Index", "value": "103.2", "change": 0.3},
            {"name": "WTI Crude", "value": "$74.10", "change": 1.1},
            {"name": "Gold", "value": "$2,640", "change": 0.6},
        ],
        "news": [
            {"headline": "Sample: Fed holds rates, signals patience on cuts",
             "source": "Sample Wire", "sentiment": "neutral",
             "summary": "Placeholder macro headline demonstrating the Macro tab card layout."},
            {"headline": "Sample: Inflation cools for a third straight month",
             "source": "Sample Wire", "sentiment": "positive",
             "summary": "Placeholder macro headline — cooling CPI supports a soft-landing narrative."},
            {"headline": "Sample: Labor market steady as payrolls come in near estimate",
             "source": "Sample Wire", "sentiment": "neutral",
             "summary": "Placeholder macro headline — jobs report broadly in line with expectations."},
        ],
    }


def build_all(cfg: dict) -> dict:
    data = emit_data(cfg)
    technicals = emit_technicals(cfg.get("skill", {}).get("watchlist", []))
    screen = emit_screen(data)
    macro = emit_macro()
    return {
        "data": data,
        "technicals": technicals,
        "screen": screen,
        "macro": macro,
    }


def write_all(cfg: dict, sample_dir: Path = SAMPLE_DIR,
              data_js: Path = DATA_JS) -> dict:
    """Write every JSON file + the data.js bundle. Returns the assembled dict."""
    bundle = build_all(cfg)
    sample_dir.mkdir(parents=True, exist_ok=True)
    (sample_dir / "data.json").write_text(json.dumps(bundle["data"], indent=2))
    (sample_dir / "technicals.json").write_text(json.dumps(bundle["technicals"], indent=2))
    (sample_dir / "screen.json").write_text(json.dumps(bundle["screen"], indent=2))
    (sample_dir / "macro_data.json").write_text(json.dumps(bundle["macro"], indent=2))

    data_js.parent.mkdir(parents=True, exist_ok=True)
    js = "window.INVEST_DATA = " + json.dumps(bundle, indent=2) + ";\n"
    data_js.write_text(js)
    return bundle


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Emit dashboard JSON + sample data.")
    ap.add_argument("--config", help="Path to config JSON")
    args = ap.parse_args(argv)

    cfg = load_config(_resolve_config(args.config))
    bundle = write_all(cfg)

    buys = sum(1 for d in bundle["data"] if d["verdict"]["verdict"] == "BUY")
    passes = sum(1 for d in bundle["data"] if d["verdict"]["verdict"] == "PASS")
    techs = bundle["technicals"]["signals"].values()
    floors = sum(1 for t in techs if t["timing"] == "REACHING FLOOR")
    ceilings = sum(1 for t in techs if t["timing"] == "REACHING CEILING")
    screen = bundle["screen"]
    print(f"wrote sample-data/*.json + core/dashboard/data.js")
    print(f"  watchlist: {len(bundle['data'])} names · {buys} BUY · {passes} PASS")
    print(f"  screen: {len(screen['pass'])} pass · {len(screen['watch'])} watch")
    print(f"  timing: {floors} reaching floor · {ceilings} reaching ceiling")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
