"""Growth-from-history: the operating-income CAGR methodology, tested offline.

`compute_growth` is pure math, so every rule of the shared methodology is
pinned here on synthetic series — full-window CAGR floored at 0, Turnaround /
Declining / Losses special cases, and the trailing `cagr_periods` windows.
The yfinance path is exercised through a fake module (no pandas, no network).
"""

import math

import pytest

from core import fundamentals as f
from core.fundamentals import compute_growth, earnings_cagr_growth, \
    enrich_config_with_live_growth


# ---------------------------------------------------------------------------
# The core CAGR rule
# ---------------------------------------------------------------------------

def test_cagr_reference_series():
    # [100, 150, 225] over 2 years: (225/100)^(1/2) - 1 = 0.5 exactly.
    g = compute_growth([100, 150, 225])
    assert g["growth_rate"] == pytest.approx(0.5)
    assert g["growth_label"] == "2yr CAGR"
    assert g["growth_years"] == 2


def test_cagr_uses_full_window_endpoints_only():
    # Only first/last matter: a dip in the middle doesn't change the CAGR.
    g = compute_growth([100, 10, 225])
    assert g["growth_rate"] == pytest.approx(0.5)


def test_declining_but_positive_floors_at_zero():
    # Both endpoints positive but shrinking: raw CAGR is negative, floored to 0.
    g = compute_growth([225, 150, 100])
    assert g["growth_rate"] == 0
    assert g["growth_label"] == "2yr CAGR"


def test_monotonic_decline_floors_at_zero():
    g = compute_growth([500, 400, 300, 200, 150])
    assert g["growth_rate"] == 0
    assert g["growth_years"] == 4


def test_ten_year_series_label_and_rate():
    values = [100 * 1.12 ** i for i in range(11)]  # 11 points = 10 years
    g = compute_growth(values)
    assert g["growth_rate"] == pytest.approx(0.12)
    assert g["growth_label"] == "10yr CAGR"
    assert g["growth_years"] == 10


# ---------------------------------------------------------------------------
# Special cases
# ---------------------------------------------------------------------------

def test_turnaround_uses_analyst_estimate():
    g = compute_growth([-10, 5], analyst_growth=0.12)
    assert g["growth_rate"] == pytest.approx(0.12)
    assert g["growth_label"] == "Turnaround"


def test_turnaround_without_analyst_is_zero():
    assert compute_growth([-10, 5])["growth_rate"] == 0
    assert compute_growth([-10, 5], analyst_growth=None)["growth_rate"] == 0


def test_turnaround_negative_analyst_is_zero():
    g = compute_growth([-10, 5], analyst_growth=-0.05)
    assert g["growth_rate"] == 0
    assert g["growth_label"] == "Turnaround"


def test_declining_into_losses():
    g = compute_growth([100, 50, -5])
    assert g["growth_rate"] == 0
    assert g["growth_label"] == "Declining"


def test_shrinking_losses_earn_reduction_rate():
    # -100 -> -50 over 1 year: 1 - (50/100)^(1/1) = 0.5
    g = compute_growth([-100, -50])
    assert g["growth_rate"] == pytest.approx(0.5)
    assert g["growth_label"].startswith("Losses")
    assert "50" in g["growth_label"]


def test_growing_losses_are_zero():
    g = compute_growth([-50, -100])
    assert g["growth_rate"] == 0
    assert g["growth_label"] == "Losses ↑"


def test_too_short_series_is_no_data():
    for values in (None, [], [100]):
        g = compute_growth(values)
        assert g["growth_rate"] is None
        assert g["growth_label"] is None
        assert g["cagr_periods"] == {}


# ---------------------------------------------------------------------------
# Trailing windows (cagr_periods)
# ---------------------------------------------------------------------------

def test_cagr_periods_windows():
    values = [100 * 1.10 ** i for i in range(11)]  # 10 years of 10% growth
    periods = compute_growth(values)["cagr_periods"]
    assert set(periods) == {"10yr", "7yr", "5yr", "3yr", "1yr"}
    for key in periods:
        assert periods[key] == pytest.approx(0.10)


def test_cagr_periods_short_series_has_none():
    periods = compute_growth([100, 150, 225])["cagr_periods"]
    assert periods["1yr"] == pytest.approx(0.5)
    assert periods["3yr"] is None
    assert periods["5yr"] is None
    assert periods["10yr"] is None


def test_cagr_periods_window_floors_and_skips_nonpositive():
    periods = compute_growth([200, 100, -10, 50])["cagr_periods"]
    assert periods["3yr"] == 0            # 200 -> 50 declining, floored at 0
    assert periods["1yr"] is None         # window starts at -10 (<= 0)


# ---------------------------------------------------------------------------
# yfinance path (fake module — no network, no pandas)
# ---------------------------------------------------------------------------

class _FakeSeries:
    def __init__(self, values):
        self._values = values

    def dropna(self):
        return _FakeSeries([v for v in self._values if v is not None])

    @property
    def values(self):
        return list(self._values)


class _FakeLoc:
    def __init__(self, rows):
        self._rows = rows

    def __getitem__(self, label):
        return _FakeSeries(self._rows[label])


