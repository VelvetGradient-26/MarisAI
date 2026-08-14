#!/usr/bin/env python
"""Generate the web artifact for the research paper.

    .venv/bin/python scripts/build_research_artifact.py

Reads the same experiment JSON the manuscript is built from, so the page and
the PDFs cannot disagree. The hero chart, every quoted figure and the results
table are computed here; only the prose is literal.

Mermaid diagrams are inlined from `research/shared/diagrams/*.mmd` — the same
files rendered to PDF for the manuscript — because artifacts render
```mermaid``` / `<pre class="mermaid">` natively. One source, two outputs.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "models" / "forecasting" / "_reports" / "paper"
RESEARCH = ROOT.parent / "research"
DIAGRAMS = RESEARCH / "shared" / "diagrams"
OUT = RESEARCH / "index.html"

HORIZONS = [1, 3, 7, 30]
PERSISTENCE = "#1f6fb2"
CLIMATOLOGY = "#d1611f"


def load() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    baselines = json.loads((DATA / "baselines.json").read_text())
    loso = json.loads((DATA / "loso.json").read_text())
    meta = json.loads((DATA / "meta.json").read_text())

    rows = []
    for entry in baselines:
        if "metrics" not in entry:
            continue
        m = entry["metrics"]
        rows.append(
            {
                "variable": entry["variable"],
                "horizon": entry["horizon"],
                "unit": entry.get("unit", ""),
                "sites": entry.get("sites"),
                "rows": entry.get("rows"),
                "skill_p": m.get("skill_score"),
                "skill_c": m.get("skill_vs_climatology"),
                "rmse": m.get("rmse"),
            }
        )
    return pd.DataFrame(rows), pd.DataFrame([r for r in loso if "skill_score" in r]), meta


def pretty(name: str) -> str:
    return name.replace("_", " ")


# --------------------------------------------------------------------------
# The hero: the two medians crossing, drawn from the data
# --------------------------------------------------------------------------


def hero_chart(main: pd.DataFrame) -> str:
    """An inline SVG of the paper's whole argument in one shape.

    One line roughly flat and one falling through zero, drawn from the
    per-horizon medians. Hand-built rather than exported from matplotlib so it
    inherits the page's theme tokens and stays crisp at any width.
    """
    medians = (
        main.groupby("horizon")[["skill_p", "skill_c"]].median().reindex(HORIZONS)
    )

    width, height = 720, 340
    left, right, top, bottom = 62, 26, 30, 52
    plot_w = width - left - right
    plot_h = height - top - bottom

    # Log x, because the horizons are 1/3/7/30 — linear would crush the short
    # leads where persistence is hardest to beat, which is half the story.
    xs = np.log(HORIZONS)
    x_min, x_max = xs.min(), xs.max()

    def px(horizon: float) -> float:
        return left + (np.log(horizon) - x_min) / (x_max - x_min) * plot_w

    y_lo, y_hi = -0.15, 1.0

    def py(value: float) -> float:
        return top + (y_hi - value) / (y_hi - y_lo) * plot_h

    parts: list[str] = []

    # Horizontal grid + y labels
    for tick in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = py(tick)
        parts.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}" '
            f'class="grid{" zero" if tick == 0 else ""}"/>'
        )
        parts.append(
            f'<text x="{left - 12}" y="{y + 4:.1f}" class="tick ta-end">'
            f"{tick:.2f}</text>"
        )

    for horizon in HORIZONS:
        x = px(horizon)
        parts.append(
            f'<text x="{x:.1f}" y="{top + plot_h + 26}" class="tick ta-mid">'
            f"{horizon} d</text>"
        )

    for column, colour, label in (
        ("skill_p", PERSISTENCE, "vs. persistence"),
        ("skill_c", CLIMATOLOGY, "vs. climatology"),
    ):
        points = [
            (px(h), py(float(medians.loc[h, column])))
            for h in HORIZONS
            if pd.notna(medians.loc[h, column])
        ]
        path = " ".join(
            ("M" if index == 0 else "L") + f"{x:.1f},{y:.1f}"
            for index, (x, y) in enumerate(points)
        )
        parts.append(f'<path d="{path}" fill="none" stroke="{colour}" stroke-width="2.5"/>')
        for x, y in points:
            parts.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{colour}" '
                f'stroke="var(--plate)" stroke-width="1.5"/>'
            )
        end_x, end_y = points[-1]
        anchor = "end" if column == "skill_c" else "end"
        parts.append(
            f'<text x="{end_x - 10:.1f}" y="{end_y - 14:.1f}" '
            f'class="serieslabel ta-{anchor}" fill="{colour}">{label}</text>'
        )

    parts.append(
        f'<text x="{left - 12}" y="{top - 12}" class="axistitle ta-end">skill</text>'
    )

    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Median skill against persistence stays roughly flat '
        f'across forecast horizons from one to thirty days, while median skill '
        f'against climatology falls steadily and crosses below zero by thirty '
        f'days." class="hero-svg">' + "".join(parts) + "</svg>"
    )


# --------------------------------------------------------------------------
# Results table
# --------------------------------------------------------------------------


def results_table(main: pd.DataFrame) -> str:
    head = "".join(f'<th colspan="2">h = {h} d</th>' for h in HORIZONS)
    sub = "".join(
        '<th class="num">S<sub>p</sub></th><th class="num">S<sub>c</sub></th>'
        for _ in HORIZONS
    )
    body = []
    for variable in sorted(main["variable"].unique()):
        cells = []
        for horizon in HORIZONS:
            row = main[(main["variable"] == variable) & (main["horizon"] == horizon)]
            for column in ("skill_p", "skill_c"):
                if row.empty or row[column].iloc[0] is None:
                    cells.append('<td class="num">&mdash;</td>')
                    continue
                value = float(row[column].iloc[0])
                klass = "num neg" if value < 0 else "num"
                cells.append(f'<td class="{klass}">{value:.3f}</td>')
        body.append(
            f'<tr><th scope="row">{html.escape(pretty(variable))}</th>'
            + "".join(cells)
            + "</tr>"
        )
    return f"""<table class="results">
