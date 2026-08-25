/**
 * Decision engine — turn a deterministic valuation into a BUY/WATCH/PASS call
 * with an evidence trail. TypeScript port of core/decision.py.
 *
 * The thesis this module makes concrete: **the math makes the call.** A verdict
 * is a pure function of three pass/fail criteria; the LLM never votes.
 *
 * Criteria (all deterministic):
 *   1. Payback Time    < 12 years   (a short payback == a cheap business)
 *   2. Margin of Safety > 0         (price sits below the fair-value sticker)
 *   3. Free Cash Flow   positive    (the business actually generates cash)
 *
 * Verdict: BUY = all 3 pass · WATCH = exactly 2 · PASS = 1 or 0.
 * Conviction (0-100) is a smooth, monotonic function of the margin of safety.
 */

import { pyFixed, pyRound } from "./pyformat.ts";
import { Valuation } from "./valuation.ts";

export const PAYBACK_MAX_YEARS = 12.0;

export type Verdict = "BUY" | "WATCH" | "PASS";

/**
 * Normalise a config `fcf` field to a boolean. Accepts 'positive'/'negative'
 * strings, booleans, or a raw number.
 */
export function fcfPositive(fcf: unknown): boolean {
  if (typeof fcf === "boolean") return fcf;
  if (typeof fcf === "number") return fcf > 0;
  if (typeof fcf === "string") {
    return ["positive", "pos", "+", "true", "yes"].includes(fcf.trim().toLowerCase());
  }
  return false;
}

/**
 * Map margin of safety to a 0-100 conviction score: a logistic curve centred
 * at mos=0 (conviction 50). Monotonic, so ranking by conviction == ranking by
 * discount.
 */
export function convictionFromMos(mos: number): number {
  return pyRound(100.0 / (1.0 + Math.exp(-mos)), 0);
}

export interface Criterion {
  name: string;
  value: string;
  threshold: string;
  passed: boolean;
}

/**
 * The three-item evidence checklist for a valuation, each with value,
 * threshold, and a deterministic pass/fail.
 */
export function valuationCriteria(v: Valuation, fcfPos: boolean): Criterion[] {
  const pbt = v.paybackYears;
  const mos = v.marginOfSafety;
  return [
    {
      name: "Payback Time",
      value: `${pyFixed(pbt, 1)}y`,
      threshold: `< ${pyFixed(PAYBACK_MAX_YEARS, 0)}y`,
      passed: pbt < PAYBACK_MAX_YEARS,
    },
    {
      name: "Margin of Safety",
      value: `${pyFixed(mos * 100, 0, true)}%`,
      threshold: "> 0",
      passed: mos > 0.0,
    },
    {
      name: "Free Cash Flow",
      value: fcfPos ? "positive" : "negative",
      threshold: "positive",
      passed: fcfPos,
    },
  ];
}

/** 3 pass -> BUY, exactly 2 -> WATCH, <=1 -> PASS. Deterministic. */
export function verdictFromCriteria(criteria: readonly Criterion[]): Verdict {
  const passed = criteria.reduce((acc, c) => acc + (c.passed ? 1 : 0), 0);
  if (passed === 3) return "BUY";
  if (passed === 2) return "WATCH";
  return "PASS";
}

export interface ValuationDecision {
  verdict: Verdict;
  conviction: number;
  criteria: Criterion[];
  narrative: string;
  payback_years: number;
  sticker_price: number;
  buy_price: number;
  margin_of_safety: number;
}

/** Build the `valuation` decision block for one stock. */
export function decideValuation(
  v: Valuation, fcfPos: boolean, narrative: string = "",
): ValuationDecision {
  const criteria = valuationCriteria(v, fcfPos);
  return {
    verdict: verdictFromCriteria(criteria),
    conviction: convictionFromMos(v.marginOfSafety),
    criteria,
    narrative,
    // A few raw numbers the dashboard likes to show alongside the checklist.
    payback_years: pyRound(v.paybackYears, 2),
    sticker_price: pyRound(v.sticker, 2),
    buy_price: pyRound(v.buyPrice, 2),
    margin_of_safety: pyRound(v.marginOfSafety, 4),
  };
}

// ---- watchlist parsing ------------------------------------------------------

/** One config watchlist row (config.example.json / config.json shape). */
export interface ConfigRow {
  ticker: string;
  name?: string;
  sector?: string;
  price: number;
  eps: number;
  growth_rate: number;
  future_pe?: number;
  fcf?: unknown;
  fcf_yield?: number;
  shape?: string;
  narrative?: string;
  [key: string]: unknown;
}

export interface Config {
  skill?: {
    projection_years?: number;
    required_return?: number;
    margin_of_safety?: number;
    default_future_pe?: number;
    watchlist?: ConfigRow[];
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

/** One watchlist row's static facts (everything except computed verdicts). */
export interface Stock {
  ticker: string;
  name: string;
  sector: string;
  price: number;
  valuation: Valuation;
  fcfPositive: boolean;
  narrative: string;
  /** timing sample-series shape: floor | neutral | extended */
  shape: string;
}

export interface ValuationDefaults {
  years: number;
  requiredReturn: number;
  margin: number;
  defaultFuturePe: number;
}

/** Pull global valuation assumptions from the config's skill block. */
export function configDefaults(cfg: Config): ValuationDefaults {
  const skill = cfg.skill ?? {};
  return {
    years: skill.projection_years ?? 10,
    requiredReturn: skill.required_return ?? 0.15,
    margin: skill.margin_of_safety ?? 0.50,
    defaultFuturePe: skill.default_future_pe ?? 15.0,
  };
}

/** Build a Valuation for one config row using the global defaults. */
export function valuationFromRow(row: ConfigRow, d: ValuationDefaults): Valuation {
  return new Valuation({
    ticker: row.ticker,
    price: row.price,
    eps: row.eps,
    growthRate: row.growth_rate,
    futurePe: row.future_pe ?? d.defaultFuturePe,
    years: d.years,
    requiredReturn: d.requiredReturn,
    margin: d.margin,
  });
}

/** Parse the config watchlist into Stock objects. */
export function stocksFromConfig(cfg: Config): Stock[] {
  const d = configDefaults(cfg);
  const rows = cfg.skill?.watchlist ?? [];
  return rows.map((row) => ({
    ticker: row.ticker,
    name: row.name ?? row.ticker,
    sector: row.sector ?? "",
    price: row.price,
    valuation: valuationFromRow(row, d),
    fcfPositive: fcfPositive(row.fcf ?? "positive"),
    narrative: row.narrative ?? "",
    shape: row.shape ?? "neutral",
  }));
}
