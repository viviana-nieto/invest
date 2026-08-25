"""Plain-language front door — ask the engine a question in English.

    python3 -m orchestration.ask "which stocks are worth buying and why?"
    python3 -m orchestration.ask --no-llm "is AMZN reaching a floor?"
    python3 -m orchestration.ask "price a call on AAPL strike 230 expiring in 1 year"

The governance contract (the whole point):

    The LLM NEVER computes the answer. It only ROUTES — it maps the question to
    one of four deterministic tools (screen / analyze / signals / option) plus
    arguments, validated against a strict JSON schema. The `core/` engine then
    computes the verdict, and the answer always carries the evidence trail
    (criteria met/failed, with the numbers). Same question, same answer.

Routing has two paths:

  * Keyword router (default, zero-LLM) — a deterministic rule set. Used when no
    `LLM_PROVIDER` is configured, when `--no-llm` is passed, and by the tests.
  * LLM router — the vendored any-LLM runner (`LLM_PROVIDER` = anthropic /
    openai / ollama / mock) parses the question into the same intent JSON.
    If the model's output fails the schema, we fall back to the keyword router.

Either way the engine's output is identical: the router only picks WHICH
deterministic function runs, never WHAT it concludes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
# run.py / providers.py use flat local imports; mirror conftest/production setup.
for p in (str(_ROOT), str(_HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from core.decision import build_decisions  # noqa: E402
from core.options import price_option  # noqa: E402
from core.screen import _resolve_config, load_config  # noqa: E402

TOOLS = ("screen", "analyze", "signals", "option")

# The contract the router (LLM or keywords) must satisfy. The LLM's only job is
# to emit this JSON; anything else is rejected and the keyword router takes over.
INTENT_SCHEMA = {
    "type": "object",
    "required": ["tool", "args"],
    "properties": {
        "tool": {"type": "string"},
        "args": {"type": "object"},
    },
}

ROUTER_PROMPT = """\
You are a ROUTER for a deterministic stock-analysis engine. Your ONLY job is to
map the user's question to exactly one tool call. You must NOT answer the
question, give an opinion, or make any investment call — a deterministic engine
computes every answer.

Tools:
- "screen": rank the whole watchlist BUY/WATCH/PASS. args: {{}}
- "analyze": full decision + evidence for one stock. args: {{"ticker": "<SYMBOL>"}}
- "signals": floor/timing signals for one stock (is it reaching a floor, when to buy). args: {{"ticker": "<SYMBOL>"}}
- "option": Black-Scholes option pricing. args: {{"ticker": "<SYMBOL>", "strike": <number>, "expiry_years": <number>, "vol": <number 0-1>, "rate": <number 0-1>, "kind": "call"|"put"}}

Known watchlist tickers: {tickers}

Question: {question}

Return ONLY JSON, no prose: {{"tool": "...", "args": {{...}}}}
"""

_TICKER_STOPWORDS = {
    "I", "A", "AN", "THE", "IS", "IT", "ON", "AT", "IN", "TO", "OF", "OR",
    "AND", "BUY", "SELL", "PASS", "WATCH", "CALL", "PUT", "USD", "ETF",
    "PE", "EPS", "FCF", "OK", "VS", "SMA", "MACD", "LLM", "AI", "WHY", "WHAT",
}


# ---- config helpers ----------------------------------------------------------


def get_config(path: str | None = None) -> dict:
    """Load config.json (or config.example.json) exactly like core.screen."""
    return load_config(_resolve_config(path))


def known_tickers(cfg: dict) -> list[str]:
    return [row["ticker"] for row in cfg.get("skill", {}).get("watchlist", [])]


# ---- deterministic keyword router --------------------------------------------


def extract_ticker(question: str, known: list[str]) -> str | None:
    """Find a ticker in the question: watchlist symbols first (case-insensitive),
    then any all-caps 2-5 letter token that isn't a common word."""
    tokens = re.findall(r"[A-Za-z]{1,5}", question)
    for t in tokens:
        if t.upper() in known:
            return t.upper()
    for t in tokens:
        if t.isupper() and 2 <= len(t) <= 5 and t not in _TICKER_STOPWORDS:
            return t
    return None


def _num(pattern: str, text: str) -> float | None:
    m = re.search(pattern, text, re.IGNORECASE)
    return float(m.group(1)) if m else None


