"""Render the verdict-first decision dashboard as one self-contained HTML file.

Consumes the ranked decision objects from `core.decision.build_decisions` (each
carrying a VALUE lens — BUY/WATCH/PASS with an evidence checklist and an agent
narrative — and a TIMING lens — four floor signals + a convergence verdict) and
emits a single static page: inline CSS/JS, no external requests, works opened
directly as a file.

Design follows the dataviz status palette (good/warning/critical), and every
verdict pairs its color with an icon AND a text label — never color alone — so the
page reads for colorblind users and in forced-colors/print. The thesis is stated
in the header legend: the deterministic engine decides; the LLM agents only narrate.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

# Verdict -> (status role, icon, human label). Color is applied via the role class.
_VALUE_VERDICT = {
    "BUY":   ("good",     "▲", "BUY"),
    "WATCH": ("warning",  "◆", "WATCH"),
    "PASS":  ("critical", "▼", "PASS"),
}
_TIMING_VERDICT = {
    "REACHING FLOOR": ("good",     "▼", "REACHING FLOOR"),
    "NEUTRAL":        ("warning",  "—", "NEUTRAL"),
    "EXTENDED":       ("serious",  "▲", "EXTENDED"),
}


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def _check_icon(passed: bool) -> str:
    role = "good" if passed else "critical"
    mark = "✓" if passed else "✗"
    return f'<span class="mark {role}" aria-hidden="true">{mark}</span>'


def _criteria_html(criteria: list[dict]) -> str:
    rows = []
    for c in criteria:
        passed = bool(c["passed"])
        state = "Pass" if passed else "Fail"
        rows.append(f"""        <li class="crit {'ok' if passed else 'no'}">
          {_check_icon(passed)}
          <span class="crit-name">{_esc(c['name'])}</span>
          <span class="crit-val mono">{_esc(c['value'])}</span>
          <span class="crit-thr">need {_esc(c['threshold'])}</span>
          <span class="sr-only">{state}</span>
        </li>""")
    return "\n".join(rows)


def _signals_html(signals: list[dict]) -> str:
    rows = []
    for s in signals:
        met = bool(s["met"])
        dot = f'<span class="sig-dot {"met" if met else "unmet"}" aria-hidden="true"></span>'
        state = "met" if met else "not met"
        rows.append(f"""        <li class="sig {'met' if met else 'unmet'}">
          {dot}
          <span class="sig-name">{_esc(s['name'])}</span>
          <span class="sig-val mono">{_esc(s['value'])}</span>
          <span class="sig-detail">{_esc(s.get('detail', ''))}</span>
          <span class="sr-only">({state})</span>
        </li>""")
    return "\n".join(rows)


def _card_html(d: dict) -> str:
    v = d["valuation"]
    t = d["timing"]
    v_role, v_icon, v_label = _VALUE_VERDICT.get(v["verdict"], ("warning", "◆", v["verdict"]))
    t_role, t_icon, t_label = _TIMING_VERDICT.get(t["verdict"], ("warning", "—", t["verdict"]))
    conviction = int(v["conviction"])
    mos = v["margin_of_safety"] * 100.0

    return f"""    <article class="card">
      <header class="card-top">
        <div class="verdict {v_role}">
          <span class="v-icon" aria-hidden="true">{v_icon}</span>
          <span class="v-label">{v_label}</span>
        </div>
        <div class="idblock">
          <div class="idline">
            <span class="rank">#{d['rank']}</span>
            <span class="ticker mono">{_esc(d['ticker'])}</span>
            <span class="name">{_esc(d['name'])}</span>
          </div>
          <div class="meta">
            <span class="sector">{_esc(d['sector'])}</span>
            <span class="dot-sep">·</span>
            <span class="price mono">${d['price']:.2f}</span>
          </div>
        </div>
        <div class="conviction">
          <div class="conv-num mono">{conviction}</div>
          <div class="conv-label">conviction</div>
          <div class="conv-bar" role="img" aria-label="conviction {conviction} of 100">
            <span style="width:{conviction}%"></span>
          </div>
        </div>
      </header>

      <div class="lenses">
        <section class="lens value-lens">
          <h3 class="lens-title"><span class="engine-tag">⚙ engine</span> Value — what it's worth</h3>
          <ul class="criteria">
{_criteria_html(v['criteria'])}
          </ul>
          <div class="numbers mono">
            <span title="fair-value sticker">sticker ${v['sticker_price']:.2f}</span>
            <span title="margin-of-safety buy price">buy&nbsp;≤&nbsp;${v['buy_price']:.2f}</span>
            <span title="margin of safety">MoS {mos:+.0f}%</span>
          </div>
          <blockquote class="narrative">
            <span class="agent-tag">🤖 agent narrative</span>
            <p>{_esc(v['narrative'])}</p>
          </blockquote>
        </section>

        <section class="lens timing-lens">
          <h3 class="lens-title"><span class="engine-tag">⚙ engine</span> Timing — when to buy</h3>
          <div class="timing-verdict {t_role}">
            <span class="t-icon" aria-hidden="true">{t_icon}</span>
            <span class="t-label">{t_label}</span>
            <span class="t-score mono">{_esc(t['score'])}</span>
          </div>
          <ul class="signals">
{_signals_html(t['signals'])}
          </ul>
        </section>
      </div>
    </article>"""


def _summary_html(decisions: list[dict]) -> str:
    def count(pred):
        return sum(1 for d in decisions if pred(d))

    buys = count(lambda d: d["valuation"]["verdict"] == "BUY")
    watch = count(lambda d: d["valuation"]["verdict"] == "WATCH")
    pas = count(lambda d: d["valuation"]["verdict"] == "PASS")
    floors = count(lambda d: d["timing"]["verdict"] == "REACHING FLOOR")
    tiles = [
        ("good", "BUY", buys, "all 3 criteria pass"),
        ("warning", "WATCH", watch, "2 of 3 pass"),
        ("critical", "PASS", pas, "≤1 passes"),
        ("good", "REACHING FLOOR", floors, "≥3 of 4 floor signals"),
    ]
    cells = []
    for role, label, n, sub in tiles:
        cells.append(f"""      <div class="tile {role}">
        <div class="tile-n mono">{n}</div>
        <div class="tile-label">{label}</div>
        <div class="tile-sub">{sub}</div>
      </div>""")
    return "\n".join(cells)


def render_dashboard(decisions: list[dict], title: str = "Decision Dashboard",
                     subtitle: str = "") -> str:
    """Return a complete HTML document for the ranked decision objects."""
    data_json = json.dumps(decisions, indent=2)
    cards = "\n".join(_card_html(d) for d in decisions)
    summary = _summary_html(decisions)
    sub = subtitle or ("Deterministic value + timing engine — ranked by conviction. "
                       "The math makes the call; agents only narrate.")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>
  :root {{
    color-scheme: dark light;
    --surface-0: #111211;
    --surface-1: #1a1a19;
    --surface-2: #232322;
    --border:    #303030;
    --ink-0:     #ffffff;
    --ink-1:     #c3c2b7;
    --ink-2:     #8a897f;
    --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
    --good: #0ca30c; --good-bg: #0d2a12;
    --warning: #fab219; --warning-bg: #2c2408;
    --serious: #ec835a; --serious-bg: #2e1a10;
    --critical: #d03b3b; --critical-bg: #2c1113;
  }}
  @media (prefers-color-scheme: light) {{
    :root {{
      --surface-0: #f4f4f2; --surface-1: #fcfcfb; --surface-2: #ffffff;
      --border: #e3e2dd; --ink-0: #0b0b0b; --ink-1: #52514e; --ink-2: #86857e;
      --good-bg: #e4f4e4; --warning-bg: #fdf2d8; --serious-bg: #fbe9df; --critical-bg: #f8e2e2;
    }}
  }}
  :root[data-theme="dark"] {{
    color-scheme: dark;
    --surface-0:#111211; --surface-1:#1a1a19; --surface-2:#232322; --border:#303030;
    --ink-0:#fff; --ink-1:#c3c2b7; --ink-2:#8a897f;
    --good-bg:#0d2a12; --warning-bg:#2c2408; --serious-bg:#2e1a10; --critical-bg:#2c1113;
  }}
  :root[data-theme="light"] {{
    color-scheme: light;
    --surface-0:#f4f4f2; --surface-1:#fcfcfb; --surface-2:#fff; --border:#e3e2dd;
    --ink-0:#0b0b0b; --ink-1:#52514e; --ink-2:#86857e;
    --good-bg:#e4f4e4; --warning-bg:#fdf2d8; --serious-bg:#fbe9df; --critical-bg:#f8e2e2;
  }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    margin: 0; padding: clamp(1rem, 3vw, 2.5rem); background: var(--surface-0);
    color: var(--ink-1); line-height: 1.45; -webkit-font-smoothing: antialiased; }}
  .mono {{ font-family: var(--mono); font-variant-numeric: tabular-nums; }}
  .sr-only {{ position:absolute; width:1px; height:1px; padding:0; margin:-1px;
    overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }}
  .wrap {{ max-width: 1180px; margin: 0 auto; }}

  header.page {{ margin-bottom: 1.5rem; }}
  h1 {{ font-size: clamp(1.4rem, 2.4vw, 1.9rem); margin: 0 0 .3rem; color: var(--ink-0);
    letter-spacing: -.01em; }}
  .subtitle {{ color: var(--ink-2); font-size: .9rem; max-width: 60ch; }}

  .legend {{ display: flex; flex-wrap: wrap; gap: .5rem 1.2rem; margin: 1rem 0 0;
    padding: .7rem .9rem; background: var(--surface-1); border: 1px solid var(--border);
    border-radius: 10px; font-size: .8rem; }}
  .legend b {{ color: var(--ink-0); }}
  .legend .split {{ display:flex; align-items:center; gap:.45rem; }}
  .chip {{ font-size:.7rem; padding:.12rem .5rem; border-radius:999px; font-weight:700;
    border:1px solid var(--border); }}
  .chip.engine {{ color: var(--ink-0); background: var(--surface-2); }}
  .chip.agent {{ color: var(--ink-1); background: transparent; border-style: dashed; }}

  .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: .8rem; margin: 1.2rem 0 1.6rem; }}
  .tile {{ background: var(--surface-1); border: 1px solid var(--border);
    border-left-width: 4px; border-radius: 10px; padding: .8rem 1rem; }}
  .tile-n {{ font-size: 1.9rem; font-weight: 700; color: var(--ink-0); line-height: 1; }}
  .tile-label {{ font-size: .72rem; font-weight: 700; letter-spacing: .05em;
    text-transform: uppercase; margin-top: .35rem; }}
  .tile-sub {{ font-size: .72rem; color: var(--ink-2); margin-top: .15rem; }}
  .tile.good {{ border-left-color: var(--good); }} .tile.good .tile-label {{ color: var(--good); }}
  .tile.warning {{ border-left-color: var(--warning); }} .tile.warning .tile-label {{ color: var(--warning); }}
  .tile.critical {{ border-left-color: var(--critical); }} .tile.critical .tile-label {{ color: var(--critical); }}
  .tile.serious {{ border-left-color: var(--serious); }} .tile.serious .tile-label {{ color: var(--serious); }}

  .cards {{ display: flex; flex-direction: column; gap: 1rem; }}
  .card {{ background: var(--surface-1); border: 1px solid var(--border); border-radius: 14px;
    overflow: hidden; }}
  .card-top {{ display: grid; grid-template-columns: auto 1fr auto; gap: 1rem; align-items: center;
    padding: 1rem 1.2rem; border-bottom: 1px solid var(--border); background: var(--surface-2); }}

  .verdict {{ display: inline-flex; align-items: center; gap: .45rem; padding: .5rem .85rem;
    border-radius: 10px; font-weight: 800; font-size: .95rem; letter-spacing: .02em;
    border: 1px solid transparent; white-space: nowrap; }}
  .verdict .v-icon {{ font-size: .9rem; }}
  .verdict.good {{ color: var(--good); background: var(--good-bg); border-color: var(--good); }}
  .verdict.warning {{ color: var(--warning); background: var(--warning-bg); border-color: var(--warning); }}
  .verdict.critical {{ color: var(--critical); background: var(--critical-bg); border-color: var(--critical); }}

  .idline {{ display: flex; align-items: baseline; gap: .5rem; flex-wrap: wrap; }}
  .rank {{ color: var(--ink-2); font-size: .8rem; font-weight: 700; }}
  .ticker {{ font-size: 1.15rem; font-weight: 700; color: var(--ink-0); }}
  .name {{ color: var(--ink-1); font-size: .9rem; }}
  .meta {{ font-size: .78rem; color: var(--ink-2); margin-top: .15rem; }}
  .dot-sep {{ margin: 0 .35rem; }}
  .price {{ color: var(--ink-1); }}

  .conviction {{ text-align: right; min-width: 120px; }}
  .conv-num {{ font-size: 1.5rem; font-weight: 700; color: var(--ink-0); line-height: 1; }}
  .conv-label {{ font-size: .66rem; text-transform: uppercase; letter-spacing: .06em;
    color: var(--ink-2); margin-bottom: .35rem; }}
  .conv-bar {{ height: 6px; background: var(--surface-0); border: 1px solid var(--border);
    border-radius: 999px; overflow: hidden; }}
  .conv-bar span {{ display: block; height: 100%; background: linear-gradient(90deg, var(--ink-2), var(--ink-0)); }}

  .lenses {{ display: grid; grid-template-columns: 1fr 1fr; }}
  .lens {{ padding: 1rem 1.2rem; }}
  .value-lens {{ border-right: 1px solid var(--border); }}
  .lens-title {{ font-size: .8rem; font-weight: 700; color: var(--ink-1); margin: 0 0 .7rem;
    text-transform: uppercase; letter-spacing: .04em; display:flex; align-items:center; gap:.5rem; }}
  .engine-tag {{ font-size: .62rem; font-weight: 700; color: var(--ink-0); background: var(--surface-2);
    border: 1px solid var(--border); border-radius: 999px; padding: .1rem .45rem; letter-spacing: .03em; }}

  ul.criteria, ul.signals {{ list-style: none; margin: 0; padding: 0; display: flex;
    flex-direction: column; gap: .35rem; }}
  .crit, .sig {{ display: grid; grid-template-columns: 1.2rem 1fr auto; gap: .1rem .55rem;
    align-items: center; padding: .4rem .55rem; background: var(--surface-2);
    border: 1px solid var(--border); border-radius: 8px; }}
  .mark {{ font-weight: 900; font-size: .95rem; text-align: center; }}
  .mark.good {{ color: var(--good); }} .mark.critical {{ color: var(--critical); }}
  .crit-name, .sig-name {{ color: var(--ink-1); font-size: .84rem; font-weight: 600; }}
  .crit-val, .sig-val {{ color: var(--ink-0); font-size: .82rem; text-align: right; }}
  .crit-thr {{ grid-column: 2 / 4; color: var(--ink-2); font-size: .68rem; }}
  .sig-detail {{ grid-column: 2 / 4; color: var(--ink-2); font-size: .68rem; }}

  .sig-dot {{ width: .7rem; height: .7rem; border-radius: 50%; justify-self: center;
    border: 2px solid var(--ink-2); background: transparent; }}
  .sig-dot.met {{ background: var(--good); border-color: var(--good); }}
  .sig.met .sig-name {{ color: var(--ink-0); }}

  .numbers {{ display: flex; flex-wrap: wrap; gap: .3rem .9rem; margin: .7rem 0; font-size: .76rem;
    color: var(--ink-2); }}
  .numbers span {{ color: var(--ink-1); }}

  .narrative {{ margin: .6rem 0 0; padding: .65rem .8rem; background: var(--surface-0);
    border: 1px dashed var(--border); border-left: 3px solid var(--ink-2); border-radius: 8px; }}
  .agent-tag {{ display: inline-block; font-size: .64rem; font-weight: 700; letter-spacing: .04em;
    text-transform: uppercase; color: var(--ink-2); margin-bottom: .3rem; }}
  .narrative p {{ margin: 0; font-size: .84rem; font-style: italic; color: var(--ink-1); }}

  .timing-verdict {{ display: flex; align-items: center; gap: .5rem; padding: .5rem .7rem;
    border-radius: 9px; margin-bottom: .7rem; border: 1px solid transparent; font-size: .82rem; }}
  .timing-verdict .t-label {{ font-weight: 800; letter-spacing: .02em; }}
  .timing-verdict .t-score {{ margin-left: auto; font-size: .74rem; opacity: .85; }}
  .timing-verdict.good {{ color: var(--good); background: var(--good-bg); border-color: var(--good); }}
  .timing-verdict.warning {{ color: var(--warning); background: var(--warning-bg); border-color: var(--warning); }}
  .timing-verdict.serious {{ color: var(--serious); background: var(--serious-bg); border-color: var(--serious); }}

  footer {{ margin-top: 1.6rem; color: var(--ink-2); font-size: .74rem; }}
  footer code {{ background: var(--surface-1); padding: .1rem .35rem; border-radius: 4px; border: 1px solid var(--border); }}
  .theme-toggle {{ float: right; font: inherit; font-size: .74rem; color: var(--ink-1);
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px;
    padding: .3rem .7rem; cursor: pointer; }}

  @media (max-width: 720px) {{
    .card-top {{ grid-template-columns: auto 1fr; }}
    .conviction {{ grid-column: 1 / 3; text-align: left; }}
    .conv-label {{ margin-bottom: .2rem; }}
    .lenses {{ grid-template-columns: 1fr; }}
    .value-lens {{ border-right: none; border-bottom: 1px solid var(--border); }}
  }}
</style>
</head>
<body>
  <div class="wrap">
    <header class="page">
      <button class="theme-toggle" id="themeToggle" type="button">◐ theme</button>
      <h1>{_esc(title)}</h1>
      <div class="subtitle">{_esc(sub)}</div>
      <div class="legend">
        <span class="split"><span class="chip engine">⚙ Engine decides</span>
          <b>deterministic math</b> — every verdict &amp; rank is a pure function of the numbers.</span>
        <span class="split"><span class="chip agent">🤖 Agents narrate</span>
          <b>LLM</b> — writes the one-line story; it never casts a vote.</span>
      </div>
    </header>

    <div class="summary">
{summary}
    </div>

    <main class="cards">
{cards}
    </main>

    <footer>
      Two lenses of one decision loop: <b>Value</b> (Payback&nbsp;Time&nbsp;&lt;&nbsp;12y · Margin&nbsp;of&nbsp;Safety&nbsp;&gt;&nbsp;0 · positive&nbsp;FCF →
      BUY/WATCH/PASS) and <b>Timing</b> (LinReg&nbsp;channel · Stochastic&nbsp;14,5,3 · MACD&nbsp;8,17,9 · SMA&nbsp;50 →
      REACHING&nbsp;FLOOR/NEUTRAL/EXTENDED). Ranked by conviction. Sample data — not investment advice.
    </footer>
  </div>
  <script>
    (function () {{
      var btn = document.getElementById('themeToggle');
      var root = document.documentElement;
      btn && btn.addEventListener('click', function () {{
        var cur = root.getAttribute('data-theme');
        var next = cur === 'light' ? 'dark' : (cur === 'dark' ? 'light'
          : (matchMedia('(prefers-color-scheme: dark)').matches ? 'light' : 'dark'));
        root.setAttribute('data-theme', next);
      }});
    }})();
  </script>
  <script type="application/json" id="decision-data">
{data_json}
  </script>
</body>
</html>
"""


def write_dashboard(decisions: list[dict], out_path: str | Path,
                    title: str = "Decision Dashboard", subtitle: str = "") -> Path:
    """Render and write the dashboard HTML to `out_path`. Returns the path."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_dashboard(decisions, title, subtitle))
    return out
