/**
 * Payback Time (PBT) valuation — a deterministic value-investing engine.
 * TypeScript port of core/valuation.py (same formulas, same defaults:
 * required_return 0.15, margin_of_safety 0.50, projection_years 10).
 *
 * 1. Payback Time — how many years of cumulative, growing earnings it takes to
 *    repay the price you pay today. Lower is better.
 * 2. Sticker price (fair value) — project EPS out N years, apply a future P/E,
 *    then discount back to today at a required rate of return. Buy only with a
 *    margin of safety below that number.
 *
 * No LLM, no network — just arithmetic. The numbers make the call.
 */

import { pyRound } from "./pyformat.ts";

/**
 * Years for cumulative growing earnings to repay `price`.
 *
 * Each future year contributes eps*(1+g)^year (year starts at 1). We sum until
 * the running total reaches `price`, then linearly interpolate within the final
 * year so the result is a smooth float. Returns `maxYears` as a sentinel when
 * earnings never repay the price.
 */
export function paybackTime(
  price: number, eps: number, growthRate: number, maxYears: number = 100,
): number {
  if (price <= 0) throw new Error("price must be positive");
  if (eps <= 0) throw new Error("payback time is undefined for non-positive earnings");

  let cumulative = 0.0;
  for (let year = 1; year <= maxYears; year++) {
    const yearEarnings = eps * (1.0 + growthRate) ** year;
    const prevCumulative = cumulative;
    cumulative += yearEarnings;
    if (cumulative >= price) {
      // Linear interpolation within this year for a smooth fractional result.
      const remaining = price - prevCumulative;
      const fraction = remaining / yearEarnings;
      return (year - 1) + fraction;
    }
  }
  return maxYears;
}

/** Project EPS `years` into the future at a constant growth rate. */
export function futureEps(eps: number, growthRate: number, years: number): number {
  return eps * (1.0 + growthRate) ** years;
}

/**
 * Fair value ("sticker price") of a share today (standard Rule #1 method):
 *     future_price = future_eps(eps, g, years) * future_pe
 *     sticker      = future_price / (1 + required_return)^years
 */
export function stickerPrice(
  eps: number, growthRate: number, futurePe: number,
  years: number = 10, requiredReturn: number = 0.15,
): number {
  const futPrice = futureEps(eps, growthRate, years) * futurePe;
  return futPrice / (1.0 + requiredReturn) ** years;
}

/** Buy price = sticker price discounted by a margin of safety (default 50%). */
export function marginOfSafetyPrice(sticker: number, margin: number = 0.50): number {
  return sticker * (1.0 - margin);
}

/**
 * How far below fair value the current price sits, as a decimal.
 *     MoS = (sticker - price) / sticker
 */
export function marginOfSafety(price: number, sticker: number): number {
  if (sticker <= 0) throw new Error("sticker price must be positive");
  return (sticker - price) / sticker;
}

export interface ValuationDict {
  ticker: string;
  price: number;
  eps: number;
  growth_rate: number;
  future_pe: number;
  payback_years: number;
  sticker_price: number;
  buy_price: number;
  margin_of_safety: number;
  verdict: string;
}

/** A full deterministic valuation for one ticker (port of the Python dataclass). */
export class Valuation {
  ticker: string;
  price: number;
  eps: number;
  growthRate: number;
  futurePe: number;
  years: number;
  requiredReturn: number;
  margin: number;

  constructor(args: {
    ticker: string; price: number; eps: number; growthRate: number;
    futurePe: number; years: number; requiredReturn: number; margin: number;
  }) {
    this.ticker = args.ticker;
    this.price = args.price;
    this.eps = args.eps;
    this.growthRate = args.growthRate;
    this.futurePe = args.futurePe;
    this.years = args.years;
    this.requiredReturn = args.requiredReturn;
    this.margin = args.margin;
  }

  get paybackYears(): number {
    return paybackTime(this.price, this.eps, this.growthRate);
  }

  get sticker(): number {
    return stickerPrice(this.eps, this.growthRate, this.futurePe,
      this.years, this.requiredReturn);
  }

  get buyPrice(): number {
    return marginOfSafetyPrice(this.sticker, this.margin);
  }

  get marginOfSafety(): number {
    return marginOfSafety(this.price, this.sticker);
  }

  /** A deterministic call: the math decides, not an LLM. */
  get verdict(): "BUY" | "WATCH" | "OVERVALUED" {
    if (this.price <= this.buyPrice) return "BUY";
    if (this.marginOfSafety > 0) return "WATCH";
    return "OVERVALUED";
  }

  toDict(): ValuationDict {
    return {
      ticker: this.ticker,
      price: pyRound(this.price, 2),
      eps: pyRound(this.eps, 2),
      growth_rate: this.growthRate,
      future_pe: this.futurePe,
      payback_years: pyRound(this.paybackYears, 2),
      sticker_price: pyRound(this.sticker, 2),
      buy_price: pyRound(this.buyPrice, 2),
      margin_of_safety: pyRound(this.marginOfSafety, 4),
      verdict: this.verdict,
    };
  }
}
