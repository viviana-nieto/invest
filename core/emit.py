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
  * ``exploration.json``  — a wider generic universe, same schema as data.json.
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
from .decision import _fcf_positive, decide_valuation
from .screen import _defaults, load_config, _resolve_config
from .valuation import Valuation

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = ROOT / "sample-data"
DATA_JS = ROOT / "core" / "dashboard" / "data.js"

# Fixed stamp keeps regeneration byte-identical (determinism tests depend on it).
GENERATED = "sample"

# Screen thresholds (documented in the dashboard's Screen tab).
DIP_MAX = 0.34   # channel position at/under this == pressing the lower third
PBT_CUT = 12.0   # Payback Time cut, matches the decision engine

# Extra generic mega-caps for the Exploration tab — a wider universe, same
# schema as the watchlist. NONE are personal-portfolio tickers.
EXPLORATION_UNIVERSE = [
    {"ticker": "META",  "name": "Meta Platforms Inc.", "sector": "Communication Services", "industry": "Internet Content & Information", "price": 500.0, "eps": 18.0, "growth_rate": 0.16, "future_pe": 24.0, "fcf": "positive", "shape": "floor"},
    {"ticker": "TSLA",  "name": "Tesla Inc.",          "sector": "Consumer Discretionary", "industry": "Auto Manufacturers",            "price": 250.0, "eps": 3.5,  "growth_rate": 0.22, "future_pe": 40.0, "fcf": "positive", "shape": "extended"},
    {"ticker": "V",     "name": "Visa Inc.",           "sector": "Financials",             "industry": "Credit Services",              "price": 280.0, "eps": 9.5,  "growth_rate": 0.12, "future_pe": 26.0, "fcf": "positive", "shape": "neutral"},
    {"ticker": "MA",    "name": "Mastercard Inc.",     "sector": "Financials",             "industry": "Credit Services",              "price": 470.0, "eps": 13.0, "growth_rate": 0.13, "future_pe": 30.0, "fcf": "positive", "shape": "extended"},
    {"ticker": "PG",    "name": "Procter & Gamble Co.","sector": "Consumer Staples",       "industry": "Household Products",           "price": 165.0, "eps": 6.4,  "growth_rate": 0.06, "future_pe": 20.0, "fcf": "positive", "shape": "neutral"},
    {"ticker": "KO",    "name": "Coca-Cola Co.",       "sector": "Consumer Staples",       "industry": "Beverages",                    "price": 62.0,  "eps": 2.5,  "growth_rate": 0.06, "future_pe": 22.0, "fcf": "positive", "shape": "neutral"},
    {"ticker": "UNH",   "name": "UnitedHealth Group",  "sector": "Health Care",            "industry": "Healthcare Plans",             "price": 520.0, "eps": 27.0, "growth_rate": 0.13, "future_pe": 18.0, "fcf": "positive", "shape": "floor"},
    {"ticker": "CSCO",  "name": "Cisco Systems Inc.",  "sector": "Technology",             "industry": "Communication Equipment",      "price": 50.0,  "eps": 3.3,  "growth_rate": 0.05, "future_pe": 15.0, "fcf": "positive", "shape": "neutral"},
    {"ticker": "ORCL",  "name": "Oracle Corp.",        "sector": "Technology",             "industry": "Software Infrastructure",      "price": 140.0, "eps": 4.2,  "growth_rate": 0.11, "future_pe": 22.0, "fcf": "positive", "shape": "extended"},
    {"ticker": "DIS",   "name": "Walt Disney Co.",     "sector": "Communication Services", "industry": "Entertainment",                "price": 95.0,  "eps": 4.8,  "growth_rate": 0.10, "future_pe": 18.0, "fcf": "positive", "shape": "floor"},
]

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


def _verdict_block(row: dict, defaults: dict) -> dict:
    val = Valuation(
        ticker=row["ticker"],
        price=float(row["price"]),
        eps=float(row["eps"]),
        growth_rate=float(row["growth_rate"]),
        future_pe=row.get("future_pe", defaults["default_future_pe"]),
        years=defaults["years"],
        required_return=defaults["required_return"],
        margin=defaults["margin"],
    )
    block = decide_valuation(val, _fcf_positive(row.get("fcf", "positive")),
                             row.get("narrative", ""))
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


def _stock_object(row: dict, defaults: dict) -> dict:
    obj = _fundamentals(row)
    obj["verdict"] = _verdict_block(row, defaults)
    return obj


def _tier(confirms: int) -> str:
    if confirms >= 2:
        return "strong"
    if confirms == 1:
        return "setting-up"
    return "watching"


