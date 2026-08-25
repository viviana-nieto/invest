/**
 * Floor/ceiling timing engine — TypeScript port of core/signals.py.
 *
 * Four independent technical signals computed from a price series — no TA
 * library, no network. Each answers a yes/no question about whether a name is
 * pressing against a floor. Their convergence is the call; the LLM never decides.
 *
 *   1. Linear-regression channel  — is price at/below the lower rail?
 *   2. Stochastic(14,5,3)         — is the slow %K oversold (< 20)?
 *   3. MACD(8,17,9)               — is the histogram turning up?
 *   4. SMA position (vs 50-day)   — is price below its longer-term average?
 *
 * Convergence verdict (`timingSignals`, the floor-only lens):
 *   REACHING FLOOR  >= 3 of 4 met · NEUTRAL 1-2 met · EXTENDED 0 met
 *
 * `railChecks` runs both sides at once — floor (buy) confirmations near the
 * lower channel rail, ceiling (sell/trim) confirmations near the upper rail —
 * and folds them into one overall timing verdict:
 * REACHING FLOOR / NEUTRAL / REACHING CEILING.
 *
 * All functions take plain number arrays (oldest -> newest).
 */

import { pyFixed } from "./pyformat.ts";

// ---- indicator primitives ---------------------------------------------------

/**
 * Simple moving average; result aligned to the input (leading NaNs).
 * NaN-safe: a window containing any NaN yields NaN at that position without
 * poisoning later windows.
 */
export function sma(values: readonly number[], period: number): number[] {
  const out: number[] = new Array(values.length).fill(NaN);
  if (period <= 0 || values.length < period) return out;
  for (let i = period - 1; i < values.length; i++) {
    let sum = 0;
    let hasNaN = false;
    for (let j = i - period + 1; j <= i; j++) {
      const v = values[j];
      if (Number.isNaN(v)) { hasNaN = true; break; }
      sum += v;
    }
    if (!hasNaN) out[i] = sum / period;
  }
  return out;
}

/**
 * Exponential moving average, seeded with the first value (leading values are
 * the running EMA, not NaN — standard for MACD chains).
 */
export function ema(values: readonly number[], period: number): number[] {
  const out: number[] = new Array(values.length).fill(NaN);
  if (values.length === 0) return out;
  const alpha = 2.0 / (period + 1.0);
  out[0] = values[0];
  for (let i = 1; i < values.length; i++) {
    out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1];
  }
  return out;
}

export interface Channel {
  slope: number;
  mid: number;
  upper: number;
  lower: number;
  price: number;
  /** 0 == lower rail, 1 == upper rail. */
  position: number;
}

/**
 * Least-squares regression channel over the last `period` bars.
 * Fits close ~ a*t + b, then draws rails at the regression line +/- numStd *
 * (population std of residuals).
 */
export function linregChannel(
  closes: readonly number[], period: number = 100, numStd: number = 2.0,
): Channel {
  const n = Math.min(period, closes.length);
  const window = closes.slice(closes.length - n);
  // Closed-form OLS for degree-1 fit over t = 0..n-1 (matches np.polyfit(.., 1)).
  const tMean = (n - 1) / 2;
  let wMean = 0;
  for (let i = 0; i < n; i++) wMean += window[i];
  wMean /= n;
  let sxx = 0;
  let sxy = 0;
  for (let i = 0; i < n; i++) {
    const dt = i - tMean;
    sxx += dt * dt;
    sxy += dt * (window[i] - wMean);
  }
  const a = sxy / sxx;
  const b = wMean - a * tMean;

  // Population std of residuals (np.std: deviations from the residual mean).
  const resid: number[] = new Array(n);
  let residMean = 0;
  for (let i = 0; i < n; i++) {
    resid[i] = window[i] - (a * i + b);
    residMean += resid[i];
  }
  residMean /= n;
  let ss = 0;
  for (let i = 0; i < n; i++) {
    const d = resid[i] - residMean;
    ss += d * d;
  }
  const residStd = Math.sqrt(ss / n);

  const mid = a * (n - 1) + b;
  const upper = mid + numStd * residStd;
  const lower = mid - numStd * residStd;
  const price = window[n - 1];
  const span = upper - lower;
  const position = span === 0 ? 0.5 : (price - lower) / span;
  return { slope: a, mid, upper, lower, price, position };
}

export interface Stochastic {
  raw_k: number;
  k: number;
  d: number;
}

/**
 * Stochastic oscillator (14,5,3): raw %K over `kPeriod`, slowed by an
 * `smoothK` SMA, with %D an `smoothD` SMA of the slow %K.
 */
