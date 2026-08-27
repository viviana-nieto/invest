"""Screen a watchlist deterministically by Payback Time and margin of safety.

Reads sample fundamentals (from config.example.json / config.json), runs the
valuation engine on each name, and ranks them. The ranking is pure math — the
same inputs always produce the same ordering, so the engine makes the call.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from .valuation import Valuation


def _defaults(cfg: dict) -> dict:
    """Pull global valuation assumptions from the config's skill block."""
    skill = cfg.get("skill", {})
    cap = skill.get("valuation_growth_cap")
    if not isinstance(cap, (int, float)) or isinstance(cap, bool) or cap <= 0:
        # A non-finite / non-positive / absent cap means "don't cap".
        cap = math.inf
    return {
        "years": skill.get("projection_years", 10),
        "required_return": skill.get("required_return", 0.15),
        "margin": skill.get("margin_of_safety", 0.50),
        "default_future_pe": skill.get("default_future_pe", 15.0),
        "default_growth": skill.get("default_growth_rate", 0.0),
        "valuation_growth_cap": cap,
    }


def _resolve_growth(row: dict, d: dict) -> float:
    """Resolve a row's growth rate with the documented precedence.

    config manual override (`growth_rate` on the row — which live enrichment
    via `core.fundamentals` never touches, and fills with the computed
    operating-income CAGR when absent) > `skill.default_growth_rate` (0.0).
    """
    g = row.get("growth_rate")
    return g if isinstance(g, (int, float)) else d["default_growth"]


def valuation_from_row(row: dict, d: dict) -> Valuation:
    """Build a Valuation for one config row using the global defaults.

    The growth the valuation trusts is capped at `valuation_growth_cap`: a
    60%/yr grower compounded 10 years is 108x, which would mint an absurd
    sticker price — the cap keeps fair value sane. Only the sticker / payback /
    margin-of-safety math sees the capped rate; the row's own `growth_rate`
    (the true historical CAGR shown in the watchlist) is untouched.
    """
    return Valuation(
        ticker=row["ticker"],
        price=row["price"],
        eps=row["eps"],
        growth_rate=min(_resolve_growth(row, d), d["valuation_growth_cap"]),
        future_pe=row.get("future_pe", d["default_future_pe"]),
        years=d["years"],
        required_return=d["required_return"],
        margin=d["margin"],
    )


def valuations_from_config(cfg: dict) -> list[Valuation]:
    """Build a Valuation for every ticker in the config's watchlist."""
    d = _defaults(cfg)
    return [valuation_from_row(row, d)
            for row in cfg.get("skill", {}).get("watchlist", [])]


def screen(cfg: dict, sort_by: str = "margin_of_safety") -> list[dict]:
    """Rank the watchlist.

    Args:
        cfg: parsed config dict (must contain skill.watchlist).
        sort_by: "margin_of_safety" (default, descending — biggest discount first)
            or "payback_years" (ascending — shortest payback first).

    Returns:
        A list of valuation dicts, ranked.
    """
    vals = valuations_from_config(cfg)

    if sort_by == "payback_years":
        vals.sort(key=lambda v: v.payback_years)
    elif sort_by == "margin_of_safety":
        vals.sort(key=lambda v: v.margin_of_safety, reverse=True)
    else:
        raise ValueError("sort_by must be 'margin_of_safety' or 'payback_years'")

    return [v.to_dict() for v in vals]


def rank_by_conviction(cfg: dict) -> list[dict]:
    """Rank the whole universe by the decision engine's conviction score,
    descending — the ordering that drives the verdict-first dashboard.

    Each element is a full decision object (valuation verdict + evidence +
    timing lens), already sorted and stamped with a 1-based `rank`. Delegates to
    `core.decision.build_decisions` so the ranking lives in one place.
    """
    from .decision import build_decisions

    return build_decisions(cfg)


def load_config(path: str | Path) -> dict:
    """Load a config JSON file (config.json or config.example.json)."""
    return json.loads(Path(path).read_text())


def _resolve_config(explicit: str | None = None) -> Path:
    """Prefer an explicit path, then config.json, then config.example.json."""
    root = Path(__file__).resolve().parent.parent
    if explicit:
        return Path(explicit)
    live = root / "config.json"
    return live if live.exists() else root / "config.example.json"


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Screen a watchlist by Payback Time / margin of safety.")
    ap.add_argument("--config", help="Path to config JSON (defaults to config.json or config.example.json)")
    ap.add_argument("--sort", default="margin_of_safety",
                    choices=["margin_of_safety", "payback_years"])
    ap.add_argument("--decisions", action="store_true",
                    help="Emit full BUY/WATCH/PASS decision objects (evidence + "
                         "timing), ranked by conviction descending.")
    args = ap.parse_args(argv)

    cfg = load_config(_resolve_config(args.config))
    if args.decisions:
        print(json.dumps(rank_by_conviction(cfg), indent=2))
        return 0
    ranked = screen(cfg, sort_by=args.sort)
    print(json.dumps(ranked, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