def _technicals_for(ticker: str, shape: str) -> dict:
    highs, lows, closes = _ohlc(ticker, shape)
    st = sig.stochastic(highs, lows, closes)
    mac = sig.macd(closes)
    sma50 = sig.sma(closes, 50)
    ref = float(sma50[-1]) if not np.isnan(sma50[-1]) else float(np.mean(closes))
    price = float(closes[-1])
    ch = sig.linreg_channel(closes, period=100)
    ch_long = sig.linreg_channel(closes, period=160)

    stoch_pass = st["k"] < 20.0
    stoch_sell = st["k"] > 80.0
    macd_pass = mac["hist_change"] > 0.0
    macd_sell = mac["hist_change"] < 0.0
    ma_pass = price < ref
    ma_sell = price > ref

    position = float(ch["position"])
    position_long = float(ch_long["position"])
    at_lower_rail = position <= DIP_MAX
    at_upper_rail = position >= 0.66

    floor_confirms = sum([stoch_pass, macd_pass, ma_pass])
    ceiling_confirms = sum([stoch_sell, macd_sell, ma_sell])

    return {
        "stoch_k": round(float(st["k"]), 1),
        "stoch_d": round(float(st["d"]), 1),
        "stoch_pass": bool(stoch_pass),
        "stoch_sell": bool(stoch_sell),
        "macd_pass": bool(macd_pass),
        "macd_sell": bool(macd_sell),
        "ma_pass": bool(ma_pass),
        "ma_sell": bool(ma_sell),
        "at_lower_rail": bool(at_lower_rail),
        "at_upper_rail": bool(at_upper_rail),
        "channel_position": round(position, 4),
        "channel_position_long": round(position_long, 4),
        "long_window": 160,
        "tier": _tier(floor_confirms),
        "ceiling_tier": _tier(ceiling_confirms),
    }


# --- top-level emitters ------------------------------------------------------


def emit_data(cfg: dict) -> list[dict]:
    """Watchlist per-stock objects (data.json contract)."""
    defaults = _defaults(cfg)
    rows = cfg.get("skill", {}).get("watchlist", [])
    return [_stock_object(r, defaults) for r in rows]


def emit_exploration(cfg: dict) -> list[dict]:
    """A wider generic universe, same schema as data.json."""
    defaults = _defaults(cfg)
    return [_stock_object(r, defaults) for r in EXPLORATION_UNIVERSE]


def emit_technicals(rows: list[dict], universe_rows: list[dict]) -> dict:
    """technicals.json — per-ticker timing signal fields for every name shown."""
    signals: dict[str, dict] = {}
    for r in list(rows) + list(universe_rows):
        signals[r["ticker"]] = _technicals_for(r["ticker"], r.get("shape", "neutral"))
    return {"generated": GENERATED, "signals": signals}


def emit_screen(data: list[dict], technicals: dict) -> dict:
    """screen.json — dip/value screen: pass[] meets both cuts, watch[] exactly one."""
    passed, watch = [], []
    universe = []
    sigs = technicals["signals"]
    for obj in data:
        ticker = obj["ticker"]
        universe.append(ticker)
        pos = sigs.get(ticker, {}).get("channel_position", 1.0)
        pbt = obj["verdict"]["payback_years"]
        dip_ok = pos <= DIP_MAX
        pbt_ok = pbt < PBT_CUT
        entry = {
            "ticker": ticker,
            "name": obj["name"],
            "channel_position": pos,
            "payback_years": pbt,
            "margin_of_safety": obj["verdict"]["margin_of_safety"],
            "dip_ok": bool(dip_ok),
            "pbt_ok": bool(pbt_ok),
        }
        if dip_ok and pbt_ok:
            passed.append(entry)
        elif dip_ok or pbt_ok:
            watch.append(entry)
    passed.sort(key=lambda e: e["channel_position"])
    watch.sort(key=lambda e: e["channel_position"])
    return {
        "generated": GENERATED,
        "criteria": {"dip_max": DIP_MAX, "pbt_cut": PBT_CUT},
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
    exploration = emit_exploration(cfg)
    technicals = emit_technicals(
        cfg.get("skill", {}).get("watchlist", []), EXPLORATION_UNIVERSE
    )
    screen = emit_screen(data + exploration, technicals)
    macro = emit_macro()
    return {
        "data": data,
        "exploration": exploration,
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
    (sample_dir / "exploration.json").write_text(json.dumps(bundle["exploration"], indent=2))
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
    floors = sum(1 for t in bundle["technicals"]["signals"].values()
                 if t["tier"] == "strong")
    print(f"wrote sample-data/*.json + core/dashboard/data.js")
    print(f"  watchlist: {len(bundle['data'])} names · {buys} BUY · {passes} PASS")
    print(f"  exploration: {len(bundle['exploration'])} names")
    print(f"  strong-floor (2+/3 confirms): {floors}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