export function stochastic(
  highs: readonly number[], lows: readonly number[], closes: readonly number[],
  kPeriod: number = 14, smoothK: number = 5, smoothD: number = 3,
): Stochastic {
  const n = closes.length;
  const rawK: number[] = new Array(n).fill(NaN);
  for (let i = kPeriod - 1; i < n; i++) {
    let hh = -Infinity;
    let ll = Infinity;
    for (let j = i - kPeriod + 1; j <= i; j++) {
      if (highs[j] > hh) hh = highs[j];
      if (lows[j] < ll) ll = lows[j];
    }
    const rng = hh - ll;
    rawK[i] = rng === 0 ? 50.0 : (100.0 * (closes[i] - ll)) / rng;
  }
  const slowK = sma(rawK, smoothK);
  const d = sma(slowK, smoothD);
  return {
    raw_k: rawK[n - 1],
    k: Number.isNaN(slowK[n - 1]) ? rawK[n - 1] : slowK[n - 1],
    d: Number.isNaN(d[n - 1]) ? slowK[n - 1] : d[n - 1],
  };
}

export interface Macd {
  macd: number;
  signal: number;
  hist: number;
  hist_change: number;
}

/**
 * MACD(8,17,9): fast EMA - slow EMA, its signal EMA, and the histogram plus
 * its one-bar change (positive change == momentum turning up).
 */
export function macd(
  closes: readonly number[], fast: number = 8, slow: number = 17, signal: number = 9,
): Macd {
  const emaFast = ema(closes, fast);
  const emaSlow = ema(closes, slow);
  const macdLine = emaFast.map((v, i) => v - emaSlow[i]);
  const signalLine = ema(macdLine, signal);
  const hist = macdLine.map((v, i) => v - signalLine[i]);
  const n = hist.length;
  const histPrev = n >= 2 ? hist[n - 2] : hist[n - 1];
  return {
    macd: macdLine[n - 1],
    signal: signalLine[n - 1],
    hist: hist[n - 1],
    hist_change: hist[n - 1] - histPrev,
  };
}

// ---- floor signal wrappers --------------------------------------------------

export interface Signal {
  name: string;
  value: string;
  met: boolean;
  detail: string;
}

function linregSignal(closes: readonly number[], period: number, numStd: number): Signal {
  const ch = linregChannel(closes, period, numStd);
  // "At/below the lower rail": position at or under 0 (price <= lower rail).
  const met = ch.position <= 0.0;
  return {
    name: "LinReg Channel",
    value: `${pyFixed(ch.position * 100, 0)}% of channel`,
    met,
    detail: met ? "at/below lower rail" : "above lower rail",
  };
}

function stochasticSignal(
  highs: readonly number[], lows: readonly number[], closes: readonly number[],
): Signal {
  const st = stochastic(highs, lows, closes);
  const met = st.k < 20.0;
  return {
    name: "Stochastic 14,5,3",
    value: `%K ${pyFixed(st.k, 0)}`,
    met,
    detail: met ? "oversold (<20)" : "not oversold",
  };
}

function macdSignal(closes: readonly number[]): Signal {
  const m = macd(closes);
  const met = m.hist_change > 0.0;
  const arrow = met ? "up" : "down";
  return {
    name: "MACD 8,17,9",
    value: `hist ${pyFixed(m.hist, 2, true)}`,
    met,
    detail: `histogram turning ${arrow}`,
  };
}

function mean(values: readonly number[]): number {
  let s = 0;
  for (const v of values) s += v;
  return s / values.length;
}

function smaSignal(closes: readonly number[], period: number = 50): Signal {
  const s = sma(closes, period);
  let ref = s[s.length - 1];
  const price = closes[closes.length - 1];
  if (Number.isNaN(ref)) ref = mean(closes); // series shorter than the SMA window
  const pct = (price / ref - 1.0) * 100.0;
  const met = price < ref; // below the long average == depressed / near a floor
  return {
    name: `Price vs SMA${period}`,
    value: `${pyFixed(pct, 0, true)}% vs SMA`,
    met,
    detail: met ? "below long average" : "above long average",
  };
}

export type TimingVerdict = "REACHING FLOOR" | "NEUTRAL" | "EXTENDED";

export interface TimingSignals {
  verdict: TimingVerdict;
  signals: Signal[];
  score: string;
  met: number;
  total: number;
}

/**
 * Compute all four floor signals + a convergence verdict — the dashboard-ready
 * `timing` block: { verdict, signals: [...], score, met, total }.
 */
