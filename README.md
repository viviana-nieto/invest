# invest — an equity decision terminal

> **A decision agent a whole team can trust — and just ask.**
> Investing is the demo; the pattern is the point. AI agents read; a deterministic engine
> makes the call; every verdict shows its work — so a non-expert can *see why* and rely on it.

**Runs on any LLM** — Claude, OpenAI, or a fully-local model via Ollama; the engine runs with
**no LLM at all**. Three front doors, one engine: a **Claude Code** skill, a **plain-language
`ask`** ("what's worth buying, and why?"), and an **MCP server** that drops into Claude Desktop /
Cursor / a team chat — so anyone on the team can use it in the tools they already have.

> **The deterministic engine makes the call; the LLM only reads and routes. Math decides, AI narrates.**
> Two lenses of one tool: **VALUE** ("what's worth buying") turns Payback&nbsp;Time,
> margin&nbsp;of&nbsp;safety, and free&nbsp;cash&nbsp;flow into a **BUY / WATCH / PASS** verdict with a
> full evidence trail; **TIMING** ("when to buy it") converges four independent technical
> signals into a **REACHING FLOOR / NEUTRAL / EXTENDED** call. Every verdict, conviction
> score, and rank is arithmetic — reproducible and identical every run — not a model's opinion.

---

## The problem

A Bloomberg Terminal runs about **$24,000/yr** — a professional decision cockpit
most people will never touch. Retail investors get the other extreme: Yahoo Finance
tables and Reddit threads, with no repeatable way to turn the numbers into a call.
And most "AI stock" tools make it worse — they let the language model both gather
the news *and* render the verdict, so the same question can get a different answer
twice in a row and you can't audit why.

Value investing is supposed to be the opposite: a few standard formulas (Payback
Time, sticker price, margin of safety) that anyone can recompute by hand. This is a
free, open-source **decision terminal** built on that principle — the model surfaces
the news; the deterministic engine makes the call.

## What this does

- **VALUE lens — BUY/WATCH/PASS verdicts + ranking.** Scores every name against three
  deterministic criteria (Payback&nbsp;Time&nbsp;<&nbsp;12y · Margin&nbsp;of&nbsp;Safety&nbsp;>&nbsp;0 · positive&nbsp;FCF):
  all 3 pass → BUY, exactly 2 → WATCH, ≤1 → PASS. Ranks the universe by a conviction
  score derived from the margin of safety. Same inputs, same ranking, every time.
- **TIMING lens — floor detection.** Converges four independent signals from a price
  series (linear-regression channel, Stochastic 14,5,3, MACD 8,17,9, price vs SMA50)
  into REACHING FLOOR / NEUTRAL / EXTENDED. Pure numpy, no TA library.
- **Prices options** with textbook Black-Scholes (European call/put + delta), with a
  clean intrinsic-value fallback at expiry.
- **Fans out news agents in parallel**, each returning schema-validated JSON — narrative
  color beside the engine's verdicts.
- **Renders a multi-tab static HTML terminal** — no server, no external assets — with a
  Watchlist (fundamentals + the signature **Signal** column + expandable BUY/WATCH/PASS
  evidence trails), a value **Screen** (Payback&nbsp;≤&nbsp;10y **and** FCF&nbsp;yield&nbsp;≥&nbsp;5%),
  a **Signals** timing lens, a live-in-browser **Options Pricing** (Black-Scholes) tab,
  and a **Macro** snapshot. GitHub-dark, offline, opens as a bare file.
- **Runs offline** on illustrative sample fundamentals + sample OHLC; optionally overlays
  live prices, candles, and a **historical operating-income CAGR** growth rate
  (SEC EDGAR / yfinance) when available — see "How growth is computed".

## Access — anyone on your team can just ask

The thesis behind this repo is **agents other teams can trust and use** — and
"use" means a non-technical teammate, in plain language, in the tools they
already have. Two front doors, one engine:

### 1. Just ask (plain-language CLI)

```bash
python3 -m orchestration.ask "which stocks are worth buying and why?"
python3 -m orchestration.ask "is AMZN reaching a floor?"
python3 -m orchestration.ask "price a call on AAPL strike 230 expiring in 1 year"
```

