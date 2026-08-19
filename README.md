# invest-open

> A value-investing **decision loop**: a deterministic engine makes the call,
> parallel LLM agents only narrate — for anyone who wants the math, not a vibe, to decide.

**Runs on any LLM** — Claude, OpenAI, or a fully-local model via Ollama. Ships with
a Claude Code skill for one-command use, plus a portable runner for everything else.

> **The deterministic engine makes the call; the LLM agents only narrate. Math decides, AI reads.**
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
  evidence trails), a dip/value **Screen**, a **Signals** timing lens, a live-in-browser
  **Options Pricing** (Black-Scholes) tab, a **Macro** snapshot, and an **Exploration**
  universe. GitHub-dark, offline, opens as a bare file.
- **Runs offline** on illustrative sample fundamentals + sample OHLC; optionally overlays
  live prices and candles via yfinance when available.

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
git clone https://github.com/your-username/invest-open ~/.claude/skills/invest-open
```
Then run `/invest` in any Claude Code session (see `adapters/claude-code/skill.md`).

### Any LLM (bring your own)
```bash
git clone https://github.com/your-username/invest-open && cd invest-open
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

### MCP (planned)

An MCP server that exposes `screen`, `signals`, and `price_option` as tools — so
any MCP-capable client can drive the same deterministic engine — is on the roadmap.
The engine already has a clean function boundary (`core/`), so the wrapper is thin.

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
| `skill.watchlist[]` | `{ticker, name, sector, price, eps, growth_rate, future_pe, fcf, shape, narrative}` rows | mega-caps |

Watchlist rows add a few fields for the two lenses: `name`/`sector` label the card,
`fcf` (`"positive"`/`"negative"`) is the third value criterion, `shape`
(`floor`/`neutral`/`extended`) selects the offline sample OHLC series for the timing
lens, and `narrative` is the canned **agent voice** sample — the LLM's one-liner that
sits beside a verdict the math already made.

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
  spawns one news agent per ticker batch in parallel.

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
