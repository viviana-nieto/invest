"""Vendored runner tests — mock provider returns schema-valid JSON.

No network, no API keys: LLM_PROVIDER=mock (or an explicit MockProvider) drives
the same parse + validate + retry loop the real providers use.
"""

import json
from pathlib import Path

import pytest

# `run` and `providers` are importable because conftest puts orchestration/ on the path.
import run
from providers import MockProvider, get_provider
from schema_validate import validate

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "orchestration" / "schema.json").read_text())

VALID_NEWS = {
    "date": "2025-01-01",
    "items": [
        {
            "ticker": "AAPL",
            "headline": "Quarterly earnings beat expectations",
            "summary": "Revenue and EPS came in above consensus.",
            "sentiment": "positive",
            "sources": ["https://example.com/a"],
        }
    ],
}


def test_mock_provider_returns_schema_valid_json():
    provider = MockProvider(VALID_NEWS)
    result = run.run_prompt("prompt", SCHEMA, provider)
    assert validate(result, SCHEMA) == []
    assert result["items"][0]["ticker"] == "AAPL"


def test_get_provider_mock_from_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("MOCK_RESPONSE", json.dumps(VALID_NEWS))
    provider = get_provider()
    assert isinstance(provider, MockProvider)
    result = run.run_prompt("prompt", SCHEMA, provider)
    assert result["date"] == "2025-01-01"


def test_extract_json_tolerates_code_fences():
    fenced = "Here you go:\n```json\n{\"date\": \"x\", \"items\": []}\n```\nthanks"
    data = run.extract_json(fenced)
    assert data == {"date": "x", "items": []}


def test_retry_then_succeed():
    # First call returns junk, second returns valid JSON.
    calls = {"n": 0}

    def responder(_prompt):
        calls["n"] += 1
        return "not json" if calls["n"] == 1 else json.dumps(VALID_NEWS)

    provider = MockProvider(responder)
    result = run.run_prompt("prompt", SCHEMA, provider, retries=2)
    assert result["items"][0]["sentiment"] == "positive"
    assert calls["n"] == 2


def test_schema_error_when_never_valid():
    provider = MockProvider("still not json")
    with pytest.raises(run.SchemaError):
        run.run_prompt("prompt", SCHEMA, provider, retries=1)


def test_run_parallel_fans_out():
    provider = MockProvider(VALID_NEWS)
    tasks = [
        {"name": "batch1", "prompt": "p1", "schema": SCHEMA},
        {"name": "batch2", "prompt": "p2", "schema": SCHEMA},
    ]
    results = run.run_parallel(tasks, provider)
    assert set(results) == {"batch1", "batch2"}
    assert all(validate(r, SCHEMA) == [] for r in results.values())


def test_load_prompt_substitutes_placeholders(tmp_path):
    p = tmp_path / "prompt.txt"
    p.write_text("tickers={{tickers}} date={{date}}")
    out = run.load_prompt(p, tickers="AAPL, MSFT")
    assert "AAPL, MSFT" in out
    assert "{{date}}" not in out  # date auto-filled