export function timingSignals(
  closes: readonly number[],
  highs?: readonly number[],
  lows?: readonly number[],
  channelPeriod: number = 100,
  numStd: number = 2.0,
): TimingSignals {
  const h = highs ?? closes;
  const l = lows ?? closes;

  const signals = [
    linregSignal(closes, channelPeriod, numStd),
    stochasticSignal(h, l, closes),
    macdSignal(closes),
    smaSignal(closes, 50),
  ];
  const met = signals.reduce((acc, s) => acc + (s.met ? 1 : 0), 0);
  const total = signals.length;

  let verdict: TimingVerdict;
  if (met >= 3) {
    verdict = "REACHING FLOOR";
  } else if (met === 0) {
    verdict = "EXTENDED";
  } else {
    verdict = "NEUTRAL";
  }

  return {
    verdict,
    signals,
    score: `${met}/${total} floor conditions met`,
    met,
    total,
  };
}

// ---- ceiling (sell/trim) mirror + the combined timing read ------------------

/**
 * Channel-position rails: position <= DIP_MAX -> the floor (buy) read is live;
 * position >= CEILING_MIN -> the ceiling (sell/trim) read is live. Because
 * DIP_MAX < CEILING_MIN, a name is near the lower rail OR the upper rail —
 * never both.
 */
export const DIP_MAX = 0.34;     // at/under == pressing the lower third of the channel
export const CEILING_MIN = 0.66; // at/over  == pressing the upper third of the channel

export type Tier = "strong" | "setting-up" | "watching";

/** Fold a 0-3 confirmation count into the dashboard tier. */
export function confirmationTier(confirms: number): Tier {
  if (confirms >= 2) return "strong";
  if (confirms === 1) return "setting-up";
  return "watching";
}

export type RailTiming = "REACHING FLOOR" | "NEUTRAL" | "REACHING CEILING";

export interface RailChecks {
  stoch_k: number;
  stoch_d: number;
  stoch_pass: boolean;
  macd_pass: boolean;
  ma_pass: boolean;
  stoch_sell: boolean;
  macd_sell: boolean;
  ma_sell: boolean;
  channel_position: number;
  at_lower_rail: boolean;
  at_upper_rail: boolean;
  floor_confirms: number;
  ceiling_confirms: number;
  tier: Tier;
  ceiling_tier: Tier;
  timing: RailTiming;
}

/**
 * Both directions of the timing lens in one deterministic read (port of
 * core.signals.rail_checks — same confirmations, rails, tiers, and the overall
 * REACHING FLOOR / NEUTRAL / REACHING CEILING verdict).
 */
export function railChecks(
  closes: readonly number[],
  highs?: readonly number[],
  lows?: readonly number[],
  channelPeriod: number = 100,
  numStd: number = 2.0,
  smaPeriod: number = 50,
  dipMax: number = DIP_MAX,
  ceilingMin: number = CEILING_MIN,
): RailChecks {
  const h = highs ?? closes;
  const l = lows ?? closes;

  const st = stochastic(h, l, closes);
  const m = macd(closes);
  const s50 = sma(closes, smaPeriod);
  const last = s50[s50.length - 1];
  const ref = Number.isNaN(last) ? mean(closes) : last;
  const price = closes[closes.length - 1];
  const ch = linregChannel(closes, channelPeriod, numStd);
  const position = ch.position;

  // Floor (buy) side.
  const stochPass = st.k < 20.0;
  const macdPass = m.hist_change > 0.0;
  const maPass = price < ref;

  // Ceiling (sell/trim) side — the inverted mirror. `ma_sell` is a breakdown
  // check ("the 50-day is lost"), not merely "above the average".
  const stochSell = st.k > 80.0;
  const macdSell = m.hist_change < 0.0;
  const maSell = price < ref;

  const atLowerRail = position <= dipMax;
  const atUpperRail = position >= ceilingMin;

  const floorConfirms = (stochPass ? 1 : 0) + (macdPass ? 1 : 0) + (maPass ? 1 : 0);
  const ceilingConfirms = (stochSell ? 1 : 0) + (macdSell ? 1 : 0) + (maSell ? 1 : 0);

  let timing: RailTiming;
  if (atUpperRail && ceilingConfirms >= 2) {
    timing = "REACHING CEILING";
  } else if (atLowerRail && floorConfirms >= 2) {
    timing = "REACHING FLOOR";
  } else {
    timing = "NEUTRAL";
  }

  return {
    stoch_k: st.k,
    stoch_d: st.d,
    stoch_pass: stochPass,
    macd_pass: macdPass,
    ma_pass: maPass,
    stoch_sell: stochSell,
    macd_sell: macdSell,
    ma_sell: maSell,
    channel_position: position,
    at_lower_rail: atLowerRail,
    at_upper_rail: atUpperRail,
    floor_confirms: floorConfirms,
    ceiling_confirms: ceilingConfirms,
    tier: confirmationTier(floorConfirms),
    ceiling_tier: confirmationTier(ceilingConfirms),
    timing,
  };
}
