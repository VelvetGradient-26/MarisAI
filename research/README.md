# Rising Skill, Falling Skill

A research paper built from the MarisAI forecasting engine's own training data,
on why persistence alone is an insufficient baseline for statistical ocean
forecasting.

**Claim.** Persistence error grows with forecast horizon; a seasonal cycle's
does not. So the persistence-referenced score of a model that has learned
nothing but the time of year stays flat, or rises, while the model genuinely
degrades. Reporting persistence alone therefore fails in the direction that
flatters the model.

**What the audit found** (13 variables × 4 horizons × 24 sites):

| median skill | h=1 | h=3 | h=7 | h=30 |
| --- | --- | --- | --- | --- |
| vs. persistence | +0.272 | +0.154 | +0.151 | **+0.273** |
| vs. climatology | +0.958 | +0.729 | +0.410 | **−0.023** |

Persistence says the models are as good at a month as at a day. Climatology
says the median model has fallen *below the seasonal cycle* by then — and
climatology skill declines with horizon for **13 of 13** variables, without
exception. Eleven model–horizon combinations beat persistence while losing to
climatology; under a persistence-only convention every one reads as a success.

## Layout

```
research/
  index.html              the web artifact (generated)
  springer/main.{tex,pdf} Springer LNCS build (llncs, single column)
  ieee/main.{tex,pdf}     IEEE conference build (IEEEtran, two column)
  shared/
    body.tex              the manuscript, shared verbatim by both builds
    references.bib        shared bibliography
    diagrams/*.mmd        Mermaid sources -> PDF for the papers, inline on the page
    generated/            figures, LaTeX tables, number macros (all generated)
```

**The two builds share `body.tex` verbatim.** Only the wrappers differ. Each
defines three things the body relies on and nothing else:

| Macro | Springer (one column) | IEEE (two column) |
| --- | --- | --- |
| `wfigure` / `wtable` | plain `figure` / `table` | `figure*` / `table*`, spanning both columns |
| `\tabscale` | `\footnotesize` | `\scriptsize` |
| `\para{X}` | `X.` — llncs adds no punctuation | `X` — IEEEtran appends its own colon |

Keeping the body class-agnostic is the point: two manuscripts that drift apart
is the failure this structure exists to prevent.

## Rebuilding

```bash
cd backend

# 1. Both experiments (~60 min, runs offline from the history cache)
.venv/bin/python scripts/run_paper_experiments.py --all

# 2. Figures, LaTeX tables, and the \newcommand macros the prose quotes
.venv/bin/python scripts/build_paper_assets.py

# 3. The web artifact (same JSON, so it cannot disagree with the papers)
.venv/bin/python scripts/build_research_artifact.py

# 4. Diagrams, if any .mmd changed (needs `npm i -g @mermaid-js/mermaid-cli`)
../research/shared/diagrams/render.sh

# 5. Compile either format (needs `brew install tectonic`)
cd ../research/springer && tectonic -X compile main.tex --outdir .
cd ../ieee     && tectonic -X compile main.tex --outdir .
```

## Why no number is typed by hand

`build_paper_assets.py` writes `shared/generated/macros.tex`, and the prose says
`\MedSkillPThirty{}` rather than `0.430`. The artifact generator reads the same
JSON. Rerunning the experiments updates all three outputs together; the
alternative — transcribing a results table into prose — is how a paper ends up
quoting a number its own table contradicts.

## Two things that make the experiments reproducible

- **`as_of` is pinned** to `2026-08-10` in `run_paper_experiments.py`. The
  training window is measured back from it, so every cached provider request has
  a stable key. Without it each rerun re-requests two years of data from 24
  points per variable and scores a slightly different dataset.
- **`MARISAI_FROZEN_HISTORY_CACHE=1`** (set by the script itself) serves the disk
  cache regardless of its 6-hour TTL. The TTL is correct for a live request
  asking for a window ending "now"; a pinned historical window cannot be revised
  upstream, so re-fetching only costs ~700 s per variable and risks a partial
  provider response. No serving path sets this.

Together these take assembly from ~700 s to ~0.8 s per variable, which is what
makes a 52-model audit plus 1,248 held-out fits practical at all.

## What the experiments add to the engine

| File | What it is |
| --- | --- |
| `backend/forecasting/climatology.py` | the baseline, with `fit_`/`apply_` split so fitting on evaluation rows takes deliberate effort |
| `backend/tests/test_climatology.py` | leakage, circular-mean and nearest-site-fallback guards |
| `backend/forecasting/evaluator.py` | `skill_vs_climatology` beside the existing persistence skill; per-fold climatology callable |
| `backend/scripts/run_paper_experiments.py` | both experiments |
| `backend/scripts/probe_cache.py` | how the `as_of` snapshot date was chosen |

## Scope

Thirteen of the engine's variables, being those with complete 24-site coverage
in the history cache at the snapshot date. The criterion is data availability
and was applied before any model was scored, but the set is not a random sample
of ocean variables — it skews toward well-observed operational products. The
paper states this rather than presenting thirteen as the whole set.
