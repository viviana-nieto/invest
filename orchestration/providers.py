"""Provider abstraction — run the same prompt on any LLM.

Selected by the LLM_PROVIDER env var: anthropic | openai | ollama | mock.
Vendor SDKs are imported lazily, so installing this package pulls in nothing.
The `mock` provider needs no network or key and is what the test suite uses.
"""

from __future__ import annotations

import json
import os
from typing import Callable


class Provider:
    """Base interface: turn a prompt string into a completion string."""

    def complete(self, prompt: str) -> str:  # pragma: no cover - interface
        raise NotImplementedError


class MockProvider(Provider):
    """Returns canned output. `responder` may be a str, a dict (JSON-encoded),
    or a callable(prompt) -> str. Defaults to the MOCK_RESPONSE env var."""

    def __init__(self, responder: str | dict | Callable[[str], str] | None = None):
        if responder is None:
            responder = os.environ.get("MOCK_RESPONSE", "{}")
        self.responder = responder

    def complete(self, prompt: str) -> str:
        r = self.responder
        if callable(r):
            return r(prompt)
        if isinstance(r, dict):
            return json.dumps(r)
        return str(r)


class AnthropicProvider(Provider):
    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

    def complete(self, prompt: str) -> str:  # pragma: no cover - needs network/key
        from anthropic import Anthropic

        client = Anthropic()  # reads ANTHROPIC_API_KEY
        msg = client.messages.create(
            model=self.model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in msg.content if block.type == "text")


class OpenAIProvider(Provider):
    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4o")

    def complete(self, prompt: str) -> str:  # pragma: no cover - needs network/key
        from openai import OpenAI

        client = OpenAI()  # reads OPENAI_API_KEY
        resp = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content or ""


class OllamaProvider(Provider):
    """Fully local, free. Requires `ollama serve` running."""

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("OLLAMA_MODEL", "llama3.1")
        self.host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    def complete(self, prompt: str) -> str:  # pragma: no cover - needs local server
        import urllib.request

        payload = json.dumps({"model": self.model, "prompt": prompt, "stream": False}).encode()
        req = urllib.request.Request(f"{self.host}/api/generate", data=payload,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())["response"]


_PROVIDERS = {
    "mock": MockProvider,
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "ollama": OllamaProvider,
}


def get_provider(name: str | None = None, **kwargs) -> Provider:
    name = (name or os.environ.get("LLM_PROVIDER", "anthropic")).lower()
    if name not in _PROVIDERS:
        raise ValueError(
            f"Unknown LLM_PROVIDER '{name}'. Choose one of: {', '.join(_PROVIDERS)}."
        )
    return _PROVIDERS[name](**kwargs)
