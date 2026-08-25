/**
 * Screen a watchlist deterministically — TypeScript port of core/screen.py plus
 * the Screen-tab cuts from core/emit.py.
 *
 * Two lenses:
 *   - `screenWatchlist` ranks every name by margin of safety (or payback time).
 *   - `emitScreen` applies the Screen tab's two cuts — Payback Time <= 10y AND
 *     FCF yield >= 5% — pass[] meets both, watch[] exactly one.
 *
 * The ranking is pure math — the same inputs always produce the same ordering.
 */

import { configDefaults, valuationFromRow } from "./decision.ts";
import type { Config, ConfigRow, ValuationDecision } from "./decision.ts";
import type { Valuation, ValuationDict } from "./valuation.ts";

/** Build a Valuation for every ticker in the config's watchlist. */
export function valuationsFromConfig(cfg: Config): Valuation[] {
  const d = configDefaults(cfg);
  return (cfg.skill?.watchlist ?? []).map((row: ConfigRow) => valuationFromRow(row, d));
}

export type ScreenSort = "margin_of_safety" | "payback_years";

/**
 * Rank the watchlist (port of core.screen.screen).
 *
 * sortBy: "margin_of_safety" (default, descending — biggest discount first) or
 * "payback_years" (ascending — shortest payback first).
 */
export function screenWatchlist(
  cfg: Config, sortBy: ScreenSort = "margin_of_safety",
): ValuationDict[] {
  const vals = valuationsFromConfig(cfg);

  if (sortBy === "payback_years") {
    vals.sort((a, b) => a.paybackYears - b.paybackYears);
  } else if (sortBy === "margin_of_safety") {
    vals.sort((a, b) => b.marginOfSafety - a.marginOfSafety);
  } else {
    throw new Error("sortBy must be 'margin_of_safety' or 'payback_years'");
  }

  return vals.map((v) => v.toDict());
}

// ---- the Screen tab's pass/watch cuts (port of core.emit.emit_screen) -------

export const SCREEN_PBT_MAX = 10.0;        // Cut A: Payback Time <= this many years
export const SCREEN_FCF_YIELD_MIN = 0.05;  // Cut B: FCF yield >= this (5%)

/** The per-stock inputs the screen needs (a slice of the data.json contract). */
export interface ScreenInput {
  ticker: string;
  name: string;
  fcf_yield: number;
  verdict: Pick<ValuationDecision, "payback_years" | "margin_of_safety">;
}

export interface ScreenEntry {
  ticker: string;
  name: string;
  payback_years: number;
  fcf_yield: number;
  margin_of_safety: number;
  pbt_ok: boolean;
  fcf_ok: boolean;
}

export interface ScreenResult {
  generated: string;
  criteria: { pbt_max: number; fcf_yield_min: number };
  universe: string[];
  pass: ScreenEntry[];
  watch: ScreenEntry[];
}

/**
 * The value screen: pass[] meets both cuts, watch[] exactly one; each side
 * sorted by payback ascending.
 */
export function emitScreen(data: readonly ScreenInput[], generated: string = "sample"): ScreenResult {
  const passed: ScreenEntry[] = [];
  const watch: ScreenEntry[] = [];
  const universe: string[] = [];
  for (const obj of data) {
    universe.push(obj.ticker);
    const pbt = obj.verdict.payback_years;
    const fcfYield = obj.fcf_yield;
    const pbtOk = pbt <= SCREEN_PBT_MAX;
    const fcfOk = fcfYield >= SCREEN_FCF_YIELD_MIN;
    const entry: ScreenEntry = {
      ticker: obj.ticker,
      name: obj.name,
      payback_years: pbt,
      fcf_yield: fcfYield,
      margin_of_safety: obj.verdict.margin_of_safety,
      pbt_ok: pbtOk,
      fcf_ok: fcfOk,
    };
    if (pbtOk && fcfOk) {
      passed.push(entry);
    } else if (pbtOk || fcfOk) {
      watch.push(entry);
    }
  }
  passed.sort((a, b) => a.payback_years - b.payback_years);
  watch.sort((a, b) => a.payback_years - b.payback_years);
  return {
    generated,
    criteria: { pbt_max: SCREEN_PBT_MAX, fcf_yield_min: SCREEN_FCF_YIELD_MIN },
    universe,
    pass: passed,
    watch,
  };
}
