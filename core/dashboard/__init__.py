"""Verdict-first decision dashboard — static HTML from the engine's decision
objects (VALUE + TIMING lenses). No server, no external requests, no LLM."""

from .render import render_dashboard, write_dashboard  # noqa: F401
