/**
 * Parity gate: the TypeScript engine must produce the SAME results as the
 * Python engine for the same inputs.
 *
 * `web/scripts/dump_engine.py` runs config.example.json (all 9 tickers), the
 * deterministic shaped price series (floor / neutral / extended), and a
 * Black-Scholes input grid through the Python engine and writes both the
 * inputs and the expected outputs to fixtures.json. This test replays the
 * identical inputs through the TS engine and asserts:
 *
 *   - floats equal within FLOAT_TOL (1e-6; observed diffs are ~1e-12),
 *   - verdicts / tiers / booleans / formatted strings exactly equal,
 *   - object shapes (keys) exactly equal.
 *
 * Run:  cd web && npm run fixtures && npm test
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import type { Config, Series } from "../index.ts";
import {
  Valuation,
  blackScholesCall,
  blackScholesPut,
  buildDecisions,
  configDefaults,
  decideValuation,
  decisionThresholds,
  delta,
  emitScreen,
  normCdf,
  priceOption,
  railChecks,
  screenWatchlist,
  technicalsFor,
  timingSignals,
  valuationFromRow,
} from "../index.ts";

const FLOAT_TOL = 1e-6;

const fixtures = JSON.parse(
  readFileSync(new URL("./fixtures.json", import.meta.url), "utf8"),
);
const cfg: Config = fixtures.config;
const rows = cfg.skill!.watchlist!;
const series: Record<string, Series & { shape: string }> = fixtures.series;
const expected = fixtures.expected;

/** Track the largest float deviation seen, for the parity report. */
let maxFloatDiff = 0;

/**
 * Deep parity assert: numbers within tol, everything else (strings, booleans,
 * null, key sets, array lengths/order) exactly equal.
 */
function assertParity(actual: unknown, exp: unknown, path: string, tol = FLOAT_TOL): void {
  if (typeof exp === "number") {
    assert.equal(typeof actual, "number", `${path}: expected a number`);
    const diff = Math.abs((actual as number) - exp);
    if (Number.isFinite(diff)) maxFloatDiff = Math.max(maxFloatDiff, diff);
    assert.ok(diff <= tol, `${path}: ${actual} !== ${exp} (diff ${diff})`);
  } else if (exp === null || typeof exp === "string" || typeof exp === "boolean") {
    assert.strictEqual(actual, exp, `${path}: ${JSON.stringify(actual)} !== ${JSON.stringify(exp)}`);
  } else if (Array.isArray(exp)) {
    assert.ok(Array.isArray(actual), `${path}: expected an array`);
    assert.strictEqual((actual as unknown[]).length, exp.length, `${path}: length mismatch`);
    exp.forEach((e, i) => assertParity((actual as unknown[])[i], e, `${path}[${i}]`, tol));
  } else if (typeof exp === "object") {
    assert.ok(actual !== null && typeof actual === "object", `${path}: expected an object`);
    const expKeys = Object.keys(exp as object).sort();
    const actKeys = Object.keys(actual as object).sort();
    assert.deepStrictEqual(actKeys, expKeys, `${path}: key mismatch`);
    for (const k of expKeys) {
      assertParity(
        (actual as Record<string, unknown>)[k],
        (exp as Record<string, unknown>)[k],
        `${path}.${k}`,
        tol,
      );
    }
  } else {
    assert.fail(`${path}: unsupported fixture type ${typeof exp}`);
  }
}

function tsValuation(ticker: string): Valuation {
  const row = rows.find((r) => r.ticker === ticker)!;
  return valuationFromRow(row, configDefaults(cfg));
}

// ---- valuation --------------------------------------------------------------

test("valuation parity: payback, sticker, buy price, margin of safety (9 tickers)", () => {
  for (const row of rows) {
    const v = tsValuation(row.ticker);
    const exp = expected.valuations[row.ticker];
    assertParity(
      {
        payback_years: v.paybackYears,
        sticker: v.sticker,
        buy_price: v.buyPrice,
        margin_of_safety: v.marginOfSafety,
      },
      exp.raw,
      `${row.ticker}.raw`,
    );
    assertParity(v.toDict(), exp.dict, `${row.ticker}.dict`);
  }
});

test("decision parity: BUY/WATCH/PASS verdict, conviction, evidence criteria", () => {
  for (const row of rows) {
    const v = tsValuation(row.ticker);
    const block = decideValuation(
      v, (row.fcf_yield as number) ?? 0, row.narrative ?? "", decisionThresholds(cfg),
    );
    assertParity(block, expected.valuations[row.ticker].decision, `${row.ticker}.decision`);
  }
});

