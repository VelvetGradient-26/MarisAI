# Rising Skill, Falling Skill

Research on why persistence alone is an insufficient baseline for statistical
ocean forecasting, built from the MarisAI forecasting engine's own training
data.

**Claim.** Persistence error grows with forecast horizon; a seasonal cycle's
does not. So the persistence-referenced score of a model that has learned
nothing but the time of year stays flat, or rises, while the model genuinely
degrades. Reporting persistence alone therefore fails in the direction that
flatters the model.

**What the audit found** (13 variables × 4 horizons × 24 sites = 52 models,
plus 1,248 held-out fits):

| median skill | h=1 | h=3 | h=7 | h=30 |
| --- | --- | --- | --- | --- |
| vs. persistence | +0.272 | +0.154 | +0.151 | **+0.273** |
| vs. climatology | +0.958 | +0.729 | +0.410 | **−0.023** |

Persistence says the models are as good at a month as at a day. Climatology
says the median model has fallen *below the seasonal cycle* by then — and
climatology skill declines with horizon for **13 of 13** variables, without
exception. Eleven model–horizon combinations beat persistence while losing to
climatology; under a persistence-only convention every one reads as a success.

**And the obvious explanation for those eleven is wrong.** A three-arm feature
ablation shows **10 of the 11 keep their skill when every calendar feature is
removed**, while the most calendar-dependent variable in the study (water
temperature at 30 days — 68% of its skill is calendar-borne) comfortably
*beats* climatology. Losing to climatology reports the **baseline's strength**,
not the model's mechanism. Diagnosing mechanism needs the ablation; two
baselines cannot do it.

An earlier draft claimed these models had "learned what month it is." The
experiment retracted it.

---

## Layout

```
research/
  notebooks/          reproduce and evaluate the whole study, in order
    marisviz.py       shared paths, data loading, high-resolution plot style
    01_data_and_eda.ipynb
    02_feature_engineering.ipynb
    03_baselines_and_models.ipynb
    04_results_and_transfer.ipynb
    figures/          PNGs written by the notebooks (300 dpi)
  data/               self-contained inputs, committed
    point_series.parquet   988,872 cleaned observations (3.1 MB)
    sites.csv              the 24 evaluation sites
    variables.json         per-variable configuration and metadata
    results/               experiment output (792 KB) so notebook 04 runs
                           from a clone; backend/models/ is untracked
  papers/
    springer/main.{tex,pdf}   Springer LNCS build (single column)
    ieee/main.{tex,pdf}       IEEE conference build (two column)
    shared/
      body.tex                the manuscript, shared verbatim by both builds
      references.bib
      diagrams/*.mmd          Mermaid sources → PDF for papers, inline on the page
      generated/              figures, LaTeX tables, number macros (generated)
  index.html          the web artifact (generated)
```

## Start here: the notebooks

Run them in order. **No credentials and no network are required** — everything
reads `research/data/`, which is committed.

| Notebook | What it establishes |
| --- | --- |
| `01_data_and_eda` | The 13 variables, 24 sites and their coverage; seasonal structure; autocorrelation, which identifies where persistence will be hard to beat. |
| `02_feature_engineering` | The ~59 features and their families; cyclical calendar encoding; the leakage discipline; and the delta-vs-level target comparison the framework turns on. |
| `03_baselines_and_models` | Both baselines; why the climatology window is ±15 days; the circular mean; a direct measurement of what fitting a baseline on the evaluation period costs; and an end-to-end three-way comparison. |
| `04_results_and_transfer` | All 52 models against both baselines; the 11 flattered cases; the 5 outright failures; the **seasonality ablation** that retracts the seasonal explanation; and the leave-one-site-out transfer results. |

```bash
cd research/notebooks
jupyter lab            # or: jupyter notebook
```

The kernel is the backend virtualenv (`backend/.venv`), which already has
everything: `marisviz.py` puts `backend/` on `sys.path` so the notebooks import
the **shipped** implementation (`forecasting.climatology`,
`forecasting.feature_engineering`) rather than reimplementing it. A notebook
that re-derives the method it documents can agree with the paper while the
shipped code disagrees with both.

To re-execute them all headlessly:

```bash
cd research/notebooks
for nb in 0*.ipynb; do
  ../../backend/.venv/bin/python -m nbconvert --to notebook --execute \
      --inplace --ExecutePreprocessor.timeout=1800 "$nb"
done
```

### Figure quality

`marisviz.setup()` fixes the matplotlib configuration once for all four
notebooks: **140 dpi inline, 300 dpi on save**, retina inline format, a serif
face matching the manuscript, recessive grid and axis chrome, and the study's
two-colour palette. That palette is validated for colour-vision deficiency
(ΔE 21.7 protan, 29.9 tritan) and both hues clear 3:1 contrast on white, so the
figures survive being printed, projected, or read by a colourblind reviewer.
`mv.save(fig, "name")` writes to `notebooks/figures/` at 300 dpi.