def _parse_option_args(question: str, ticker: str | None) -> dict:
    q = question
    strike = _num(r"strike\s*(?:of|at|price)?\s*\$?(\d+(?:\.\d+)?)", q)
    if strike is None:
        strike = _num(r"\$?(\d+(?:\.\d+)?)\s*strike", q)

    years = _num(r"(\d+(?:\.\d+)?)\s*(?:year|yr)s?", q)
    months = _num(r"(\d+(?:\.\d+)?)\s*(?:month|mo)s?", q)
    expiry_years = years if years is not None else (
        months / 12.0 if months is not None else 1.0)

    vol = _num(r"vol(?:atility)?\s*(?:of|at)?\s*(\d+(?:\.\d+)?)", q)
    if vol is None:
        vol = _num(r"(\d+(?:\.\d+)?)\s*%?\s*vol(?:atility)?", q)
    if vol is not None and vol > 1.0:
        vol /= 100.0
    rate = _num(r"rate\s*(?:of|at)?\s*(\d+(?:\.\d+)?)", q)
    if rate is None:
        rate = _num(r"(\d+(?:\.\d+)?)\s*%?\s*rate", q)
    if rate is not None and rate > 1.0:
        rate /= 100.0

    kind = "put" if re.search(r"\bputs?\b", q, re.IGNORECASE) else "call"
    args: dict = {"kind": kind, "expiry_years": expiry_years,
                  "vol": vol if vol is not None else 0.25,
                  "rate": rate if rate is not None else 0.04}
    if ticker:
        args["ticker"] = ticker
    if strike is not None:
        args["strike"] = strike
    return args


def route_keywords(question: str, known: list[str] | None = None) -> dict:
    """Deterministic rule-based router: question -> {"tool", "args"}.

    Precedence: option > signals/timing > single-name analyze > screen.
    Zero LLM — this is the path tests and `--no-llm` use.
    """
    known = known or []
    q = question.lower()
    ticker = extract_ticker(question, known)

    if re.search(r"\b(option|call|put|strike|premium|black.?scholes|delta)\b", q):
        return {"tool": "option", "args": _parse_option_args(question, ticker)}

    if re.search(r"\b(floor|timing|when|signal|signals|oversold|bottom|dip|entry)\b", q):
        args = {"ticker": ticker} if ticker else {}
        return {"tool": "signals", "args": args}

    if ticker:
        return {"tool": "analyze", "args": {"ticker": ticker}}

    # "what should I buy", "which stocks are worth buying", "screen", "rank"...
    return {"tool": "screen", "args": {}}


# ---- LLM router (routes only — never answers) ---------------------------------


def route_llm(question: str, known: list[str], provider=None) -> dict:
    """Ask the configured LLM to emit the intent JSON, schema-validated.

    Raises on any failure (bad JSON, wrong tool, provider error) so the caller
    can fall back to the deterministic keyword router.
    """
    import run as runner
    from providers import get_provider

    provider = provider or get_provider()
    prompt = ROUTER_PROMPT.format(tickers=", ".join(known) or "(none)",
                                  question=question)
    intent = runner.run_prompt(prompt, INTENT_SCHEMA, provider)
    if intent.get("tool") not in TOOLS:
        raise ValueError(f"router returned unknown tool: {intent.get('tool')!r}")
    intent.setdefault("args", {})
    return intent


def route(question: str, cfg: dict, use_llm: bool = False) -> tuple[dict, str]:
    """Return (intent, router_used). Falls back to keywords on any LLM failure."""
    known = known_tickers(cfg)
    if use_llm:
        try:
            return route_llm(question, known), "llm"
        except Exception:
            pass  # deterministic fallback below
    return route_keywords(question, known), "keywords"


# ---- dispatch: the deterministic engine computes the answer -------------------


def dispatch(intent: dict, cfg: dict) -> dict:
    """Run the routed core function. Pure engine — no LLM anywhere below here."""
    tool = intent["tool"]
    args = intent.get("args", {}) or {}
    known = known_tickers(cfg)

    if tool == "screen":
        return {"tool": "screen", "decisions": build_decisions(cfg)}

    if tool in ("analyze", "signals"):
        ticker = str(args.get("ticker", "")).upper()
        if ticker not in known:
            return {"tool": tool, "error":
                    f"unknown ticker {ticker or '(none)'} — watchlist has: "
                    + ", ".join(known)}
        decision = next(d for d in build_decisions(cfg) if d["ticker"] == ticker)
        return {"tool": tool, "decision": decision, "universe": len(known)}

    if tool == "option":
        ticker = str(args.get("ticker", "")).upper()
        row = next((r for r in cfg["skill"]["watchlist"]
                    if r["ticker"] == ticker), None)
        S = args.get("price") or (row["price"] if row else None)
        if S is None:
            return {"tool": "option", "error":
                    f"unknown ticker {ticker or '(none)'} and no price given — "
                    "watchlist has: " + ", ".join(known)}
        if args.get("strike") is None:
            return {"tool": "option", "error":
                    "no strike found — say e.g. 'price a call on "
                    f"{ticker or 'AAPL'} strike 230 expiring in 1 year'"}
        result = price_option(
            S=float(S), K=float(args["strike"]),
            T=float(args.get("expiry_years", 1.0)),
            r=float(args.get("rate", 0.04)),
            sigma=float(args.get("vol", 0.25)),
            kind=args.get("kind", "call"),
        )
        return {"tool": "option", "ticker": ticker, "option": result}

    return {"tool": tool, "error": f"unknown tool {tool!r}"}


# ---- evidence-backed formatting -----------------------------------------------


def _fmt_criteria_inline(criteria: list[dict]) -> str:
    return " · ".join(
        f"{'✓' if c['passed'] else '✗'} {c['name']} {c['value']} "
        f"(need {c['threshold']})" for c in criteria)


