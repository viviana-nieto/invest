"""Provider-agnostic agent runner.

Loads a prompt, sends it to whichever LLM `LLM_PROVIDER` selects, extracts and
validates JSON against a schema (retrying on invalid output), and can fan out
many prompts in parallel — the same orchestration pattern the Claude Code skill
uses, but portable to any LLM (including local Ollama).

CLI:
    LLM_PROVIDER=ollama python -m orchestration.run \
        --prompt orchestration/prompts/news_agent.txt \
        --schema orchestration/schema.json
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from providers import Provider, get_provider  # noqa: E402
from schema_validate import validate  # noqa: E402


class SchemaError(RuntimeError):
    """Raised when the LLM output never satisfies the schema after retries."""


def load_prompt(path: str | Path, **context) -> str:
    """Read a prompt file and substitute {{key}} placeholders.

    `date` defaults to today (local) so agent searches are timely.
    """
    context.setdefault("date", datetime.date.today().isoformat())
    text = Path(path).read_text()
    for key, value in context.items():
        text = text.replace(f"{{{{{key}}}}}", str(value))
    return text


def extract_json(text: str) -> dict:
    """Pull a JSON object out of an LLM response, tolerating markdown fences."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    if not fenced:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start != -1 and end != -1:
            candidate = candidate[start:end + 1]
    return json.loads(candidate)


def run_prompt(prompt: str, schema: dict | None, provider: Provider,
               retries: int = 2) -> dict:
    """Run one prompt, returning validated JSON. Retries on parse/schema failure."""
    last_err = ""
    attempt_prompt = prompt
    for _ in range(retries + 1):
        raw = provider.complete(attempt_prompt)
        try:
            data = extract_json(raw)
        except (json.JSONDecodeError, ValueError) as e:
            last_err = f"invalid JSON: {e}"
        else:
            errors = validate(data, schema) if schema else []
            if not errors:
                return data
            last_err = "; ".join(errors)
        # Nudge the model to fix its output on the next attempt.
        attempt_prompt = (
            f"{prompt}\n\nYour previous response was invalid ({last_err}). "
            "Return ONLY valid JSON matching the schema, no prose, no code fences."
        )
    raise SchemaError(f"output never satisfied the schema after {retries + 1} tries: {last_err}")


def run_parallel(tasks: list[dict], provider: Provider, retries: int = 2,
                 max_workers: int = 8) -> dict:
    """Fan out many prompts concurrently.

    tasks: [{"name": str, "prompt": str, "schema": dict|None}, ...]
    Returns {name: validated_result}. Exceptions propagate with the task name.
    """
    results: dict = {}

    def _one(task):
        return task["name"], run_prompt(task["prompt"], task.get("schema"), provider, retries)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for name, result in pool.map(_one, tasks):
            results[name] = result
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run a prompt on any LLM and validate its JSON.")
    ap.add_argument("--prompt", required=True, help="Path to a prompt file")
    ap.add_argument("--schema", help="Path to a JSON schema the output must satisfy")
    ap.add_argument("--provider", help="Override LLM_PROVIDER")
    args = ap.parse_args(argv)

    provider = get_provider(args.provider)
    schema = json.loads(Path(args.schema).read_text()) if args.schema else None
    result = run_prompt(load_prompt(args.prompt), schema, provider)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
