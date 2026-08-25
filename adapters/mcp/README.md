# MCP server — drop the engine into the tools your team already uses

This adapter exposes the deterministic `core/` engine as **MCP tools**, so a
non-technical teammate can use it from **Claude Desktop, Cursor, or any
MCP-capable chat** — no CLI, no Python knowledge, just "which stocks are worth
buying?" in the chat box they already have open.

The governance split still holds: the chat model phrases the question and reads
the result back, but **every verdict comes from the deterministic engine** —
each tool returns the evidence trail (criteria met/failed, with the numbers),
never a bare opinion.

## Tools

| Tool | What it returns |
|---|---|
| `screen_watchlist()` | The whole watchlist ranked, each name with its BUY/WATCH/PASS verdict, conviction, and the 3-criterion evidence checklist |
| `analyze_ticker(ticker)` | One name's full decision: verdict + evidence trail + fair-value numbers + timing lens |
| `floor_signals(ticker)` | The 4 timing signals (LinReg channel, Stochastic 14,5,3, MACD 8,17,9, price vs SMA50) + the convergence verdict |
| `price_option(ticker, strike, expiry_years, vol, rate, kind)` | Black-Scholes premium + delta |

## Install

The MCP SDK is **optional** — the rest of the repo (engine, tests, `ask` CLI)
never needs it. To serve:

```bash
pip install mcp
```

## Claude Desktop

Add to `claude_desktop_config.json` (macOS:
`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "invest-open": {
      "command": "python3",
      "args": ["/absolute/path/to/invest-open/adapters/mcp/server.py"]
    }
  }
}
```

Restart Claude Desktop, then ask in plain language — e.g. *"screen the
watchlist and tell me which names pass all three criteria"*. The model will
call `screen_watchlist` and read back the engine's verdicts and evidence.

## Cursor / other MCP clients

Any client that speaks MCP over stdio uses the same command:

```jsonc
// .cursor/mcp.json
{
  "mcpServers": {
    "invest-open": {
      "command": "python3",
      "args": ["/absolute/path/to/invest-open/adapters/mcp/server.py"]
    }
  }
}
```

## Notes

- Uses your `config.json` if present, else the bundled `config.example.json`
  (illustrative sample data) — point it at your team's watchlist via config,
  not code.
- The tool bodies are plain Python functions (tested directly, no SDK
  required); `FastMCP` is a thin wrapper behind a guarded import.
- Not investment advice.
