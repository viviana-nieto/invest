#!/usr/bin/env python3
"""Dump the Python engine's outputs as parity fixtures for the TypeScript port.

Runs the SAME inputs (config.example.json watchlist + deterministic synthetic
price series + a Black-Scholes grid) through the Python engine and serializes
both the inputs and the expected outputs to
``web/engine/__tests__/fixtures.json``. The TS parity test
(``web/engine/__tests__/parity.test.ts``) replays the inputs through the TS
engine and asserts equality — floats within 1e-6, verdicts/tiers/booleans and
formatted strings exactly.

Price series are serialized as plain float lists (JSON round-trips doubles
exactly), so both engines consume bit-identical inputs.

Usage:
    cd web && python3 scripts/dump_engine.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

WEB = Path(__file__).resolve().parents[1]
ROOT = WEB.parent
sys.path.insert(0, str(ROOT))

from scipy.stats import norm  # noqa: E402

from core import emit  # noqa: E402
from core import signals as sig  # noqa: E402
from core.decision import (build_decision, decide_valuation,  # noqa: E402
                           decision_thresholds, stocks_from_config)
from core.options import (black_scholes_call, black_scholes_put,  # noqa: E402
                          delta, price_option)
from core.screen import (_defaults, load_config, screen,  # noqa: E402
                         valuation_from_row)

OUT = WEB / "engine" / "__tests__" / "fixtures.json"


def _flist(a) -> list[float]:
    return [float(x) for x in a]


def main() -> int:
    cfg = load_config(ROOT / "config.example.json")
    d = _defaults(cfg)
    t = decision_thresholds(cfg)
    rows = cfg["skill"]["watchlist"]

    # --- shared inputs: deterministic OHLC series per ticker (crc32-seeded,
    # shaped floor / neutral / extended exactly as core.emit generates them).
    series: dict[str, dict] = {}
    for row in rows:
        highs, lows, closes = emit._ohlc(row["ticker"], row.get("shape", "neutral"))
        series[row["ticker"]] = {
            "shape": row.get("shape", "neutral"),
            "highs": _flist(highs),
            "lows": _flist(lows),
            "closes": _flist(closes),
        }

    # --- valuation + decision expectations per ticker.
    valuations: dict[str, dict] = {}
    for row in rows:
        # The shared adapter caps the growth the valuation trusts (the TS side
        # mirrors this via valuationFromRow + configDefaults).
        v = valuation_from_row(row, d)
        valuations[row["ticker"]] = {
            "raw": {
                "payback_years": v.payback_years,
                "sticker": v.sticker,
                "buy_price": v.buy_price,
                "margin_of_safety": v.margin_of_safety,
            },
            "dict": v.to_dict(),
            "decision": decide_valuation(
                v, row.get("fcf_yield", 0), row.get("narrative", ""), t
            ),
        }

    # --- full ranked decision objects, using the serialized series explicitly
    # (mirrors core.decision.build_decisions' sort + rank stamping).
    decisions = []
    for s in stocks_from_config(cfg):
        ser = series[s.ticker]
        decisions.append(build_decision(s, series=(
            np.array(ser["highs"]), np.array(ser["lows"]), np.array(ser["closes"])),
            thresholds=t))
    decisions.sort(key=lambda dd: (
        -dd["valuation"]["conviction"],
        -dd["valuation"]["margin_of_safety"],
        dd["ticker"],
    ))
    for i, dd in enumerate(decisions, start=1):
        dd["rank"] = i

    # --- signals expectations per ticker (floor lens, both-rails lens, and the
    # emitted technicals block — emit._technicals_for regenerates the identical
    # deterministic series internally).
    signals_expected: dict[str, dict] = {}
    for row in rows:
        ser = series[row["ticker"]]
        c = np.array(ser["closes"])
        h = np.array(ser["highs"])
        l = np.array(ser["lows"])
        signals_expected[row["ticker"]] = {
            "timing_signals": sig.timing_signals(c, highs=h, lows=l),
            "rail_checks": sig.rail_checks(c, highs=h, lows=l, channel_period=100),
            "technicals": emit._technicals_for(row["ticker"], row.get("shape", "neutral")),
        }

    # --- screen expectations (both sorts + the Screen tab's pass/watch cuts).
    minimal = []
    for row in rows:
        minimal.append({
            "ticker": row["ticker"],
            "name": row.get("name", row["ticker"]),
            "fcf_yield": row["fcf_yield"],
            "verdict": emit._verdict_block(row, d, t),
        })
    screen_expected = {
        "by_mos": screen(cfg, sort_by="margin_of_safety"),
        "by_pbt": screen(cfg, sort_by="payback_years"),
        "emit_screen": emit.emit_screen(minimal),
    }

    # --- Black-Scholes grid (calls + puts + deltas + rounded dicts) and a
    # normal-CDF grid straight from scipy.
    options_grid = []
    for S in (60.0, 80.0, 95.0, 100.0, 105.0, 120.0, 150.0):
        for T in (0.0, 0.05, 0.25, 1.0, 2.0):
            for r in (0.0, 0.05):
                for sigma in (0.0, 0.2, 0.45):
                    for kind in ("call", "put"):
                        K = 100.0
                        fn = black_scholes_call if kind == "call" else black_scholes_put
                        options_grid.append({
                            "S": S, "K": K, "T": T, "r": r, "sigma": sigma,
                            "kind": kind,
                            "premium": float(fn(S, K, T, r, sigma)),
                            "delta": float(delta(S, K, T, r, sigma, kind)),
                            "dict": price_option(S, K, T, r, sigma, kind),
                        })
    norm_cdf_grid = [
        {"x": float(x), "cdf": float(norm.cdf(x))} for x in np.linspace(-8.0, 8.0, 81)
    ]

    fixture = {
        "_comment": ("Generated by web/scripts/dump_engine.py — Python engine "
                     "expectations for the TS parity test. Regenerate with "
                     "`python3 scripts/dump_engine.py` from web/. Sample data — "
                     "illustrative only, not investment advice."),
        "config": cfg,
        "series": series,
        "expected": {
            "valuations": valuations,
            "decisions": decisions,
            "signals": signals_expected,
            "screen": screen_expected,
            "options_grid": options_grid,
            "norm_cdf_grid": norm_cdf_grid,
            "bs_reference": {
                "S": 100.0, "K": 100.0, "T": 1.0, "r": 0.05, "sigma": 0.2,
                "call": float(black_scholes_call(100.0, 100.0, 1.0, 0.05, 0.2)),
            },
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(fixture, indent=1, allow_nan=False) + "\n")

    timings = sorted(t["rail_checks"]["timing"] for t in signals_expected.values())
    print(f"wrote {OUT.relative_to(WEB)}")
    print(f"  tickers: {len(rows)} · options grid: {len(options_grid)} points")
    print(f"  rail timings: {timings}")
    print(f"  screen: pass={[e['ticker'] for e in screen_expected['emit_screen']['pass']]} "
          f"watch={[e['ticker'] for e in screen_expected['emit_screen']['watch']]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
