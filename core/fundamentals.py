"""Live growth derivation: historical operating-income CAGR (guarded, offline-safe).

The engine's `growth_rate` input is not a guess — when live data is available it
is derived from the company's **annual operating-income (EBIT) history**:

1. Build the annual operating-income series, oldest → newest, capped at the
   last 10 fiscal years. SEC EDGAR is preferred (10+ years of 10-K filings);
   yfinance's `income_stmt` is the fallback (~4 years).
2. ``growth_rate = max(0, (last / first) ** (1 / n) - 1)`` where
   ``n = len(series) - 1`` — the full-window CAGR, floored at 0 so a shrinking
   business never gets negative "growth" projected forward.
3. Special cases:
   - first <= 0 < last  → **Turnaround**: the historical CAGR is undefined, so
     use the analyst forward estimate (yfinance ``info["earningsGrowth"]``) if
     it is positive, else 0.
   - first > 0 >= last  → **Declining**: 0.
   - both <= 0          → shrinking losses earn their annual loss-reduction
     rate; growing losses get 0.
4. ``cagr_periods`` reports the same floored CAGR over trailing 10/7/5/3/1-year
   windows (None where the series is too short or an endpoint is <= 0).

Precedence when the skill resolves a row's growth (see
``enrich_config_with_live_growth``):

    config manual override  >  computed historical CAGR  >  documented default

A numeric ``growth_rate`` on a watchlist row is an explicit manual override and
always wins. Rows that omit it get the computed CAGR when live data is
available, else ``skill.default_growth_rate`` (default ``0.0`` — conservative:
no evidence of growth means none is projected).

Everything network-touching is guarded: with no yfinance and no network the
module imports cleanly and the pure math (``compute_growth``) still runs, so
the offline sample path is unaffected.
"""

from __future__ import annotations

import json
import os
import urllib.request

try:  # optional dependency; the engine works without it
    import yfinance as _yf
    _HAVE_YF = True
except Exception:  # pragma: no cover - depends on the environment
    _yf = None
    _HAVE_YF = False

#: Growth used when a row has no manual override and no live data could be
#: computed. Conservative by design; override via ``skill.default_growth_rate``.
DEFAULT_GROWTH_RATE = 0.0

# SEC EDGAR: free historical XBRL data, no API key. EDGAR requires a
# descriptive "name contact-email" User-Agent identifying the client, or it
# returns 403 (https://www.sec.gov/os/accessing-edgar-data). Bring your own:
# set SEC_EDGAR_USER_AGENT="Your Name your@email.com". The placeholder below is
# only so the module imports; it will be rejected by SEC until you set yours.
_SEC_HEADERS = {
    "User-Agent": os.environ.get(
        "SEC_EDGAR_USER_AGENT", "invest-open-skill set-your-own@example.com"
    )
}
_sec_ticker_map: dict | None = None


def _empty_growth() -> dict:
    return {"growth_rate": None, "growth_label": None,
            "growth_years": None, "cagr_periods": {}}


def compute_growth(values: list[float] | None,
                   analyst_growth: float | None = None) -> dict:
    """Turn an annual operating-income series (oldest → newest) into a growth dict.

    Pure math — no network, no yfinance. Implements the shared methodology
    documented in the module docstring, byte-for-byte compatible with the
    reference dashboard implementation.

    Args:
        values: annual operating income, oldest first. Fewer than 2 points
            yields the empty result (caller falls back to the default).
        analyst_growth: forward analyst estimate, used only for Turnarounds.

    Returns:
        {"growth_rate", "growth_label", "growth_years", "cagr_periods"}.
    """
    if not values or len(values) < 2:
        return _empty_growth()

    first, last = values[0], values[-1]
    n_years = len(values) - 1

    if first > 0 and last > 0:
        cagr = (last / first) ** (1 / n_years) - 1
        growth_rate = max(0, cagr)
        growth_label = f"{n_years}yr CAGR"
    elif first <= 0 and last > 0:
        # Turnaround: historical CAGR undefined; lean on the analyst estimate.
        if analyst_growth and analyst_growth > 0:
            growth_rate = analyst_growth
        else:
            growth_rate = 0
        growth_label = "Turnaround"
    elif first > 0 and last <= 0:
        growth_rate = 0
        growth_label = "Declining"
    else:  # both <= 0
        loss_reduction = (abs(first) - abs(last)) / abs(first)
        if loss_reduction > 0:
            annual_reduction = 1 - (abs(last) / abs(first)) ** (1 / n_years)
            growth_rate = annual_reduction
            growth_label = f"Losses ↓{annual_reduction * 100:.0f}%/yr"
        else:
            growth_rate = 0
            growth_label = "Losses ↑"

    cagr_periods: dict[str, float | None] = {}
    for yrs in [10, 7, 5, 3, 1]:
        if len(values) >= yrs + 1:
            p_first = values[-(yrs + 1)]
            p_last = values[-1]
            if p_first > 0 and p_last > 0:
                cagr_periods[f"{yrs}yr"] = max(0, (p_last / p_first) ** (1 / yrs) - 1)
            else:
                cagr_periods[f"{yrs}yr"] = None
        else:
            cagr_periods[f"{yrs}yr"] = None

    return {"growth_rate": growth_rate, "growth_label": growth_label,
            "growth_years": n_years, "cagr_periods": cagr_periods}


# ---------------------------------------------------------------------------
# SEC EDGAR (preferred source: 10+ years of annual 10-K operating income)
# ---------------------------------------------------------------------------

