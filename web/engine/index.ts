/**
 * invest-open TypeScript engine — barrel + per-ticker assembly.
 *
 * Framework-agnostic port of the deterministic Python engine (core/valuation.py,
 * core/options.py, core/signals.py, core/decision.py, core/screen.py +
 * core/emit.py's assembly). No React, no DOM — plain functions the future UI
 * consumes directly.
 *
 * `buildDecision` produces the same per-ticker decision object shape as
 * core.decision.build_decision, and `technicalsFor` the same per-ticker block
 * as core.emit._technicals_for — so the output is drop-in compatible with the
 * JSON contract the existing dashboard reads. The only difference from the
 * Python sample pipeline: the price series is an explicit input (the web app
 * supplies real or sample candles) instead of being synthesized internally.
 */

export * from "./pyformat.ts";
export * from "./valuation.ts";
export * from "./options.ts";
export * from "./signals.ts";
export * from "./decision.ts";
export * from "./screen.ts";

import { decideValuation, stocksFromConfig } from "./decision.ts";
import type { Config, Stock, ValuationDecision } from "./decision.ts";
import { pyRound } from "./pyformat.ts";
import { linregChannel, railChecks, timingSignals } from "./signals.ts";
import type { RailTiming, Tier, TimingSignals } from "./signals.ts";

/** One OHLC price series, oldest -> newest. */
export interface Series {
  highs: readonly number[];
  lows: readonly number[];
  closes: readonly number[];
}

/** The full per-ticker decision object (both lenses) the dashboard renders. */
export interface DecisionObject {
  ticker: string;
  name: string;
  sector: string;
  price: number;
  valuation: ValuationDecision;
  timing: TimingSignals;
  rank?: number;
}

/**
 * Assemble the full per-stock decision object (port of
 * core.decision.build_decision with an explicit price series).
 */
export function buildDecision(stock: Stock, series: Series): DecisionObject {
  const valuation = decideValuation(stock.valuation, stock.fcfPositive, stock.narrative);
  const timing = timingSignals(series.closes, series.highs, series.lows);
  return {
    ticker: stock.ticker,
    name: stock.name,
    sector: stock.sector,
    price: pyRound(stock.price, 2),
    valuation,
    timing,
  };
}

/**
 * Full decision objects for the whole watchlist, ranked by conviction desc
 * (port of core.decision.build_decisions; the caller supplies one price series
 * per ticker). Tie-break: margin of safety desc, then ticker asc — a total,
 * deterministic order.
 */
export function buildDecisions(
  cfg: Config, seriesByTicker: Readonly<Record<string, Series>>,
): DecisionObject[] {
  const stocks = stocksFromConfig(cfg);
  const decisions = stocks.map((s) => {
    const series = seriesByTicker[s.ticker];
    if (!series) throw new Error(`no price series for ${s.ticker}`);
    return buildDecision(s, series);
  });
  decisions.sort((a, b) =>
    b.valuation.conviction - a.valuation.conviction
    || b.valuation.margin_of_safety - a.valuation.margin_of_safety
    || (a.ticker < b.ticker ? -1 : a.ticker > b.ticker ? 1 : 0));
  decisions.forEach((d, i) => { d.rank = i + 1; });
  return decisions;
}

/** The technicals.json per-ticker block (port of core.emit._technicals_for). */
export interface TechnicalsBlock {
  stoch_k: number;
  stoch_d: number;
  stoch_pass: boolean;
  stoch_sell: boolean;
  macd_pass: boolean;
  macd_sell: boolean;
  ma_pass: boolean;
  ma_sell: boolean;
  at_lower_rail: boolean;
  at_upper_rail: boolean;
  channel_position: number;
  channel_position_long: number;
  long_window: number;
  tier: Tier;
  ceiling_tier: Tier;
  timing: RailTiming;
}

/**
 * Both directions of the timing lens for one name — the exact per-ticker block
 * core/emit.py writes into technicals.json.
 */
export function technicalsFor(series: Series, longWindow: number = 160): TechnicalsBlock {
  const rc = railChecks(series.closes, series.highs, series.lows, 100);
  const chLong = linregChannel(series.closes, longWindow);
  return {
    stoch_k: pyRound(rc.stoch_k, 1),
    stoch_d: pyRound(rc.stoch_d, 1),
    stoch_pass: rc.stoch_pass,
    stoch_sell: rc.stoch_sell,
    macd_pass: rc.macd_pass,
    macd_sell: rc.macd_sell,
    ma_pass: rc.ma_pass,
    ma_sell: rc.ma_sell,
    at_lower_rail: rc.at_lower_rail,
    at_upper_rail: rc.at_upper_rail,
    channel_position: pyRound(rc.channel_position, 4),
    channel_position_long: pyRound(chLong.position, 4),
    long_window: longWindow,
    tier: rc.tier,
    ceiling_tier: rc.ceiling_tier,
    timing: rc.timing,
  };
}
