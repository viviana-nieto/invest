"""CLI: build the verdict-first decision dashboard from the sample engine.

    python -m core.build_dashboard --out core/dashboard/index.html

Runs the deterministic decision engine over the config watchlist (both the VALUE
and TIMING lenses), ranks by conviction, and writes a self-contained HTML page.
"""

from __future__ import annotations

import argparse

from .dashboard import write_dashboard
from .screen import _resolve_config, load_config, rank_by_conviction


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the decision dashboard HTML.")
    ap.add_argument("--config", help="Path to config JSON")
    ap.add_argument("--out", default="core/dashboard/cards.html", help="Output HTML path")
    ap.add_argument("--title", default="Decision Dashboard", help="Page title")
    args = ap.parse_args(argv)

    cfg = load_config(_resolve_config(args.config))
    decisions = rank_by_conviction(cfg)
    path = write_dashboard(decisions, args.out, title=args.title)

    buys = sum(1 for d in decisions if d["valuation"]["verdict"] == "BUY")
    floors = sum(1 for d in decisions if d["timing"]["verdict"] == "REACHING FLOOR")
    print(f"wrote {path} ({len(decisions)} stocks · {buys} BUY · {floors} reaching floor)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
