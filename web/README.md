# web/ — TypeScript engine (Phase 1 of the interactive dashboard)

A framework-agnostic TypeScript port of the deterministic Python engine —
plain functions and classes, no React, no DOM — proven **identical** to the
Python version by a parity gate that runs the same inputs through both engines.

## Modules (`engine/`)

| Module | Ports | What it computes |
| --- | --- | --- |
| `valuation.ts` | `core/valuation.py` | Payback Time, sticker/fair value, margin of safety (defaults: required_return 0.15, margin_of_safety 0.50, projection_years 10, default_future_pe 15) |
| `options.ts` | `core/options.py` | Black-Scholes call/put + delta, T=0 intrinsic fallback. Canonical module: same formulas as the JS embedded in `core/dashboard/index.html`, but with a machine-precision normal CDF (Cephes `ndtr`, the same routine scipy uses) instead of the Abramowitz-Stegun approximation |
| `signals.ts` | `core/signals.py` | Stochastic(14,5,3), MACD(8,17,9), SMA50, linear-regression channel + rails, floor AND ceiling confirmations, tiers, timing verdict (REACHING FLOOR / NEUTRAL / REACHING CEILING) |
| `decision.ts` | `core/decision.py` | BUY/WATCH/PASS verdict + conviction + evidence criteria (3 pass → BUY, 2 → WATCH, ≤1 → PASS) |
| `screen.ts` | `core/screen.py` + `core/emit.py` cuts | Watchlist rankings + the Screen (Payback ≤ 10y AND FCF yield ≥ 5%; pass = both, watch = one) |
| `index.ts` | `core/decision.build_decisions` / `core/emit._technicals_for` | Barrel + `buildDecision` / `buildDecisions` / `technicalsFor` — the full per-ticker decision object (valuation + verdict + technicals) from a config row + a price series, in the same shape `core/emit.py` writes, ready for the React UI |
| `pyformat.ts` | — | Exact Python `round()` / `f"{x:.Nf}"` semantics (ties-to-even on the exact binary value, via BigInt) so rounded numbers and formatted strings match Python byte-for-byte |

## Run it

```bash
cd web
npm install            # typescript + @types/node only (tests use node:test)

npm run fixtures       # python3 scripts/dump_engine.py — regenerate the Python
                       # engine's expected outputs (engine/__tests__/fixtures.json)
npm run typecheck      # tsc --noEmit
npm test               # node --test engine/__tests__/parity.test.ts
```

Requires Node ≥ 22.6 (built-in TypeScript type stripping runs the `.ts` test
directly) and the repo's Python environment (numpy + scipy) for fixture
regeneration. The committed `fixtures.json` means `npm test` alone reproduces
the parity check without Python.

## The parity gate

`scripts/dump_engine.py` feeds the Python engine:

- all 9 tickers from `config.example.json`,
- the deterministic shaped OHLC series (floor / neutral / extended) that
  `core/emit.py` generates,
- a 420-point Black-Scholes grid (S × T × r × sigma × call/put, including
  T=0 and sigma=0 intrinsic cases) plus a scipy `norm.cdf` grid,

and serializes inputs + expected outputs to `engine/__tests__/fixtures.json`
(floats round-trip exactly through JSON, so both engines consume bit-identical
inputs). `parity.test.ts` replays everything through the TS engine and asserts:

- floats within **1e-6** (observed max deviation ≈ 3e-14),
- normal CDF within 1e-12 of scipy,
- verdicts, tiers, booleans, ranks, key sets, and every formatted string
  (`"%K 12"`, `"hist +0.42"`, `"+23%"` …) **exactly** equal,
- the reference call S=K=100, T=1, r=.05, σ=.2 ≈ 10.4506,
- floor-shaped series → REACHING FLOOR, neutral → NEUTRAL, extended →
  REACHING CEILING,
- the screen pass set on the sample data is exactly {CI, JPM, NKE}.

Sample data — illustrative only, not investment advice.
