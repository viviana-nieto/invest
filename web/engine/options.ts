/**
 * Black-Scholes European option pricing — deterministic, no LLM.
 * TypeScript port of core/options.py (the canonical module for the web UI).
 *
 *     d1 = (ln(S/K) + (r + sigma^2/2) T) / (sigma sqrt(T))
 *     d2 = d1 - sigma sqrt(T)
 *     C  = S N(d1) - K e^(-rT) N(d2)
 *     P  = K e^(-rT) N(-d2) - S N(-d1)      (via put-call parity)
 *
 * N() is the standard normal CDF. The Python engine uses scipy.stats.norm.cdf,
 * which is the Cephes `ndtr` routine — so this port ships the same Cephes
 * erf/erfc rational approximations (double precision, ~1e-16), not the cruder
 * Abramowitz–Stegun polynomial the legacy dashboard (core/dashboard/index.html,
 * ==BS_START==..==BS_END==) embeds (~1e-7). Same formulas and the same
 * T<=0 / sigma<=0 intrinsic-value fallback as both prior implementations;
 * only the CDF precision is upgraded so TS == Python to machine precision.
 *
 * At expiry (T == 0) an option is worth exactly its intrinsic value, which we
 * return directly to avoid division by zero.
 */

import { pyRound } from "./pyformat.ts";

export type OptionKind = "call" | "put";

// ---- standard normal CDF (Cephes ndtr port: erf/erfc rational approximations)

const MAXLOG = 7.09782712893383996843e2; // log(2^1024)
const SQRTH = 7.07106781186547524401e-1; // sqrt(2)/2

// erf(x) for |x| < 1:  x * P(x^2) / Q(x^2)
const ERF_T = [
  9.60497373987051638749e0, 9.00260197203842689217e1, 2.23200534594684319226e3,
  7.00332514112805075473e3, 5.55923013010394962768e4,
];
const ERF_U = [
  // implicit leading 1.0
  3.35617141647503099647e1, 5.21357949780152679795e2, 4.59432382970980127987e3,
  2.26290000613890934246e4, 4.92673942608635921086e4,
];

// erfc(x) for 1 <= x < 8
const ERFC_P = [
  2.46196981473530512524e-10, 5.64189564831068821977e-1, 7.46321056442269912687e0,
  4.86371970985681366614e1, 1.96520832956077098242e2, 5.26445194995477358631e2,
  9.34528527171957607540e2, 1.02755188689515710272e3, 5.57535335369399327526e2,
];
const ERFC_Q = [
  // implicit leading 1.0
  1.32281951154744992508e1, 8.67072140885989742329e1, 3.54937778887819891062e2,
  9.75708501743205489753e2, 1.82390916687909736289e3, 2.24633760818710981792e3,
  1.65666309194161350182e3, 5.57535340817727675546e2,
];

// erfc(x) for x >= 8
const ERFC_R = [
  5.64189583547755073984e-1, 1.27536670759978104416e0, 5.01905042251180477414e0,
  6.16021097993053585195e0, 7.40974269950448939160e0, 2.97886665372100240670e0,
];
const ERFC_S = [
  // implicit leading 1.0
  2.26052863220117276590e0, 9.39603524938001434673e0, 1.20489539808096656605e1,
  3.20332675697189572855e1, 9.70843505387964458329e0, 6.11115679723064073573e0,
];

function polevl(x: number, coef: number[]): number {
  let ans = coef[0];
  for (let i = 1; i < coef.length; i++) ans = ans * x + coef[i];
  return ans;
}

function p1evl(x: number, coef: number[]): number {
  let ans = x + coef[0];
  for (let i = 1; i < coef.length; i++) ans = ans * x + coef[i];
  return ans;
}

function erf(x: number): number {
  if (Math.abs(x) > 1.0) return 1.0 - erfc(x);
  const z = x * x;
  return (x * polevl(z, ERF_T)) / p1evl(z, ERF_U);
}

