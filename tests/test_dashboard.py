"""Dashboard render tests — the HTML must be verdict-first and self-contained.

Renders from sample decisions and asserts the page carries the verdict badges, at
least one BUY, the evidence-checklist markup, the timing signals, and the
deterministic/LLM legend that states the thesis.
"""

from pathlib import Path

import pytest

from core.dashboard import render_dashboard, write_dashboard
from core.screen import load_config, rank_by_conviction

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.example.json"


@pytest.fixture
def decisions():
    return rank_by_conviction(load_config(CONFIG))


@pytest.fixture
def htmldoc(decisions):
    return render_dashboard(decisions, title="Decision Dashboard")


def test_is_self_contained_html(htmldoc):
    assert htmldoc.lstrip().startswith("<!doctype html>")
    # No external requests: no http(s) asset links, no CDN.
    assert "http://" not in htmldoc and "https://" not in htmldoc
    assert "<link" not in htmldoc and "src=" not in htmldoc


def test_states_the_deterministic_vs_llm_thesis(htmldoc):
    # The header legend must make the engine/agent split explicit.
    assert "Engine decides" in htmldoc
    assert "Agents narrate" in htmldoc
    assert "deterministic" in htmldoc
    assert "⚙" in htmldoc and "🤖" in htmldoc


def test_has_verdict_badges_including_a_buy(htmldoc):
    assert 'class="verdict good"' in htmldoc   # a BUY badge (good == green)
    assert ">BUY<" in htmldoc
    # All three verdict states styled.
    assert 'class="verdict warning"' in htmldoc  # WATCH
    assert 'class="verdict critical"' in htmldoc  # PASS


def test_has_evidence_checklist(htmldoc):
    assert 'class="criteria"' in htmldoc
    assert "Payback Time" in htmldoc
    assert "Margin of Safety" in htmldoc
    assert "Free Cash Flow" in htmldoc
    assert "need &lt; 12y" in htmldoc  # threshold shown, html-escaped


def test_checklist_marks_pass_and_fail(htmldoc):
    assert "✓" in htmldoc and "✗" in htmldoc


def test_has_agent_narrative_box(htmldoc):
    assert 'class="narrative"' in htmldoc
    assert "agent narrative" in htmldoc


def test_has_timing_lens_with_all_four_signals(htmldoc):
    assert 'class="signals"' in htmldoc
    assert "LinReg Channel" in htmldoc
    assert "Stochastic 14,5,3" in htmldoc
    assert "MACD 8,17,9" in htmldoc
    assert "Price vs SMA50" in htmldoc
    # A convergence verdict and a floor score appear.
    assert "REACHING FLOOR" in htmldoc
    assert "floor conditions met" in htmldoc


def test_cards_are_ranked_in_order(htmldoc):
    # Rank #1 must appear before rank #2 in document order.
    assert htmldoc.index(">#1<") < htmldoc.index(">#2<")


def test_conviction_and_rank_present(htmldoc):
    assert "conviction" in htmldoc
    assert ">#1<" in htmldoc


def test_write_dashboard_roundtrips(decisions, tmp_path):
    out = write_dashboard(decisions, tmp_path / "d" / "index.html")
    assert out.exists()
    text = out.read_text()
    assert "<!doctype html>" in text
    assert ">BUY<" in text


# --- the multi-tab terminal (core/dashboard/index.html) ----------------------

import re
import shutil
import subprocess

INDEX = ROOT / "core" / "dashboard" / "index.html"


@pytest.fixture(scope="module")
def index_html():
    return INDEX.read_text()


def test_terminal_is_offline_no_external_http(index_html):
    # The bare file must render with zero external http(s) resources.
    assert "http://" not in index_html
    assert "https://" not in index_html


def test_terminal_has_all_six_tabs(index_html):
    for tab in ["watchlist", "screen", "signals", "options", "macro", "exploration"]:
        assert f'data-tab="{tab}"' in index_html


def test_terminal_has_engine_agent_legend(index_html):
    assert "⚙" in index_html and "🤖" in index_html
    assert "Engine decides" in index_html
    assert "Agents narrate" in index_html


def test_terminal_has_verdict_badges(index_html):
    # Badge classes are styled in CSS and emitted by the verdictBadge() helper.
    assert ".badge.buy" in index_html
    assert ".badge.watch" in index_html
    assert ".badge.pass" in index_html
    assert "verdictBadge" in index_html
    assert "BUY:" in index_html and "WATCH:" in index_html and "PASS:" in index_html


def test_terminal_has_signal_column_markup(index_html):
    # The signature St·M·MA cell + tier dots + extended warning.
    assert "signalInfo" in index_html
    assert "'St'" in index_html or '"St"' in index_html or ">St<" in index_html or "St " in index_html
    assert "🟢" in index_html and "🟡" in index_html and "⚪" in index_html
    assert "🔴" in index_html and "🟠" in index_html
    assert "⚠" in index_html  # extended warning
    assert "Signal" in index_html  # column header


def test_terminal_has_expandable_evidence_trail(index_html):
    assert "detailHTML" in index_html
    assert "criteria" in index_html


def test_terminal_ships_black_scholes_js(index_html):
    assert "bsCall" in index_html and "bsPut" in index_html and "bsDelta" in index_html


def test_terminal_js_black_scholes_matches_python_reference(index_html):
    """Extract the BS block and run it in node: call(100,100,1,.05,.2) ≈ 10.4506."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available for JS parity check")
    m = re.search(r"// ==BS_START==(.*?)// ==BS_END==", index_html, re.S)
    assert m, "BS markers not found in index.html"
    js = m.group(1) + "\nconsole.log(bsCall(100,100,1,0.05,0.2).toFixed(4));"
    out = subprocess.run([node, "-e", js], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    val = float(out.stdout.strip())
    assert abs(val - 10.4506) < 1e-3, f"JS BS call = {val}, expected 10.4506"