// ---- options ----------------------------------------------------------------

test("options parity: Black-Scholes call/put + delta grid", () => {
  assert.ok(expected.options_grid.length >= 400, "grid should be substantial");
  for (const g of expected.options_grid) {
    const fn = g.kind === "call" ? blackScholesCall : blackScholesPut;
    const label = `BS(${g.kind} S=${g.S} T=${g.T} r=${g.r} sigma=${g.sigma})`;
    assertParity(fn(g.S, g.K, g.T, g.r, g.sigma), g.premium, `${label}.premium`);
    assertParity(delta(g.S, g.K, g.T, g.r, g.sigma, g.kind), g.delta, `${label}.delta`);
    assertParity(priceOption(g.S, g.K, g.T, g.r, g.sigma, g.kind), g.dict, `${label}.dict`);
  }
});

test("options reference: S=K=100, T=1, r=.05, sigma=.2 -> call ~= 10.4506", () => {
  const ref = expected.bs_reference;
  const call = blackScholesCall(ref.S, ref.K, ref.T, ref.r, ref.sigma);
  assert.ok(Math.abs(call - 10.4506) < 1e-4, `call ${call} != 10.4506`);
  assertParity(call, ref.call, "bs_reference.call");
});

test("normal CDF parity vs scipy (Cephes ndtr), x in [-8, 8]", () => {
  for (const p of expected.norm_cdf_grid) {
    assertParity(normCdf(p.x), p.cdf, `normCdf(${p.x})`, 1e-12);
  }
});

// ---- signals ----------------------------------------------------------------

const SHAPE_TIMING: Record<string, string> = {
  floor: "REACHING FLOOR",
  neutral: "NEUTRAL",
  extended: "REACHING CEILING",
};

test("signals parity: timing_signals + rail_checks + technicals per ticker", () => {
  for (const row of rows) {
    const s = series[row.ticker];
    const exp = expected.signals[row.ticker];
    assertParity(
      timingSignals(s.closes, s.highs, s.lows),
      exp.timing_signals,
      `${row.ticker}.timing_signals`,
    );
    assertParity(
      railChecks(s.closes, s.highs, s.lows, 100),
      exp.rail_checks,
      `${row.ticker}.rail_checks`,
    );
    assertParity(technicalsFor(s), exp.technicals, `${row.ticker}.technicals`);
  }
});

test("signals: shaped series land on the intended floor/neutral/ceiling verdicts", () => {
  for (const row of rows) {
    const s = series[row.ticker];
    const rc = railChecks(s.closes, s.highs, s.lows, 100);
    assert.strictEqual(
      rc.timing,
      SHAPE_TIMING[s.shape],
      `${row.ticker} (${s.shape}) rail timing`,
    );
  }
  const shapes = new Set(rows.map((r) => series[r.ticker].shape));
  assert.deepStrictEqual([...shapes].sort(), ["extended", "floor", "neutral"]);
});

// ---- full decision objects --------------------------------------------------

test("decision-object parity: full ranked watchlist (valuation + timing + rank)", () => {
  const ts = buildDecisions(cfg, series);
  assertParity(ts, expected.decisions, "decisions");
});

// ---- screen -----------------------------------------------------------------

test("screen parity: margin-of-safety and payback rankings", () => {
  assertParity(screenWatchlist(cfg, "margin_of_safety"), expected.screen.by_mos, "screen.by_mos");
  assertParity(screenWatchlist(cfg, "payback_years"), expected.screen.by_pbt, "screen.by_pbt");
});

test("screen parity: pass/watch cuts (PBT <= 10y AND FCF yield >= 5%)", () => {
  const d = configDefaults(cfg);
  const minimal = rows.map((row) => ({
    ticker: row.ticker,
    name: row.name ?? row.ticker,
    fcf_yield: row.fcf_yield as number,
    verdict: decideValuation(
      valuationFromRow(row, d),
      (row.fcf_yield as number) ?? 0,
      row.narrative ?? "",
      decisionThresholds(cfg),
    ),
  }));
  const result = emitScreen(minimal);
  assertParity(result, expected.screen.emit_screen, "screen.emit_screen");
  assert.deepStrictEqual(
    result.pass.map((e) => e.ticker).sort(),
    ["CI", "JPM", "NKE"],
    "sample pass set",
  );
});

test("parity report", () => {
  assert.ok(maxFloatDiff <= FLOAT_TOL);
  console.log(`  max float deviation TS vs Python: ${maxFloatDiff.toExponential(3)} (tolerance ${FLOAT_TOL})`);
});