def _fmt_signals(timing: dict) -> list[str]:
    lines = [f"Timing: {timing['verdict']} ({timing['score']})"]
    for s in timing["signals"]:
        mark = "✓" if s["met"] else "✗"
        lines.append(f"  {mark} {s['name']}: {s['value']} — {s['detail']}")
    return lines


FOOTER = ("—\n⚙ engine decides · 🤖 agents narrate — every verdict above is "
          "deterministic arithmetic (same inputs, same answer); the LLM, when "
          "used at all, only routed your question. Not investment advice.")


def format_answer(result: dict, router: str = "keywords") -> str:
    """Turn the engine's structured result into an evidence-backed answer.

    Never a bare opinion: each verdict ships with the criteria met/failed and
    the numbers behind them.
    """
    if "error" in result:
        return f"Can't answer that yet: {result['error']}"

    tool = result["tool"]
    lines: list[str] = []

    if tool == "screen":
        ds = result["decisions"]
        lines.append(f"Watchlist screen — {len(ds)} names, ranked by conviction "
                     "(highest first). Verdict = 3 deterministic criteria:")
        for d in ds:
            v = d["valuation"]
            lines.append(
                f" #{d['rank']} {d['ticker']:<6} {v['verdict']:<5} "
                f"(conviction {v['conviction']})  "
                f"{_fmt_criteria_inline(v['criteria'])}  "
                f"| timing: {d['timing']['verdict']}")
        buys = [d["ticker"] for d in ds if d["valuation"]["verdict"] == "BUY"]
        lines.append(f"Worth buying by the engine's rules: "
                     f"{', '.join(buys) if buys else 'none today'} "
                     "(all 3 criteria passed).")

    elif tool == "analyze":
        d = result["decision"]
        v = d["valuation"]
        lines.append(f"{d['ticker']} — {d['name']} ({d['sector']}) @ ${d['price']:.2f}")
        lines.append(f"Verdict: {v['verdict']} (conviction {v['conviction']}, "
                     f"rank #{d['rank']} of {result['universe']})")
        lines.append("Evidence:")
        for c in v["criteria"]:
            mark = "✓" if c["passed"] else "✗"
            lines.append(f"  {mark} {c['name']}: {c['value']} (need {c['threshold']})")
        lines.append(f"Fair value (sticker): ${v['sticker_price']:.2f} · "
                     f"buy-below: ${v['buy_price']:.2f} · "
                     f"margin of safety {v['margin_of_safety'] * 100:+.0f}%")
        lines.extend(_fmt_signals(d["timing"]))

    elif tool == "signals":
        d = result["decision"]
        lines.append(f"{d['ticker']} — {d['name']} @ ${d['price']:.2f}")
        lines.extend(_fmt_signals(d["timing"]))
        lines.append("(REACHING FLOOR = 3+ of 4 conditions met; the convergence "
                     "is the call, computed — not judged.)")

    elif tool == "option":
        o = result["option"]
        lines.append(
            f"{result['ticker']} {o['kind']} — strike ${o['K']:.2f}, "
            f"expiry {o['T']:.2f}y, vol {o['sigma'] * 100:.0f}%, "
            f"rate {o['r'] * 100:.1f}% (underlying ${o['S']:.2f})")
        lines.append(f"Black-Scholes premium: ${o['premium']:.2f} · "
                     f"delta {o['delta']:+.2f}")
        lines.append("(Standard Black-Scholes-Merton, deterministic — "
                     "recompute it by hand and you'll get the same number.)")

    lines.append(f"[router: {router}]")
    lines.append(FOOTER)
    return "\n".join(lines)


# ---- public entry point --------------------------------------------------------


def ask(question: str, cfg: dict | None = None, use_llm: bool = False) -> str:
    """Answer a plain-English question with the deterministic engine."""
    cfg = cfg or get_config()
    intent, router = route(question, cfg, use_llm=use_llm)
    result = dispatch(intent, cfg)
    return format_answer(result, router=router)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Ask the deterministic investing engine a question in plain "
                    "English. The LLM (optional) only routes; the engine decides.")
    ap.add_argument("question", nargs="+", help="Your question, in plain language")
    ap.add_argument("--no-llm", action="store_true",
                    help="Force the deterministic keyword router (no model at all)")
    ap.add_argument("--config", help="Path to config JSON "
                    "(defaults to config.json or config.example.json)")
    ap.add_argument("--json", action="store_true",
                    help="Print the raw structured result instead of prose")
    args = ap.parse_args(argv)

    question = " ".join(args.question)
    cfg = get_config(args.config)
    # LLM routing is opt-in via LLM_PROVIDER; with no model configured (or
    # --no-llm) the deterministic keyword router handles everything.
    use_llm = (not args.no_llm) and bool(os.environ.get("LLM_PROVIDER"))

    if args.json:
        intent, router = route(question, cfg, use_llm=use_llm)
        result = dispatch(intent, cfg)
        result["router"] = router
        print(json.dumps(result, indent=2))
    else:
        print(ask(question, cfg, use_llm=use_llm))
    return 0


if __name__ == "__main__":
    sys.exit(main())
