# /invest

A **decision loop** for value investing: a deterministic engine makes every call,
parallel LLM agents only narrate. Two lenses of one tool —

- **VALUE** ("what's worth buying"): Payback&nbsp;Time + margin&nbsp;of&nbsp;safety + FCF →
  a **BUY / WATCH / PASS** verdict per stock, with the evidence trail.
- **TIMING** ("when to buy it"): four independent technical signals →
  a **REACHING FLOOR / NEUTRAL / EXTENDED** convergence verdict per stock.

> The math decides; the model reads. No LLM votes on a verdict.

## Usage

```
/invest ask "<plain-language question>"
/invest dashboard
/invest screen [--sort margin_of_safety|payback_years]
/invest signals
/invest news
/invest <TICKER> --strike <K> --exp <YYYY-MM-DD> [--vol <sigma>] [--rate <r>] [--put]
```

Examples:
```
/invest ask "which stocks are worth buying and why?"
/invest dashboard
/invest screen
/invest signals
/invest news
/invest AAPL --strike 230 --exp 2025-12-19 --vol 0.25
```

All paths below are **repo-relative** — run them from the skill's repo root.

---

## Access — anyone on your team can just ask

This skill is one of **three front doors to the same deterministic engine**,
so a non-technical teammate never needs special commands:

- **Plain language**: `python3 -m orchestration.ask "which stocks are worth
  buying and why?"` — an LLM (or, with `--no-llm`, a deterministic keyword
  router) *only routes* the question to one of four engine tools; the answer is
  always the engine's verdict plus its evidence (criteria met/failed, with
  numbers). Never a bare opinion.
- **Their existing tools**: `adapters/mcp/server.py` drops the engine into
  Claude Desktop / Cursor / any MCP chat as `screen_watchlist`,
  `analyze_ticker`, `floor_signals`, `price_option` (see `adapters/mcp/README.md`).
- **This skill** for Claude Code users.

The governance rule holds on every door: **the LLM routes; the engine decides.**

## Subcommand: `ask` — plain-language questions

Answer any free-form question by running the front door and relaying its
evidence-backed output verbatim (it already contains the verdict + criteria):

```bash
python3 -m orchestration.ask --no-llm "<the user's question>"
```

Handles: "what should I buy / screen the list", "analyze TICKER", "is TICKER
reaching a floor / when do I buy", "price a call/put on TICKER strike X
expiring in N months". With `LLM_PROVIDER` set the routing goes through the
model instead of keywords — the answer is identical because the engine, not the
router, computes it.

## Subcommand: `screen` — Part 1, the VALUE lens

Rank the universe by **conviction** (descending) and print the BUY/WATCH/PASS
verdict for each name with its three-criterion evidence checklist.

```bash
python3 -m core.screen --decisions
```

Each decision object carries `valuation.verdict`, `valuation.conviction`, the
`criteria` checklist (Payback&nbsp;Time&nbsp;<&nbsp;12y · Margin&nbsp;of&nbsp;Safety&nbsp;>&nbsp;0 · positive&nbsp;FCF),
and an agent `narrative`. Verdict logic is deterministic: **all 3 pass → BUY**,
**exactly 2 → WATCH**, **≤1 → PASS**.

Present it as a ranked table: rank, ticker, verdict, conviction, the three
pass/fail criteria, and margin of safety. For the classic flat valuation table
(sticker/buy-price columns) use `python3 -m core.screen --sort payback_years`.

## Subcommand: `signals` — Part 2, the TIMING lens

Compute the four floor signals + convergence verdict per stock, from sample
OHLC (offline) or live candles.

```bash
python3 -c "import json; from core.screen import load_config, _resolve_config, rank_by_conviction; print(json.dumps([{'ticker':d['ticker'],'timing':d['timing']} for d in rank_by_conviction(load_config(_resolve_config(None)))], indent=2))"
```

Report each name's `timing.verdict` and `timing.score` ("N/4 floor conditions
met") plus which of the four signals fired: **LinReg channel** (at/below lower
rail), **Stochastic 14,5,3** (oversold <20), **MACD 8,17,9** (histogram turning
up), **Price vs SMA50** (below the long average). ≥3 of 4 → REACHING FLOOR.

For **live candles**, `core.fetch_prices.fetch_ohlc(ticker)` returns
`(highs, lows, closes)` via yfinance (guarded import; falls back to the sample
series offline). Feed them to `core.signals.timing_signals(closes, highs, lows)`.

## Subcommand: `dashboard` — the multi-tab terminal

