"""Sample-spread tests — the generated sample must be lively and deterministic.

The 9-name sample is shaped so the engine produces a real spread: at least one
BUY, at least one PASS, and at least one name that is BOTH a BUY and REACHING
FLOOR (a strong-tier timing read). Regeneration must be byte-identical.
"""

import json
from pathlib import Path

import pytest

from core import emit
from core.screen import load_config

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.example.json"


@pytest.fixture(scope="module")
def bundle():
    return emit.build_all(load_config(CONFIG))


def test_has_at_least_one_buy_and_one_pass(bundle):
    verdicts = [o["verdict"]["verdict"] for o in bundle["data"]]
    assert verdicts.count("BUY") >= 1
    assert verdicts.count("PASS") >= 1


def test_has_a_buy_that_is_reaching_floor(bundle):
    sigs = bundle["technicals"]["signals"]
    buys_on_floor = [
        o["ticker"] for o in bundle["data"]
        if o["verdict"]["verdict"] == "BUY" and sigs[o["ticker"]]["tier"] == "strong"
    ]
    assert buys_on_floor, "expected >=1 BUY that is also REACHING FLOOR (strong tier)"


def test_has_an_extended_name(bundle):
    # At least one name flagged extended (long-window channel position >= 0.66).
    sigs = bundle["technicals"]["signals"]
    assert any(s["channel_position_long"] >= 0.66 for s in sigs.values())


def test_sparklines_nonempty(bundle):
    for o in bundle["data"]:
        assert o["sparkline"] and all(isinstance(x, (int, float)) for x in o["sparkline"])


def test_regeneration_is_byte_identical(tmp_path):
    cfg = load_config(CONFIG)
    a = json.dumps(emit.build_all(cfg), sort_keys=True)
    b = json.dumps(emit.build_all(cfg), sort_keys=True)
    assert a == b
