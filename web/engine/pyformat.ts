/**
 * Python-compatible float rounding and fixed-point formatting.
 *
 * Python's `round(x, n)` and `f"{x:.Nf}"` round the EXACT binary value of a
 * double to N decimal places with ties-to-even (banker's rounding). JavaScript's
 * `Math.round` / `Number.prototype.toFixed` use different tie rules, so the port
 * reimplements the exact algorithm: decompose the double into mantissa * 2^exp
 * with BigInt and do exact integer arithmetic. This keeps the TS engine's
 * rounded numbers and formatted strings byte-identical to the Python engine's.
 */

/** Exact round-half-even of |x| * 10^ndigits as a non-negative BigInt. */
function scaledHalfEven(absX: number, ndigits: number): bigint {
  // |x| = mant * 2^exp, exactly (IEEE-754 double decomposition).
  const dv = new DataView(new ArrayBuffer(8));
  dv.setFloat64(0, absX);
  const bits = dv.getBigUint64(0);
  let biasedExp = Number((bits >> 52n) & 0x7ffn);
  let mant = bits & 0xfffffffffffffn;
  if (biasedExp === 0) {
    biasedExp = 1; // subnormal
  } else {
    mant |= 0x10000000000000n; // implicit leading bit
  }
  const exp = biasedExp - 1075;

  // q = round(mant * 10^ndigits * 2^exp), ties to even — all exact.
  let num = mant * 10n ** BigInt(ndigits);
  let den = 1n;
  if (exp >= 0) {
    num <<= BigInt(exp);
  } else {
    den = 1n << BigInt(-exp);
  }
  let q = num / den;
  const rem2 = (num % den) * 2n;
  if (rem2 > den || (rem2 === den && (q & 1n) === 1n)) q += 1n;
  return q;
}

/** Python's round(x, ndigits): exact decimal rounding, ties to even. */
export function pyRound(x: number, ndigits: number = 0): number {
  if (!Number.isFinite(x) || x === 0) return x; // NaN, ±Inf, ±0 pass through
  const q = scaledHalfEven(Math.abs(x), ndigits);
  const r = Number(q) / 10 ** ndigits;
  return x < 0 ? -r : r;
}

/**
 * Python's f"{x:.Nf}" (plusSign=false) / f"{x:+.Nf}" (plusSign=true).
 * Matches Python's ties-to-even and its "-0" output for small negatives.
 */
export function pyFixed(x: number, digits: number, plusSign: boolean = false): string {
  if (Number.isNaN(x)) return plusSign ? "+nan" : "nan";
  if (!Number.isFinite(x)) return x < 0 ? "-inf" : plusSign ? "+inf" : "inf";
  const neg = x < 0 || Object.is(x, -0);
  let s = scaledHalfEven(Math.abs(x), digits).toString();
  if (digits > 0) {
    if (s.length <= digits) s = s.padStart(digits + 1, "0");
    s = s.slice(0, s.length - digits) + "." + s.slice(s.length - digits);
  }
  return (neg ? "-" : plusSign ? "+" : "") + s;
}