## Rebuilding everything

```bash
cd backend

# 1. Both experiments (~87 min; runs offline from the history cache)
.venv/bin/python scripts/run_paper_experiments.py --all

# 1b. The seasonality ablation (~40 min): full / no-calendar / calendar-only
.venv/bin/python scripts/run_seasonality_ablation.py --all

# 2. The notebook dataset (only needed if the experiments' inputs changed)
.venv/bin/python scripts/export_research_dataset.py

# 3. Figures, LaTeX tables, and the \newcommand macros the prose quotes
.venv/bin/python scripts/build_paper_assets.py

# 4. The web artifact (same JSON, so it cannot disagree with the papers)
.venv/bin/python scripts/build_research_artifact.py

# 5. Diagrams, if any .mmd changed (needs `npm i -g @mermaid-js/mermaid-cli`)
../research/papers/shared/diagrams/render.sh

# 6. Compile either format (needs `brew install tectonic`)
cd ../research/papers/springer && tectonic -X compile main.tex --outdir .
cd ../ieee                     && tectonic -X compile main.tex --outdir .
```

## The two paper builds share one body

Only the wrappers differ. Each defines three things and nothing else:

| Macro | Springer (one column) | IEEE (two column) |
| --- | --- | --- |
| `wfigure` / `wtable` | plain `figure` / `table` | `figure*` / `table*`, spanning both columns |
| `\tabscale` | `\footnotesize` | `\scriptsize` |
| `\para{X}` | `X.` — llncs adds no punctuation | `X` — IEEEtran appends its own colon |

Keeping `body.tex` class-agnostic is the point: two manuscripts that drift apart
is the failure this structure exists to prevent.

## Why no number is typed by hand

`build_paper_assets.py` writes `papers/shared/generated/macros.tex`, and the
prose says `\MedSkillPThirty{}` rather than `0.273`. The artifact generator
reads the same JSON. Rerunning the experiments updates all three outputs
together; the alternative — transcribing a results table into prose — is how a
paper ends up quoting a number its own table contradicts.

## Two things that make the experiments reproducible

- **`as_of` is pinned** to `2026-08-10` in `run_paper_experiments.py`. The
  training window is measured back from it, so every cached provider request has
  a stable key. Without it each rerun re-requests two years of data from 24
  points per variable and scores a slightly different dataset.
- **`MARISAI_FROZEN_HISTORY_CACHE=1`** (set by the scripts themselves) serves the
  disk cache regardless of its 6-hour TTL. The TTL is correct for a live request
  asking for a window ending "now"; a pinned historical window cannot be revised
  upstream, so re-fetching only costs ~700 s per variable and risks a partial
  provider response. No serving path sets this.

Together these take assembly from ~700 s to ~0.8 s per variable, which is what
makes a 52-model audit plus 1,248 held-out fits practical at all.

## What this adds to the engine

| File | What it is |
| --- | --- |
| `backend/forecasting/climatology.py` | the baseline, with `fit_`/`apply_` split so fitting on evaluation rows takes deliberate effort |
| `backend/tests/test_climatology.py` | leakage, circular-mean and nearest-site-fallback guards |
| `backend/forecasting/evaluator.py` | `skill_vs_climatology` beside the existing persistence skill; per-fold climatology callable |
| `backend/scripts/run_paper_experiments.py` | both experiments |
| `backend/scripts/export_research_dataset.py` | the notebooks' self-contained dataset |
| `backend/scripts/probe_cache.py` | how the `as_of` snapshot date was chosen |

## Scope and honest limits

- **Thirteen of the engine's variables**, being those with complete 24-site
  coverage in the history cache at the snapshot date. The criterion is data
  availability and was applied before any model was scored, but the set is not a
  random sample of ocean variables — it skews toward well-observed operational
  products.
- **The record is ~2.2 years**, so the seasonal cycle cannot be separated from
  interannual variability, and the climatology is estimated from two annual
  cycles. A longer record would strengthen the baseline, making this comparison
  conservative in the direction that favours the model.
- **"Observations" are operational analysis products**, not in-situ
  measurements — themselves model output constrained by assimilated data. These
  scores measure agreement with an analysis, not with the ocean.
- **Autocorrelation does not predict skill on its own.** Notebook 01 raises the
  hypothesis and notebook 04 tests it: pooled Spearman is ≈0. It flags where the
  baseline will be strong, not where the model will lose. Stated because the
  shortcut is tempting.
- **Wave direction is regressed linearly** though decoded circularly, so a veer
  across north trains as a near-full reversal.