No flags to memorize, no JSON to read. An optional LLM (`LLM_PROVIDER` =
anthropic / openai / ollama / mock) **only routes** the question to one of four
deterministic tools — it never computes the answer or makes the call. With no
model configured (or with `--no-llm`) a deterministic keyword router does the
same job, so `ask` works with zero LLM. Either way, every answer is
**evidence-backed**: the verdict plus the criteria met/failed, with the numbers.

```
$ python3 -m orchestration.ask --no-llm "what should I buy?"
 #1 NVDA  BUY   (conviction 65)  ✓ Payback Time 9.5y (need < 12y) · ✓ Margin of Safety +60% (need > 0) · ✓ FCF positive ...
 #2 AMZN  BUY   (conviction 53)  ✓ Payback Time 11.2y (need < 12y) · ✓ Margin of Safety +13% (need > 0) · ✓ FCF positive ...
 ...
⚙ engine decides · 🤖 agents narrate
```

### 2. Drops into your team's tools (MCP server)

`adapters/mcp/server.py` exposes the same engine as **MCP tools** —
`screen_watchlist`, `analyze_ticker`, `floor_signals`, `price_option` — so it
plugs straight into **Claude Desktop, Cursor, or any MCP-capable internal
chat**. Your teammate asks in their chat window; the model calls the tool; the
deterministic engine returns the verdict *with its evidence trail*. Setup (one
config snippet + `pip install mcp`) in [`adapters/mcp/README.md`](adapters/mcp/README.md).

## See it working

```
$ python3 -m core.screen --decisions
[ #1 NVDA  BUY   conviction 65  payback 9.5y ✓  MoS +60% ✓  FCF + ✓  | REACHING FLOOR 4/4 ]
[ #2 AMZN  BUY   conviction 53  payback 11.2y ✓ MoS +13% ✓  FCF + ✓  | REACHING FLOOR 4/4 ]
[ #3 GOOGL WATCH conviction 48  payback 10.0y ✓ MoS  -6% ✗  FCF + ✓  | NEUTRAL 1/4 ]
...
$ python3 -m core.emit                     # sample-data/*.json + core/dashboard/data.js
$ open core/dashboard/index.html           # the multi-tab terminal (offline)
```

---

## Install

### Claude Code
```bash
git clone https://github.com/viviana-nieto/invest ~/.claude/skills/invest
```
Then run `/invest` in any Claude Code session (see `adapters/claude-code/skill.md`).

### Any LLM (bring your own)
```bash
git clone https://github.com/viviana-nieto/invest && cd invest
pip install -r requirements.txt
cp config.example.json config.json   # edit to taste

# Deterministic engine — no LLM, no keys:
python3 -m core.screen --sort payback_years
python3 -m core.emit            # generate sample data, then open core/dashboard/index.html

# Parallel news agents on any provider:
cd orchestration
export LLM_PROVIDER=ollama            # or anthropic / openai / mock
python3 run.py --prompt prompts/news_agent.txt --schema schema.json
```

**Bring your own credentials.** This skill ships with none — it uses whatever
you configure locally, never anyone else's:

- **LLM (optional):** `LLM_PROVIDER` picks the provider; supply that provider's
  own key in your environment (e.g. `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`), or
  run `ollama` fully local with no key at all. The deterministic engine needs no
  LLM.
- **Live growth (optional):** the CAGR growth fetcher reads SEC EDGAR, which is
  free and keyless but requires a descriptive User-Agent or it returns 403. Set
  your own before using live data:
  ```bash
  export SEC_EDGAR_USER_AGENT="Your Name you@example.com"
  ```
  Without it, live growth is skipped and rows fall back to config values or the
  conservative default — the rest of the skill works unchanged.

### MCP (Claude Desktop / Cursor / any MCP client)

```bash
pip install mcp
```

Then point your client at `adapters/mcp/server.py` — full config snippet in
[`adapters/mcp/README.md`](adapters/mcp/README.md). Four tools
(`screen_watchlist`, `analyze_ticker`, `floor_signals`, `price_option`), each a
thin wrapper over the deterministic `core/` functions, each returning the
evidence alongside the verdict. The SDK is optional: the engine, the `ask` CLI,
and the test suite never require it.

### Plain language (no install beyond the repo)

```bash
python3 -m orchestration.ask --no-llm "what should I buy?"
```

---