def _sec_get_json(url: str):  # pragma: no cover - network
    req = urllib.request.Request(url, headers=_SEC_HEADERS)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_sec_cik(ticker: str) -> str | None:  # pragma: no cover - network
    """Map a ticker to its zero-padded CIK via SEC's public ticker file."""
    global _sec_ticker_map
    if _sec_ticker_map is None:
        try:
            data = _sec_get_json("https://www.sec.gov/files/company_tickers.json")
            _sec_ticker_map = {v["ticker"]: str(v["cik_str"]).zfill(10)
                               for v in data.values()}
        except Exception:
            _sec_ticker_map = {}
    return _sec_ticker_map.get(ticker.upper())


# XBRL concepts to try, in order: US filers (10-K, us-gaap) first, then
# foreign private issuers (20-F, ifrs-full).
_EDGAR_CONCEPTS = [
    ("us-gaap", "OperatingIncomeLoss", "10-K"),
    ("us-gaap",
     "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
     "10-K"),
    ("ifrs-full", "ProfitLossFromOperatingActivities", "20-F"),
    ("ifrs-full", "ProfitLoss", "20-F"),
]


def _extract_annual_values(data: dict, form: str) -> list[float] | None:
    """Deduplicated annual values from a companyconcept payload, oldest first."""
    for entries in data.get("units", {}).values():
        annual = [e for e in entries
                  if e.get("form") == form and e.get("fp") == "FY"]
        if not annual:
            continue
        annual.sort(key=lambda x: x["end"])
        seen: set[str] = set()
        unique: list[float] = []
        for item in annual:
            if item["end"] not in seen:
                seen.add(item["end"])
                unique.append(float(item["val"]))
        if len(unique) >= 2:
            return unique
    return None


def fetch_operating_income_edgar(ticker: str) -> list[float] | None:  # pragma: no cover - network
    """Annual operating income (oldest → newest, last 10) from SEC EDGAR.

    Uses the `companyconcept` endpoint, trying `us-gaap/OperatingIncomeLoss`
    (annual 10-K facts) first and falling back through pre-tax income and the
    IFRS operating-profit concepts (20-F) for foreign private issuers. Returns
    None for non-SEC filers, missing concepts, or any network failure — the
    caller falls back to yfinance.
    """
    cik = _get_sec_cik(ticker)
    if not cik:
        return None
    for taxonomy, concept, form in _EDGAR_CONCEPTS:
        try:
            url = (f"https://data.sec.gov/api/xbrl/companyconcept/"
                   f"CIK{cik}/{taxonomy}/{concept}.json")
            data = _sec_get_json(url)
        except Exception:
            continue
        values = _extract_annual_values(data, form)
        if values:
            return values[-10:]
    return None


# ---------------------------------------------------------------------------
# yfinance fallback (~4 years of annual statements)
# ---------------------------------------------------------------------------

def fetch_operating_income_yf(ticker: str) -> list[float] | None:
    """Annual operating income (oldest → newest, last 10) from yfinance.

    Reads `Ticker.income_stmt`, taking the first available of
    "Operating Income", "EBIT", then "Net Income". Returns None when yfinance
    is missing, the fetch fails, or no usable row exists.
    """
    if not _HAVE_YF:
        return None
    try:
        inc = _yf.Ticker(ticker).income_stmt
    except Exception:
        return None
    if inc is None or getattr(inc, "empty", True):
        return None
    try:
        for label in ["Operating Income", "EBIT", "Net Income"]:
            if label in inc.index:
                row = inc.loc[label].dropna()
                values = [float(v) for v in list(row.values)[::-1]]
                return values[-10:]
    except Exception:
        return None
    return None


def fetch_analyst_growth(ticker: str) -> float | None:
    """Forward analyst earnings-growth estimate (used only for Turnarounds)."""
    if not _HAVE_YF:
        return None
    try:
        value = _yf.Ticker(ticker).info.get("earningsGrowth")
        return float(value) if value is not None else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# The live entry points
# ---------------------------------------------------------------------------

def earnings_cagr_growth(ticker: str) -> dict:
    """Compute a ticker's growth from its historical operating-income series.

    Source order: SEC EDGAR (longer history) then yfinance. The analyst
    estimate is fetched only when the series is a Turnaround (first <= 0 <
    last), where a historical CAGR is undefined.

    Returns {"growth_rate", "growth_label", "growth_years", "cagr_periods"};
    all values None/empty when no data source is available (offline).
    """
    values = fetch_operating_income_edgar(ticker)
    if not values or len(values) < 2:
        values = fetch_operating_income_yf(ticker)

    analyst = None
    if values and len(values) >= 2 and values[0] <= 0 < values[-1]:
        analyst = fetch_analyst_growth(ticker)

    return compute_growth(values, analyst_growth=analyst)


def enrich_config_with_live_growth(cfg: dict) -> dict:
    """Fill in growth for watchlist rows that don't set it manually.

    Precedence per row (highest wins):
      1. A numeric ``growth_rate`` in the config — an explicit MANUAL OVERRIDE,
         never touched.
      2. The computed historical operating-income CAGR (``earnings_cagr_growth``),
         which also stamps ``growth_label`` / ``growth_years`` / ``cagr_periods``
         onto the row for display.
      3. ``skill.default_growth_rate`` (default 0.0) with label
         ``"default (no data)"`` — the documented offline/no-data fallback.

    Returns the same cfg object (mutated), mirroring
    ``core.fetch_prices.enrich_config_with_live_prices``.
    """
    skill = cfg.get("skill", {})
    default_growth = skill.get("default_growth_rate", DEFAULT_GROWTH_RATE)
    for row in skill.get("watchlist", []):
        if isinstance(row.get("growth_rate"), (int, float)):
            continue  # manual override wins
        computed = earnings_cagr_growth(row["ticker"])
        if computed["growth_rate"] is not None:
            row.update(computed)
        else:
            row["growth_rate"] = default_growth
            row["growth_label"] = "default (no data)"
    return cfg