function erfc(a: number): number {
  const x = Math.abs(a);
  if (x < 1.0) return 1.0 - erf(a);

  let z = -a * a;
  if (z < -MAXLOG) return a < 0 ? 2.0 : 0.0; // underflow
  z = Math.exp(z);

  let p: number;
  let q: number;
  if (x < 8.0) {
    p = polevl(x, ERFC_P);
    q = p1evl(x, ERFC_Q);
  } else {
    p = polevl(x, ERFC_R);
    q = p1evl(x, ERFC_S);
  }
  let y = (z * p) / q;
  if (a < 0) y = 2.0 - y;
  if (y === 0.0) return a < 0 ? 2.0 : 0.0; // underflow
  return y;
}

/** Standard normal CDF — matches scipy.stats.norm.cdf (Cephes ndtr). */
export function normCdf(a: number): number {
  const x = a * SQRTH;
  const z = Math.abs(x);
  let y: number;
  if (z < SQRTH) {
    y = 0.5 + 0.5 * erf(x);
  } else {
    y = 0.5 * erfc(z);
    if (x > 0) y = 1.0 - y;
  }
  return y;
}

// ---- Black-Scholes ----------------------------------------------------------

function d1d2(S: number, K: number, T: number, r: number, sigma: number): [number, number] {
  const denom = sigma * Math.sqrt(T);
  const d1 = (Math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / denom;
  const d2 = d1 - denom;
  return [d1, d2];
}

/**
 * Price of a European call. At T == 0 (or sigma == 0) returns intrinsic value
 * max(S - K, 0).
 */
export function blackScholesCall(S: number, K: number, T: number, r: number, sigma: number): number {
  if (T <= 0 || sigma <= 0) return Math.max(S - K, 0.0);
  const [d1, d2] = d1d2(S, K, T, r, sigma);
  return S * normCdf(d1) - K * Math.exp(-r * T) * normCdf(d2);
}

/**
 * Price of a European put, via put-call parity: P = C - S + K e^(-rT).
 * At T == 0 (or sigma == 0) returns intrinsic value max(K - S, 0).
 */
export function blackScholesPut(S: number, K: number, T: number, r: number, sigma: number): number {
  if (T <= 0 || sigma <= 0) return Math.max(K - S, 0.0);
  const call = blackScholesCall(S, K, T, r, sigma);
  return call - S + K * Math.exp(-r * T);
}

/**
 * Option delta. Call delta = N(d1) in [0, 1]; put delta = N(d1) - 1 in [-1, 0].
 * At T == 0 (or sigma == 0) delta collapses to the step function.
 */
export function delta(
  S: number, K: number, T: number, r: number, sigma: number,
  kind: OptionKind = "call",
): number {
  if (kind !== "call" && kind !== "put") {
    throw new Error("kind must be 'call' or 'put'");
  }
  if (T <= 0 || sigma <= 0) {
    if (kind === "call") return S > K ? 1.0 : 0.0;
    return S < K ? -1.0 : 0.0;
  }
  const [d1] = d1d2(S, K, T, r, sigma);
  const nd1 = normCdf(d1);
  return kind === "call" ? nd1 : nd1 - 1.0;
}

export interface PricedOption {
  kind: OptionKind;
  S: number;
  K: number;
  T: number;
  r: number;
  sigma: number;
  premium: number;
  delta: number;
}

/** Convenience: price + delta for one option (dashboard-friendly dict). */
export function priceOption(
  S: number, K: number, T: number, r: number, sigma: number,
  kind: OptionKind = "call",
): PricedOption {
  let premium: number;
  if (kind === "call") {
    premium = blackScholesCall(S, K, T, r, sigma);
  } else if (kind === "put") {
    premium = blackScholesPut(S, K, T, r, sigma);
  } else {
    throw new Error("kind must be 'call' or 'put'");
  }
  return {
    kind, S, K, T, r, sigma,
    premium: pyRound(premium, 4),
    delta: pyRound(delta(S, K, T, r, sigma, kind), 4),
  };
}