## Configuration

Config lives in `config.json` (gitignored; copy from `config.example.json`).

| Key | Meaning | Default |
|---|---|---|
| `llm.provider` | `anthropic` \| `openai` \| `ollama` \| `mock` | `mock` |
| `skill.projection_years` | Horizon for sticker-price EPS projection | `10` |
| `skill.required_return` | Discount rate / minimum acceptable return | `0.15` |
| `skill.margin_of_safety` | Discount below sticker price to buy | `0.50` |
| `skill.default_future_pe` | Fallback future P/E when a row omits one | `15.0` |
| `skill.default_growth_rate` | Fallback growth when a row omits `growth_rate` and no live CAGR is available | `0.0` |
| `skill.watchlist[]` | `{ticker, name, sector, price, eps, growth_rate, future_pe, fcf, shape, narrative}` rows | mega-caps |

Watchlist rows add a few fields for the two lenses: `name`/`sector` label the card,
`fcf` (`"positive"`/`"negative"`) is the third value criterion, `shape`
(`floor`/`neutral`/`extended`) selects the offline sample OHLC series for the timing
lens, and `narrative` is the canned **agent voice** sample — the LLM's one-liner that
sits beside a verdict the math already made.

### How growth is computed

`growth_rate` — the input to Payback Time and sticker price — is not a guess.
When fetching live data (`core.fundamentals`), it is derived from the company's
**historical annual operating-income (EBIT) series**, oldest → newest, capped at
the last 10 fiscal years — SEC EDGAR preferred (10+ years of 10-K filings),
yfinance `income_stmt` as the fallback (~4 years):

```
growth_rate = max(0, (last / first) ** (1 / n) - 1)      # n = years spanned
```

The full-window CAGR, **floored at 0** — a shrinking business never gets
negative "growth" projected forward. Special cases: operating income turned
positive (**Turnaround**) → use the analyst forward estimate if positive, else 0;
turned negative (**Declining**) → 0; still negative → shrinking losses earn
their annual loss-reduction rate, growing losses get 0. Trailing 10/7/5/3/1-year
CAGRs are also reported as `cagr_periods`.

Precedence per row: **config manual override** (a numeric `growth_rate` in
`config.json` — never touched) → **computed historical CAGR** →
**`skill.default_growth_rate`** (default `0.0`, the documented no-data
fallback). Offline, the shipped sample values act as the override, so
everything still runs with no network.

## How it works

Two layers, cleanly separated:

- **`core/` — deterministic, zero LLM.** `valuation.py` computes Payback Time (years
  for cumulative growing earnings to repay today's price), sticker price (future EPS ×
  future P/E, discounted back at the required return), and margin of safety.
  `decision.py` turns those into the BUY/WATCH/PASS verdict + conviction + evidence
  checklist (the VALUE lens). `signals.py` computes the four floor indicators and their
  convergence verdict (the TIMING lens); `sample_prices.py` ships offline OHLC.
  `options.py` is standard Black-Scholes. `screen.py` ranks the universe by conviction;
  `emit.py` writes the dashboard's JSON contract + a deterministic sample universe;
  `dashboard/index.html` is the offline multi-tab terminal that reads it.
- **`orchestration/` — portable LLM layer.** `run.py` loads a prompt, sends it to any
  provider, extracts + validates JSON against `schema.json` (retrying on bad output),
  and `run_parallel()` fans many prompts out concurrently. The Claude Code adapter
  spawns one news agent per ticker batch in parallel. `ask.py` is the
  plain-language front door: the LLM (or a zero-LLM keyword router) classifies a
  question into a schema-validated intent — `{tool, args}` — and the matching
  `core/` function computes the evidence-backed answer.
- **`adapters/` — where teams meet the engine.** The Claude Code skill
  (`adapters/claude-code/skill.md`) and the MCP server (`adapters/mcp/server.py`)
  are both thin shells over the same `core/` functions.

The pattern: **agents fan out in parallel and return validated JSON; a deterministic
engine turns the numbers into the verdict.** The LLM never decides buy/sell.

## Development

```bash
python3 -m pytest        # unit + e2e (mock provider, no network/keys)
```

## Disclaimer

Educational tool. Sample fundamentals are illustrative and not current. **Not
investment advice.**

## License

MIT