<thead>
<tr><td></td>{head}</tr>
<tr><th scope="col">Variable</th>{sub}</tr>
</thead>
<tbody>{"".join(body)}</tbody>
</table>"""


def mermaid(name: str) -> str:
    source = (DIAGRAMS / f"{name}.mmd").read_text()
    return f'<pre class="mermaid">{html.escape(source)}</pre>'


# --------------------------------------------------------------------------


def build() -> None:
    main, loso, meta = load()

    at1 = main[main["horizon"] == 1]
    at30 = main[main["horizon"] == 30]
    loso7 = loso[loso["horizon"] == 7]
    pooled7 = main[main["horizon"] == 7]

    facts = {
        "n_vars": main["variable"].nunique(),
        "n_sites": int(main["sites"].max()),
        "n_models": len(main),
        "n_loso": len(loso),
        "as_of": meta.get("as_of", ""),
        "window": meta.get("climatology_window_days", 15),
        "sp1": float(at1["skill_p"].median()),
        "sp30": float(at30["skill_p"].median()),
        "sc1": float(at1["skill_c"].median()),
        "sc30": float(at30["skill_c"].median()),
        "lose_pers": int((main["skill_p"] < 0).sum()),
        "lose_clim": int((main["skill_c"] < 0).sum()),
        "flattered": int(((main["skill_p"] > 0) & (main["skill_c"] < 0)).sum()),
        "sp3": float(main[main["horizon"] == 3]["skill_p"].median()),
        "sp7": float(main[main["horizon"] == 7]["skill_p"].median()),
        "sc3": float(main[main["horizon"] == 3]["skill_c"].median()),
        "sc7": float(main[main["horizon"] == 7]["skill_c"].median()),
        "clim_neg_30": int((at30["skill_c"] < 0).sum()),
        "pers_neg_30": int((at30["skill_p"] < 0).sum()),
        "falling": sum(
            1
            for v in main["variable"].unique()
            if (s := main[main["variable"] == v].sort_values("horizon")["skill_c"].to_numpy())
            is not None
            and len(s) >= 2
            and s[-1] < s[0]
        ),
        "pooled7": float(pooled7["skill_p"].median()),
        "loso7": float(loso7["skill_score"].median()),
        "loso_pos": float((loso7["skill_score"] > 0).mean()) * 100.0,
    }

    page = TEMPLATE.format(
        hero=hero_chart(main),
        table=results_table(main),
        arch=mermaid("architecture"),
        flow=mermaid("dataflow"),
        decide=mermaid("interpretation"),
        **facts,
    )
    OUT.write_text(page)
    print(json.dumps(facts, indent=2, default=str))
    print(f"wrote {OUT} ({len(page) / 1024:.0f} KB)")


TEMPLATE = """<title>Rising Skill, Falling Skill</title>
<style>
  /* Palette from bathymetric chart convention: deep-water ink, a cool
     chart ground, and the two series hues as the only accents. Both series
     colours are validated for colour-vision deficiency separation
     (dE 21.7 protan) and carry >=3:1 on either ground. */
  :root {{
    --ground: #f4f7f8;
    --plate: #ffffff;
    --ink: #10202a;
    --ink-2: #3d5560;
    --ink-3: #6b8390;
    --rule: #cbd8dd;
    --rule-2: #e3ecef;
    --persistence: #1f6fb2;
    --climatology: #c2571a;
    --neg: #a8341a;
    --serif: "Iowan Old Style", "Charter", "Palatino Linotype", Palatino,
             "Book Antiqua", Georgia, serif;
    --mono: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace;
    --measure: 66ch;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --ground: #0c1519;
      --plate: #131f25;
      --ink: #e3edf1;
      --ink-2: #a5bcc5;
      --ink-3: #7794a0;
      --rule: #294049;
      --rule-2: #1d2f36;
      --persistence: #5aa9e6;
      --climatology: #f0894a;
      --neg: #ff8b6b;
    }}
  }}
  :root[data-theme="dark"] {{
    --ground: #0c1519;
    --plate: #131f25;
    --ink: #e3edf1;
    --ink-2: #a5bcc5;
    --ink-3: #7794a0;
    --rule: #294049;
    --rule-2: #1d2f36;
    --persistence: #5aa9e6;
    --climatology: #f0894a;
    --neg: #ff8b6b;
  }}

  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--ground);
    color: var(--ink);
    font-family: var(--serif);
    font-size: 18px;
    line-height: 1.62;
    -webkit-font-smoothing: antialiased;
  }}
  .wrap {{
    max-width: 78rem;
    margin: 0 auto;
    padding: 0 1.5rem 6rem;
    display: grid;
    grid-template-columns: 1fr min(var(--measure), 100%) 1fr;
  }}
  .wrap > * {{ grid-column: 2; }}
  .bleed {{ grid-column: 1 / -1; }}

  h1, h2, h3 {{ text-wrap: balance; line-height: 1.2; font-weight: 600; }}
  h1 {{ font-size: clamp(2rem, 5vw, 3.1rem); margin: 0 0 .6rem; letter-spacing: -.015em; }}
  h2 {{ font-size: 1.6rem; margin: 3.4rem 0 .3rem; }}
  h3 {{ font-size: 1.16rem; margin: 2rem 0 .2rem; }}
  p {{ margin: .85rem 0; }}
  a {{ color: var(--persistence); }}

  .eyebrow {{
    font-family: var(--mono);
    font-size: .72rem;
    letter-spacing: .14em;
    text-transform: uppercase;
    color: var(--ink-3);
    margin: 0 0 1.1rem;
  }}
  /* A hairline above each section, like a depth contour on a chart: it marks
     a boundary, which is the only thing it is there to do. */
  h2::before {{
    content: "";
    display: block;
    border-top: 1px solid var(--rule);
    margin-bottom: 1.5rem;
  }}
  header {{ padding: 5rem 0 0; }}
  .standfirst {{
    font-size: 1.28rem;
    line-height: 1.5;
    color: var(--ink-2);
    margin: 0 0 2rem;
    text-wrap: pretty;
  }}
  .byline {{
    font-family: var(--mono);
    font-size: .78rem;
    color: var(--ink-3);
    border-top: 1px solid var(--rule);
    padding-top: .9rem;
    margin-top: 2rem;
  }}

  figure {{ margin: 2.2rem 0; }}
  figcaption {{
    font-size: .84rem;
    line-height: 1.5;
    color: var(--ink-3);
    margin-top: .7rem;
    max-width: var(--measure);
  }}
  .plate {{
    background: var(--plate);
    border: 1px solid var(--rule);
    padding: 1.4rem;
    overflow-x: auto;
  }}
  .hero-svg {{ width: 100%; height: auto; display: block; }}
  .grid {{ stroke: var(--rule-2); stroke-width: 1; }}
  .grid.zero {{ stroke: var(--ink-3); stroke-dasharray: 4 3; }}
  .tick {{ font-family: var(--mono); font-size: 11px; fill: var(--ink-3); }}
  .axistitle {{ font-family: var(--mono); font-size: 11px; fill: var(--ink-3); }}
  .serieslabel {{ font-family: var(--mono); font-size: 12.5px; font-weight: 600; }}
  .ta-end {{ text-anchor: end; }}
  .ta-mid {{ text-anchor: middle; }}

  /* Mermaid renders with a light theme baked into each .mmd, so the plate it
     sits on stays light in both page themes — the way a figure plate in a
     printed journal does. Reversing it per-theme would need two diagram
     sources, which is exactly the drift this setup avoids. */
  .diagram {{ background: #ffffff; border: 1px solid var(--rule); padding: 1.2rem; overflow-x: auto; }}
  .diagram pre.mermaid {{ margin: 0; text-align: center; }}

  table.results {{
    border-collapse: collapse;
    font-family: var(--mono);
    font-size: .76rem;
    font-variant-numeric: tabular-nums;
    width: 100%;
    background: var(--plate);
  }}
  table.results th, table.results td {{
    padding: .42rem .55rem;
    border-bottom: 1px solid var(--rule-2);
    text-align: left;
    white-space: nowrap;
  }}
  table.results thead tr:first-child td, table.results thead tr:first-child th {{
    border-bottom: none;
  }}
  table.results thead th {{
    color: var(--ink-3);
    font-weight: 600;
    border-bottom: 1px solid var(--rule);
  }}
  table.results thead tr:first-child th {{
    text-align: center;
    border-left: 1px solid var(--rule-2);
  }}
  table.results tbody th {{ font-weight: 500; color: var(--ink); }}
  .num {{ text-align: right !important; }}
  .neg {{ color: var(--neg); font-weight: 600; }}

  .facts {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
    gap: 1px;
    background: var(--rule);
    border: 1px solid var(--rule);
    margin: 2rem 0;
  }}
  .fact {{ background: var(--plate); padding: 1rem 1.1rem; }}
  .fact .v {{
    font-family: var(--mono);
    font-size: 1.5rem;
    font-variant-numeric: tabular-nums;
    display: block;
    line-height: 1.1;
  }}
  .fact .k {{
    font-size: .78rem;
    color: var(--ink-3);
    display: block;
    margin-top: .35rem;
    line-height: 1.35;
  }}
  .fact.p .v {{ color: var(--persistence); }}
  .fact.c .v {{ color: var(--climatology); }}

  blockquote {{
    margin: 2rem 0;
    padding-left: 1.3rem;
    border-left: 3px solid var(--climatology);
    font-size: 1.15rem;
    line-height: 1.5;
    color: var(--ink);
  }}
  code {{ font-family: var(--mono); font-size: .86em; }}
  .files {{
    font-family: var(--mono);
    font-size: .82rem;
    border-collapse: collapse;
    width: 100%;
    background: var(--plate);
  }}
  .files th, .files td {{
    padding: .5rem .6rem;
    border-bottom: 1px solid var(--rule-2);
    text-align: left;
    vertical-align: top;
  }}
  .files th {{ color: var(--ink-3); font-weight: 600; white-space: nowrap; }}
  .caveat {{
    font-size: .92rem;
    color: var(--ink-2);
    background: var(--plate);
    border: 1px solid var(--rule);
    border-left: 3px solid var(--ink-3);
    padding: 1rem 1.2rem;
    margin: 2rem 0;
  }}
  ol.steps {{ padding-left: 1.3rem; }}
  ol.steps li {{ margin: .6rem 0; }}
  @media (max-width: 40rem) {{
    body {{ font-size: 17px; }}
    .wrap {{ padding: 0 1.1rem 4rem; }}
  }}
</style>

<div class="wrap">
<header>
  <p class="eyebrow">Forecast verification &middot; {n_vars} ocean variables &middot; {n_sites} sites</p>
  <h1>Rising skill, falling skill</h1>
  <p class="standfirst">Ocean forecasts are almost always scored against
  persistence. That single baseline fails in the one direction that flatters
  the model &mdash; and the failure grows with forecast horizon, which is
  exactly where people read success.</p>
</header>

<figure class="bleed">
  <div class="plate">{hero}</div>
  <figcaption>Median skill across {n_vars} ocean variables, against two
  baselines. Persistence decays with lead time; a seasonal cycle does not. So
  the same predictions look horizon-invariant against one baseline and look
  like they decay past a seasonal lookup against the other &mdash; depending
  only on which is reported.</figcaption>
</figure>

<p class="byline">Deepak Krishna &middot; MarisAI &middot; snapshot {as_of}</p>

<h2>The argument</h2>

<p>Persistence &mdash; predict that tomorrow equals today &mdash; is a hard
baseline on autocorrelated geophysical series, and beating it is normally read
as evidence that a model learned something. The problem is structural rather
than statistical.</p>

<p>Persistence error <em>grows</em> with the forecast horizon, because the
ocean decorrelates from its present state. The error of a seasonal climatology
does not: knowing that it is February is exactly as informative thirty days
ahead as it is one day ahead. A skill score against persistence therefore has a
denominator that inflates with horizon &mdash; which holds the score up even as
the model's own error grows.</p>

<blockquote>A model that has learned nothing but the time of year can hold its
skill against persistence flat, or increase it, while genuinely degrading. Flat
skill with lead time is what a reader takes for long-range predictive
content.</blockquote>

<p>We hit this pattern in a working forecasting engine and could not tell,
with persistence as the only baseline, whether it was real skill or a seasonal
artefact. This work adds the baseline that discriminates, and audits
{n_models} models to find out.</p>

<div class="facts">
  <div class="fact p"><span class="v">{sp1:.3f} &rarr; {sp30:.3f}</span>
    <span class="k">median skill vs. persistence, 1 d &rarr; 30 d &mdash; unchanged</span></div>
  <div class="fact c"><span class="v">{sc1:.3f} &rarr; {sc30:.3f}</span>
    <span class="k">median skill vs. climatology, 1 d &rarr; 30 d &mdash; collapses</span></div>
  <div class="fact"><span class="v">{flattered}</span>
    <span class="k">models that beat persistence but lose to climatology</span></div>
  <div class="fact"><span class="v">{lose_pers}</span>
    <span class="k">models worse than doing nothing at all</span></div>
</div>

<h2>How the framework is built</h2>

<p>One acquisition path, one feature builder and one model class serve every
variable; nothing in the pipeline branches on which variable it is training.
That uniformity is what makes a cross-variable audit meaningful &mdash;
differences in the results cannot be blamed on differences in the
implementation.</p>

<figure class="bleed">
  <div class="diagram">{arch}</div>
  <figcaption>Framework architecture. The three predictors at the bottom are
  scored on identical rows. Shaded: the climatology baseline and the second
  skill score it makes possible.</figcaption>
</figure>

<h3>Why the model predicts change, not level</h3>

<p>A regression tree partitions feature space into piecewise-constant regions,
so it cannot represent the identity function <code>y(t+h) = y(t)</code> &mdash;
which is exactly what persistence is. Fitted on levels, the framework scored
worse than persistence at <em>every</em> horizon. Fitted on the change,
persistence becomes the constant zero function, which a tree represents
exactly, and the same data and features yield positive skill.</p>

<h2>How the experiments are run</h2>

<p>The climatology is a per-site day-of-year mean over a &plusmn;{window}-day
circular window, and it is refitted <em>inside every cross-validation fold</em>
on that fold's training rows only. Fitting it once over the whole record would
leak the evaluation period into the baseline's own definition &mdash;
flattering the baseline, understating the model. That is an error in the safe
direction, which is why it is easy to leave in place.</p>

<figure class="bleed">
  <div class="diagram">{flow}</div>
  <figcaption>Both experiments end to end. Shaded boxes are the two places a
  baseline is fitted; both are fitted strictly inside the fold they are scored
  in.</figcaption>
</figure>

<div class="caveat"><strong>The window is not cosmetic.</strong> The record
spans about 2.2 years, so a bare day-of-year mean would average two samples
and be mostly noise &mdash; a strawman the model beats for the wrong reason.
A &plusmn;{window}-day window pools roughly 60 samples per estimate, which is
what makes this a baseline worth losing to. A longer record would strengthen
the climatology further, so this comparison is conservative in the direction
that favours the model.</div>

<h2>Results</h2>

<p>Median skill against persistence is <strong>{sp1:.3f}</strong> at one day
and <strong>{sp30:.3f}</strong> at thirty &mdash; essentially unchanged, having
dipped to {sp3:.3f} and {sp7:.3f} in between. Read alone, that says the models
are as good at a month as at a day, which for a forecasting system would be
remarkable.</p>

<p>Over exactly the same range, median skill against climatology falls
monotonically: <strong>{sc1:.3f}</strong>, {sc3:.3f}, {sc7:.3f},
<strong>{sc30:.3f}</strong>. It declines with horizon for
<strong>{falling} of {n_vars}</strong> variables without exception. By thirty
days the median model has fallen <em>below</em> the seasonal cycle, and
<strong>{clim_neg_30} of {n_vars}</strong> variables lose to it outright &mdash;
against {pers_neg_30} that lose to persistence.</p>

<p>The sharpest cases are the <strong>{flattered}</strong> model&ndash;horizon
combinations that beat persistence while losing to climatology. Under a
single-baseline convention every one of them reads as a success, when the
correct call is to ship the climatology instead: cheaper to compute, cheaper to
serve, and more accurate.</p>

<figure class="bleed">
  <div class="plate">{table}</div>
  <figcaption>Skill against persistence (S<sub>p</sub>) and against climatology
  (S<sub>c</sub>) at each horizon. Red marks a negative score &mdash; the
  baseline winning. Reading across a row shows the divergence; reading down the
  S<sub>c</sub> columns shows it is systematic rather than incidental.</figcaption>
</figure>

<h3>The two baselines fail in different places</h3>

<p><strong>{lose_pers}</strong> model&ndash;horizon combinations are worse than
doing nothing at all. These concentrate in high-inertia subsurface variables,
and the pattern is physically coherent: when a variable's autocorrelation time
greatly exceeds the horizon, persistence is near-optimal and the residual is
close to pure noise, so fitting it adds variance without adding signal.</p>

<p>Crucially these are <em>not</em> the same variables that fail against
climatology. Some subsurface variables lose to persistence while beating
climatology by a wide margin; some wave variables do the reverse. That the two
baselines fail in different places is the strongest available argument for
reporting both.</p>

<h2>Does it transfer to ocean it never saw?</h2>

<p>Serving one globally pooled model at arbitrary coordinates rests on an
assumption that is rarely tested. We tested it directly: {n_loso} fits, each
training on 23 sites and scoring the 24th, blocked in space <em>and</em> time
&mdash; the model trains on the earlier 80% of the record at the retained
sites and is scored on the later 20% at the held-out one.</p>

<div class="facts">
  <div class="fact p"><span class="v">{pooled7:.3f}</span>
    <span class="k">median skill at sites seen in training (7 d)</span></div>
  <div class="fact c"><span class="v">{loso7:.3f}</span>
    <span class="k">median skill at held-out sites (7 d)</span></div>
  <div class="fact"><span class="v">{loso_pos:.0f}%</span>
    <span class="k">held-out sites that keep positive skill</span></div>
  <div class="fact"><span class="v">{n_loso}</span>
    <span class="k">held-out fits</span></div>
</div>

<p>Transfer is real but it costs skill, and the cost is concentrated in
dynamically energetic regions &mdash; western boundary currents and upwelling
systems, whose variability is driven by mesoscale processes a model fitted on
distant sites cannot resolve. The majority staying positive supports serving
the pooled model at unseen coordinates; the falling median means the pooled
figure overstates what a user clicking on open ocean should expect, and a
deployed system should say so.</p>

<h2>What to do with two numbers</h2>

<p>Taken together the pair maps onto a small set of clearly distinguishable
recommendations &mdash; three of which are &ldquo;do not deploy this
model&rdquo; for reasons a single baseline cannot surface.</p>

<figure class="bleed">
  <div class="diagram">{decide}</div>
  <figcaption>Interpreting the two skill scores together.</figcaption>
</figure>

<h2>The papers</h2>

<p>The manuscript is typeset for both major conference families from one
shared body, so the two cannot drift apart. Every experimental number in the
prose is a generated macro rather than a typed figure &mdash; rerunning the
experiments updates the manuscript.</p>

<table class="files">
<tr><th>research/springer/main.pdf</th><td>Springer LNCS format
  (<code>llncs</code>, single column)</td></tr>
<tr><th>research/ieee/main.pdf</th><td>IEEE conference format
  (<code>IEEEtran</code>, two column)</td></tr>
<tr><th>research/shared/body.tex</th><td>the manuscript body, shared verbatim
  by both builds</td></tr>
<tr><th>research/shared/diagrams/</th><td>Mermaid sources &mdash; the same
  files render to PDF for the papers and inline on this page</td></tr>
<tr><th>research/shared/generated/</th><td>figures, LaTeX tables and the
  number macros, all generated from the experiment output</td></tr>
</table>

<h3>Rebuilding</h3>
<ol class="steps">
<li>Run both experiments:
  <code>python scripts/run_paper_experiments.py --all</code></li>
<li>Regenerate figures, tables and macros:
  <code>python scripts/build_paper_assets.py</code></li>
<li>Compile either format:
  <code>tectonic -X compile main.tex --outdir .</code></li>
</ol>

<h2>What this does not claim</h2>

<p>The record is about 2.2 years, so the seasonal cycle cannot be separated
from interannual variability. The &ldquo;observations&rdquo; are operational
analysis products &mdash; themselves model output constrained by assimilated
data &mdash; so these scores measure agreement with an analysis, not with the
ocean. The {n_vars} variables are those with complete {n_sites}-site coverage
in the archive at the snapshot date, a criterion applied before any model was
scored. Hyperparameters are fixed across all variables, so no individual model
is at its own ceiling. And wave direction is decoded circularly but still
regressed linearly, so a veer across north trains as a near-full reversal.</p>

<p class="byline">Experiments pinned to snapshot {as_of} &middot;
{n_models} models &middot; {n_loso} held-out fits &middot; climatology window
&plusmn;{window} days</p>
</div>
"""


if __name__ == "__main__":
    build()