Generate the sample JSON contract and open the self-contained, multi-tab
**equity decision terminal** (`core/dashboard/index.html`): a Watchlist with the
signature **Signal** column + expandable BUY/WATCH/PASS evidence trails, a value
**Screen** (Payback&nbsp;≤&nbsp;10y **and** FCF&nbsp;yield&nbsp;≥&nbsp;5%), the **Signals**
timing lens, a live-in-browser **Options Pricing** (Black-Scholes) tab, and a
**Macro** snapshot.

```bash
python3 -m core.emit                    # writes sample-data/*.json + core/dashboard/data.js
```

Then open `core/dashboard/index.html` (it works as a bare `file://` — the data is
also bundled into `core/dashboard/data.js` so no server is needed). Summarize the
ranking: which names are BUY, which are REACHING FLOOR, and where value and timing
agree (the strongest setups).

The older single-page verdict-card view is still available via
`python3 -m core.build_dashboard --out core/dashboard/cards.html`.

## Subcommand: `news` — parallel agents (the "narrate" half)

Fan out **one news agent per batch of tickers**, each returning JSON that
satisfies `orchestration/schema.json`. The news is color; the engine's verdict is
the call.

1. Read the watchlist tickers from `config.json` (fall back to `config.example.json`).
2. Read the prompt template `orchestration/prompts/news_agent.txt` — it has
   `{{tickers}}` and `{{date}}` placeholders.
3. Split tickers into 2-3 batches and **spawn one Agent per batch in parallel**
   (a single message, multiple Agent tool calls). Instruct each to return ONLY
   JSON: `{ "date", "items": [ { "ticker", "headline", "summary", "sentiment", "sources" } ] }`.
4. Validate each agent's JSON against `orchestration/schema.json`, merge the
   `items` arrays, present a per-ticker digest.
5. Then run `screen` so the news sits beside the deterministic verdicts.

Portable equivalent (any LLM, no Claude Code):
```bash
cd orchestration
LLM_PROVIDER=mock python3 run.py --prompt prompts/news_agent.txt --schema schema.json
```

## Subcommand: `<TICKER> --strike X --exp DATE` — Black-Scholes

Price a European option on the ticker with the deterministic Black-Scholes engine.

1. Determine the underlying price `S`: the ticker's `price` from the config
   watchlist, or a live fetch via `core.fetch_prices`.
2. Compute `T` = (exp date − today) / 365.
3. Use `--vol` for sigma (default 0.25) and `--rate` for r (default 0.04).
4. Call the engine:

```bash
python3 -c "from core.options import price_option; import json; print(json.dumps(price_option(S, K, T, r, sigma, 'call'), indent=2))"
```

Report premium and delta. Add `--put` to price a put. If expiry is today (`T=0`),
the engine returns intrinsic value.

---

## The decision loop, end to end

1. `screen` — the VALUE engine assigns each name BUY/WATCH/PASS and ranks by conviction.
2. `signals` — the TIMING engine flags which names are pressing a floor.
3. `dashboard` — both lenses in the multi-tab terminal. The best setups are
   where a BUY meets a REACHING FLOOR (the 🟢 tier in the Signal column).
4. `news` — parallel agents add narrative colour; they never move a verdict.

## How growth is computed (live data)

When fetching live data for a ticker, `growth_rate` comes from
`core.fundamentals.earnings_cagr_growth(ticker)` — the **historical annual
operating-income (EBIT) CAGR**, not a guess:

- Series: annual operating income oldest → newest, last 10 fiscal years.
  SEC EDGAR preferred (10+ yrs of 10-Ks), yfinance `income_stmt` fallback (~4 yrs).
- `growth_rate = max(0, (last/first)**(1/n) - 1)` — full-window CAGR,
  **floored at 0**; label `"{n}yr CAGR"`, plus trailing `cagr_periods`
  (10/7/5/3/1-yr windows).
- Special cases: losses → profit = **Turnaround** (analyst forward estimate if
  positive, else 0); profit → losses = **Declining** (0); persistent losses =
  annual loss-reduction rate or 0.

Precedence per watchlist row: **config manual override** (a numeric
`growth_rate` in `config.json`, never touched) > **computed CAGR** >
**`skill.default_growth_rate`** (default 0.0). To overlay live prices *and*
growth in one call:

```bash
python3 -c "from core.screen import load_config, _resolve_config, screen; from core.fetch_prices import enrich_config_with_live_data; import json; print(json.dumps(screen(enrich_config_with_live_data(load_config(_resolve_config(None)))), indent=2))"
```

Offline (no yfinance / no network) nothing changes: the sample `growth_rate`
values in the config act as the override and the engine runs as before.

## Notes

- The `core/` engine has **zero LLM** — same inputs always produce the same
  verdict, conviction, and ranking. Only `news` calls a model.
- `config.example.json` fundamentals + sample OHLC are illustrative so everything
  runs offline. Copy to `config.json` and edit for live use.
- Not investment advice.
