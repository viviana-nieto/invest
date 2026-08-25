"""Access-layer tests: the plain-language `ask` front door.

Governance contract under test: the router (keywords or a mocked LLM) only
picks WHICH deterministic core function runs; the engine computes the answer,
and the formatted answer carries the evidence (criteria + numbers). Everything
here runs with zero network and zero keys.
"""

import json

import pytest

from orchestration.ask import (
    ask,
    dispatch,
    extract_ticker,
    get_config,
    known_tickers,
    main,
    route,
    route_keywords,
    route_llm,
)

CFG = get_config()
KNOWN = known_tickers(CFG)
# A ticker guaranteed to be on the configured watchlist, whatever the seed.
TICKER = KNOWN[0]
# A near-the-money strike for that name, so option asserts stay well-behaved.
STRIKE = int(round(next(r["price"] for r in CFG["skill"]["watchlist"]
                        if r["ticker"] == TICKER)))
# ...and a ticker guaranteed NOT to be on the watchlist.
ABSENT = "ZZZZ"
assert ABSENT not in KNOWN


# ---- deterministic keyword router ------------------------------------------------


@pytest.mark.parametrize("question,tool", [
    ("what should I buy?", "screen"),
    ("which stocks are worth buying and why?", "screen"),
    ("screen the watchlist", "screen"),
    ("rank the universe", "screen"),
    ("analyze NVDA", "analyze"),
    ("what do you think about amzn?", "analyze"),
    ("is AMZN reaching a floor?", "signals"),
    ("when should I buy GOOGL?", "signals"),
    ("show me the timing signals for JPM", "signals"),
    ("price a call on AAPL strike 230 expiring in 1 year", "option"),
    ("what's a put on MSFT with a 400 strike worth?", "option"),
])
def test_keyword_router_maps_questions_to_tools(question, tool):
    intent = route_keywords(question, KNOWN)
    assert intent["tool"] == tool


def test_keyword_router_extracts_args():
    intent = route_keywords("analyze NVDA", KNOWN)
    assert intent["args"]["ticker"] == "NVDA"

    intent = route_keywords("is AMZN reaching a floor?", KNOWN)
    assert intent["args"]["ticker"] == "AMZN"

    intent = route_keywords(
        "price a call on AAPL strike 230 expiring in 6 months at 30% vol", KNOWN)
    args = intent["args"]
    assert args["ticker"] == "AAPL"
    assert args["strike"] == 230.0
    assert args["expiry_years"] == pytest.approx(0.5)
    assert args["vol"] == pytest.approx(0.30)
    assert args["kind"] == "call"

    intent = route_keywords("what's a put on MSFT strike 400?", KNOWN)
    assert intent["args"]["kind"] == "put"
    assert intent["args"]["strike"] == 400.0


def test_keyword_router_is_deterministic():
    q = "which stocks are worth buying and why?"
    assert route_keywords(q, KNOWN) == route_keywords(q, KNOWN)


def test_extract_ticker_case_insensitive_and_stopword_safe():
    assert extract_ticker("tell me about nvda", KNOWN) == "NVDA"
    # "I" and "BUY" must never be read as tickers.
    assert extract_ticker("what should I BUY today", KNOWN) is None


# ---- mock-LLM router: the model routes, the engine answers ------------------------


def test_llm_router_mock_provider_returns_valid_intent(monkeypatch):
    from providers import MockProvider

    provider = MockProvider({"tool": "analyze", "args": {"ticker": "NVDA"}})
    intent = route_llm("what's the story with nvidia?", KNOWN, provider=provider)
    assert intent == {"tool": "analyze", "args": {"ticker": "NVDA"}}

    # ...and the intent dispatches to the deterministic core function.
    result = dispatch(intent, CFG)
    assert result["tool"] == "analyze"
    assert result["decision"]["ticker"] == "NVDA"
    assert result["decision"]["valuation"]["verdict"] in ("BUY", "WATCH", "PASS")


def test_llm_router_rejects_unknown_tool():
    from providers import MockProvider

    provider = MockProvider({"tool": "yolo_trade", "args": {}})
    with pytest.raises(Exception):
        route_llm("buy everything", KNOWN, provider=provider)