class _FakeFrame:
    """Duck-types the slice of the pandas API that fetch_operating_income_yf uses.

    Rows are stored newest-first, matching yfinance's income_stmt columns.
    """

    def __init__(self, rows):
        self._rows = rows

    @property
    def empty(self):
        return not self._rows

    @property
    def index(self):
        return list(self._rows)

    @property
    def loc(self):
        return _FakeLoc(self._rows)


class _FakeTicker:
    def __init__(self, rows, info=None):
        self.income_stmt = _FakeFrame(rows)
        self.info = info or {}


class _FakeYF:
    def __init__(self, rows, info=None):
        self._rows, self._info = rows, info

    def Ticker(self, ticker):
        return _FakeTicker(self._rows, self._info)


@pytest.fixture
def offline_edgar(monkeypatch):
    """Force the EDGAR-preferred path to miss so yfinance is exercised."""
    monkeypatch.setattr(f, "fetch_operating_income_edgar", lambda t: None)


def test_earnings_cagr_growth_via_yfinance(monkeypatch, offline_edgar):
    # yfinance stores newest-first; [225, 150, 100] reversed -> [100, 150, 225].
    monkeypatch.setattr(f, "_yf", _FakeYF({"Operating Income": [225, 150, 100]}))
    monkeypatch.setattr(f, "_HAVE_YF", True)
    g = earnings_cagr_growth("TEST")
    assert g["growth_rate"] == pytest.approx(0.5)
    assert g["growth_label"] == "2yr CAGR"
    assert g["cagr_periods"]["1yr"] == pytest.approx(0.5)


def test_earnings_cagr_growth_prefers_edgar(monkeypatch):
    monkeypatch.setattr(f, "fetch_operating_income_edgar",
                        lambda t: [100 * 1.12 ** i for i in range(11)])
    monkeypatch.setattr(f, "_HAVE_YF", False)  # yfinance never needed
    g = earnings_cagr_growth("TEST")
    assert g["growth_rate"] == pytest.approx(0.12)
    assert g["growth_label"] == "10yr CAGR"


def test_yf_label_fallback_to_ebit(monkeypatch, offline_edgar):
    monkeypatch.setattr(f, "_yf", _FakeYF({"EBIT": [225, 150, 100]}))
    monkeypatch.setattr(f, "_HAVE_YF", True)
    assert earnings_cagr_growth("TEST")["growth_rate"] == pytest.approx(0.5)


def test_yf_turnaround_pulls_analyst(monkeypatch, offline_edgar):
    monkeypatch.setattr(
        f, "_yf",
        _FakeYF({"Operating Income": [5, -10]}, info={"earningsGrowth": 0.2}))
    monkeypatch.setattr(f, "_HAVE_YF", True)
    g = earnings_cagr_growth("TEST")
    assert g["growth_label"] == "Turnaround"
    assert g["growth_rate"] == pytest.approx(0.2)


def test_offline_yields_no_data(monkeypatch, offline_edgar):
    monkeypatch.setattr(f, "_HAVE_YF", False)
    g = earnings_cagr_growth("TEST")
    assert g["growth_rate"] is None


# ---------------------------------------------------------------------------
# Precedence: config override > computed CAGR > default
# ---------------------------------------------------------------------------

def _cfg(rows, **skill_extra):
    skill = {"watchlist": rows}
    skill.update(skill_extra)
    return {"skill": skill}


def test_manual_override_wins(monkeypatch):
    monkeypatch.setattr(f, "earnings_cagr_growth",
                        lambda t: compute_growth([100, 150, 225]))
    cfg = _cfg([{"ticker": "AAA", "growth_rate": 0.07}])
    enrich_config_with_live_growth(cfg)
    assert cfg["skill"]["watchlist"][0]["growth_rate"] == 0.07  # untouched


def test_computed_cagr_fills_missing_growth(monkeypatch):
    monkeypatch.setattr(f, "earnings_cagr_growth",
                        lambda t: compute_growth([100, 150, 225]))
    cfg = _cfg([{"ticker": "AAA"}])
    row = enrich_config_with_live_growth(cfg)["skill"]["watchlist"][0]
    assert row["growth_rate"] == pytest.approx(0.5)
    assert row["growth_label"] == "2yr CAGR"
    assert row["growth_years"] == 2


def test_default_when_no_data(monkeypatch):
    monkeypatch.setattr(f, "earnings_cagr_growth", lambda t: compute_growth(None))
    cfg = _cfg([{"ticker": "AAA"}])
    row = enrich_config_with_live_growth(cfg)["skill"]["watchlist"][0]
    assert row["growth_rate"] == 0.0
    assert row["growth_label"] == "default (no data)"


def test_default_is_configurable(monkeypatch):
    monkeypatch.setattr(f, "earnings_cagr_growth", lambda t: compute_growth(None))
    cfg = _cfg([{"ticker": "AAA"}], default_growth_rate=0.05)
    row = enrich_config_with_live_growth(cfg)["skill"]["watchlist"][0]
    assert row["growth_rate"] == 0.05


def test_screen_resolves_missing_growth_to_default():
    from core.screen import _defaults, _resolve_growth

    cfg = _cfg([])
    d = _defaults(cfg)
    assert _resolve_growth({"ticker": "AAA", "growth_rate": 0.3}, d) == 0.3
    assert _resolve_growth({"ticker": "AAA"}, d) == 0.0