def test_route_falls_back_to_keywords_when_llm_fails(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("MOCK_RESPONSE", "not json at all")
    intent, router = route("analyze NVDA", CFG, use_llm=True)
    assert router == "keywords"
    assert intent == {"tool": "analyze", "args": {"ticker": "NVDA"}}


def test_ask_end_to_end_with_mock_llm(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv(
        "MOCK_RESPONSE", json.dumps({"tool": "signals", "args": {"ticker": "AMZN"}}))
    answer = ask("is amazon near a bottom?", CFG, use_llm=True)
    assert "AMZN" in answer
    assert "floor conditions met" in answer
    assert "[router: llm]" in answer


# ---- the engine decides; the answer carries the evidence --------------------------


def test_screen_answer_contains_ranked_verdicts_and_evidence():
    answer = ask("which stocks are worth buying and why?", CFG, use_llm=False)
    assert "#1" in answer                       # ranked
    assert "Payback Time" in answer             # criteria named...
    assert "Margin of Safety" in answer
    assert "Free Cash Flow" in answer
    assert "✓" in answer and "✗" in answer      # ...with pass/fail marks
    assert "conviction" in answer
    for verdict in ("BUY", "WATCH", "PASS"):
        assert verdict in answer
    assert "engine decides" in answer           # governance footer


def test_analyze_answer_contains_numbers_and_thresholds():
    answer = ask("analyze NVDA", CFG, use_llm=False)
    assert "NVDA" in answer
    assert "Verdict:" in answer
    assert "need < 12y" in answer               # threshold shown with the number
    assert "margin of safety" in answer.lower()
    assert "sticker" in answer.lower()


def test_signals_answer_lists_all_four_signals():
    answer = ask(f"is {TICKER} reaching a floor?", CFG, use_llm=False)
    for name in ("LinReg Channel", "Stochastic 14,5,3", "MACD 8,17,9",
                 "Price vs SMA50"):
        assert name in answer
    assert "floor conditions met" in answer


def test_option_answer_contains_premium_and_delta():
    answer = ask(f"price a call on {TICKER} strike {STRIKE} expiring in 1 year",
                 CFG, use_llm=False)
    assert "premium" in answer
    assert "delta" in answer
    assert f"${STRIKE:.2f}" in answer           # the strike echoed back


def test_option_matches_core_black_scholes():
    from core.options import price_option as bs

    intent = route_keywords(
        f"price a call on {TICKER} strike {STRIKE} expiring in 1 year", KNOWN)
    result = dispatch(intent, CFG)
    row = next(r for r in CFG["skill"]["watchlist"] if r["ticker"] == TICKER)
    expected = bs(S=row["price"], K=float(STRIKE), T=1.0, r=0.04, sigma=0.25,
                  kind="call")
    assert result["option"]["premium"] == expected["premium"]
    assert result["option"]["delta"] == expected["delta"]


def test_unknown_ticker_gets_helpful_error():
    answer = ask(f"analyze {ABSENT}", CFG, use_llm=False)
    assert "unknown ticker" in answer
    for t in KNOWN:                             # lists what IS available
        assert t in answer


# ---- the --no-llm CLI path ---------------------------------------------------------


def test_cli_no_llm_smoke(capsys):
    rc = main(["--no-llm", "what should I buy?"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "#1" in out
    assert "Payback Time" in out
    assert "[router: keywords]" in out


def test_cli_ignores_llm_provider_when_no_llm(monkeypatch, capsys):
    # Even with a provider configured, --no-llm must stay fully deterministic.
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("MOCK_RESPONSE", json.dumps(
        {"tool": "option", "args": {"ticker": "AAPL", "strike": 1}}))
    rc = main(["--no-llm", "--json", "analyze", "MSFT"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["tool"] == "analyze"            # keyword route, not the mock's
    assert data["router"] == "keywords"
    assert data["decision"]["ticker"] == "MSFT"


def test_cli_json_screen_shape(capsys):
    rc = main(["--no-llm", "--json", "screen", "the", "watchlist"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["tool"] == "screen"
    assert len(data["decisions"]) == len(KNOWN)
    ranks = [d["rank"] for d in data["decisions"]]
    assert ranks == sorted(ranks)
