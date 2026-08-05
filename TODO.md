# TODO

Jobs identified during the 2026-08-05 review. Ordered within each section by
what unblocks the most other work, not by size.

Numbers here were measured, not estimated — where a figure appears, it came
from an actual run against this repo. Re-verify before relying on any of them
if it has been a while.

---

## 1. MLflow experiment tracking

**Why first:** nothing else in this list can be evaluated without it. Every
report under `machine_learning/reports/` and `backend/models/forecasting/_reports`
is written to a **fixed filename**, so each rerun destroys the previous result.
There is currently no way to answer "did that feature help?" — which makes every
other improvement below unmeasurable.

- Track both ML problems (`hab_early_warning`, `fish_habitat_prediction`) and
  the backend forecasting engine's training runs.
- Log per run: config snapshot, feature list, fold scores, holdout scores,
  SHAP top-N, and the resolved data window.
- The forecasting engine already emits `skill_score` vs persistence — that is
  the metric to make the headline comparison, since it is what catches a model
  shipping worse than the trivial baseline.
- Keep it offline-only. `backend/` must not gain an MLflow import: the boundary
  that keeps `machine_learning/` out of the backend's import graph is
  deliberate (see CLAUDE.md).
- SQLite backend store is sufficient; no server needed for a single machine.

## 2. Train more `forecasting.yaml` variables

`backend/forecasting/config/forecasting.yaml` configures **32 variables**;
`backend/models/forecasting/` contains **2** (`sea_surface_temperature`,
`air_temperature`).

This is the highest AI-surface-per-unit-effort item in the repo. Each variable
is one YAML block naming a code the download registry already serves, plus a
training run — and it yields a complete metric-intelligence page at
`/dashboard/<variable>` with **no frontend edit** (verified: `/dashboard/nitrate`
already renders and correctly omits the untrained sections).

- Start with variables whose providers are cheap and already cached:
  `significant_wave_height`, `sea_surface_salinity`, `current_speed`.
- Watch the `skill_score` line in the training log. `WORSE THAN PERSISTENCE`
  means do not ship that variable+horizon, not "tune it a bit".
- Not every variable will train well; a variable that cannot beat persistence
  should stay untrained rather than ship a page that implies a working forecast.

## 3. Global forecasting

Both ML models are regional — `ARABIAN_SEA` (HAB) and `NORTH_INDIAN_OCEAN`
(habitat) — while the map, dashboard and downloader are global. The forecast
grid path is already global, so this is mostly about the two `machine_learning/`
problems and about grid build cost.

- Cost is dominated by the fetch and is **independent of output resolution**:
  ~1080 whole-globe reads (~35 min) plus ~15 min of cell loop at 1°.
  `--resolution 4.0` speeds up only the loop.
- The ~40x cheaper daily Copernicus products were measured and deliberately not
  adopted: they would collapse hourly wind onto a daily axis inside
  `build_dataframe`'s inner join, turning wind speed from a 24-hour mean into
  one instantaneous value. Solve that before swapping them in.
- Open-Meteo variables can never be gridded (point API, 900-point cap).
  `grid_history.ungriddable_reason` already encodes this — extend rather than
  work around it.
- Region expansion for HAB/habitat is bounded by data, not code: the habitat
  window is 2000–2013 because OBIS target-species records stop after 2014.

---

## 4. Conversational agent over the existing API (in progress)

Not RAG — **tool-calling** over the ~40 endpoints that already exist. "What is
the 7-day SST forecast off Kochi, and how does it compare to last year?" becomes
calls to `/api/v1/forecast` and `/trends`, narrated over the real returned
numbers. Grounded in live data, and it surfaces the whole platform through one
interface.

- `services/llm.py` already provides a provider-agnostic `LLMProvider` Protocol
  (Gemini / OpenAI / Ollama) behind `LLM_PROVIDER` / `LLM_API_KEY` /
  `LLM_MODEL` / `LLM_BASE_URL`. The gap is that `generate(prompt) -> str` has
  **no tool-calling**.
- Reuse `services/metrics/story.py`'s discipline: compute first, phrase second,
  and verify that every number in the response is derivable from the facts
  block. Hallucinated ocean readings are the whole risk here, and that pattern
  is the existing mitigation.
- Keep the agent's tool surface narrow (5-8 tools). Every tool is a prompt the
  model can get wrong.

## 5. ConvLSTM / U-Net for spatial forecasting

**The argument for deep learning here is architectural, not decorative.**
`grid_predictor` scores every cell **independently** — it loops cell by cell
through the point pipeline, deliberately, to avoid train/serve skew. The
consequence is that the model cannot see spatial structure at all: not an eddy,
not a front, not the shape of a bloom. A gradient-boosted tree over per-cell
features is structurally blind to the neighbourhood.

That is a real gap a convolutional/recurrent model fills, and it is defensible
under questioning in a way that bolting an LSTM onto tabular data is not.

- Baseline to beat is strong and already measured: delta-target LightGBM at
  skill +0.20 vs persistence. **Trees beating neural nets on tabular data is
  the norm** — the claim to make is "DL where trees are provably blind
  (fields), trees where they win (points)", not "DL is better".
- Two candidate framings, smaller first:
  - **U-Net segmentation of HAB bloom extent** over chlorophyll fields.
    Contained, and 3.9M labelled rows already exist.
  - **ConvLSTM over SST/chlorophyll fields** for grid-to-grid forecasting.
    Directly extends the forecast map.
- Cost: the gridded training data is the expensive part (~35 min per fetch
  window, resolution-independent). Budget for that before any modelling.
- Do not start this until (1) MLflow exists — otherwise "did it help?" is
  unanswerable — and (4) works.

## 6. RAG — scope carefully, most framings do not typecheck

RAG retrieves from unstructured text. MarisAI's data is numeric grids and time
series; you do not *retrieve* SST, you query it. "RAG over ocean data" is a
category mismatch and should not be built.

Two targets are legitimate:

- **The data catalog itself** — 36 variables x provider, dataset, grid spacing,
  cadence, coverage start, citation, licence. Genuinely useful ("which
  variables cover 2015 daily at 0.083 degrees?"). But this is ~36 records: it
  **fits in a single prompt**. Prompt-stuffing is the correct implementation.
  Standing up a vector database for 36 documents is the trap to avoid.
- **Scientific literature** on HABs and the five target species. This is real
  RAG with a real corpus, and would genuinely deepen the explainability
  sections — but it is a separate ingestion project that does not touch the
  platform's own data path. Treat it as its own effort, not as a feature of
  the chatbot.

Sequence: do the catalog version as prompt context inside (4) first, and only
consider a vector store if the literature corpus is actually pursued.

---

## Bugs and correctness

### Fish-habitat ensemble scores below its own best member

`fish_habitat_prediction` weights ensemble members by **normalized CV TSS**,
which compresses a large quality gap into a small weight gap:

| model | CV TSS | weight | holdout TSS |
|---|---|---|---|
| lightgbm | 0.826 | 0.364 | **0.788** |
| random_forest | 0.821 | 0.362 | 0.774 |
| maxent | 0.619 | **0.273** | 0.365 |
| ensemble | — | — | **0.694** |

MaxEnt gets 27% of the vote at less than half the holdout TSS, and the exported
product (`habitat_suitability.nc`) is the ensemble. **Not a pure loss:** the
ensemble has the best Boyce index (0.936 vs 0.895), so it is better spatially
calibrated while being worse at discrimination. The problem is that this
tradeoff is currently made implicitly by a weighting formula. Make it
deliberate: drop MaxEnt, weight by rank/softmax rather than raw TSS, or stack
on out-of-fold predictions.

### `machine_learning/` tests do not run

`pytest tests/` fails at collection with `ModuleNotFoundError: No module named
'marine_ml'` — there is no `pyproject.toml`, `pytest.ini` or `setup.cfg` in
`machine_learning/`. With `PYTHONPATH=. pytest tests/`, **all 23 pass**.

Higher risk than a normal broken path because of *what* those tests are: they
enforce "only one forward shift exists", "never random K-fold", and
"climatology fitted on training rows only". They are the guardrails against
silent methodology error, and they are invisible to anyone who runs pytest the
obvious way. One config file with `pythonpath = ["."]` fixes it.

### Feature store is stored at float64

`data/processed/feature_store/hab_gridded.parquet` — 3.9M rows x 151 columns,
2.6 GB, with **142 `double` columns**. It predates `compact_dtypes` being wired
into `write_feature_store`. `read_feature_store` compensates, but only *after*
`pd.read_parquet` has materialized ~4.7 GB, so peak is ~7 GB with both copies
alive — the OOM-with-no-traceback its own docstring warns about, paid on every
experiment iteration.

- Rewrite the store once compacted: 2.6 GB -> ~1.3 GB, peak read ~7 GB -> ~2.4 GB.
- Add `columns=` passthrough to `read_feature_store`. Columnar projection is the
  single biggest experimentation win: a 20-of-151-column experiment reads ~13%
  of the file. No new infrastructure.
- Do **not** move this to Postgres/Mongo/Redis. Row stores read all 151 columns
  to serve 12; Parquet reads 12. If it outgrows one machine, DuckDB reads these
  same files in place with no import step.

### HAB t+7 sits at the edge of usefulness

At the 0.8-recall operating point: precision 0.202, false-alarm rate 0.798 —
four of every five alerts are false. Defensible for a screening tool where a
miss costs more than a false alarm, but that should be an explicit decision
recorded in the UI copy, not a horizon that merely exists.

### Small habitat holdout

885 rows / 167 positives. The confidence interval on holdout TSS 0.788 is wide;
the spatial folds (471–791 rows each, TSS 0.76–0.90) are the more trustworthy
signal. Report both rather than the holdout alone.

---

## Documentation drift

- CLAUDE.md states "the HAB window is 2 years". `marine_ml/config.py` has
  `HAB_START = 2016-01-01`, `HAB_END = 2021-12-31` — six years — and
  `fusion.py`'s own docstring agrees ("6-year daily feature table"). Correct
  CLAUDE.md.

---

## Deferred / considered and rejected

- **A database for caching.** Every in-process cache is already bounded with
  eviction; the on-disk fetch cache is 4.6 MB. Memory was concentrated in a few
  global float64 arrays, addressed directly (SST cache: ~140 MB -> ~35 MB via
  float32 plus removing a duplicated array). Redis/Mongo would relocate those
  bytes while adding a second resident copy plus serialization on the hot path.
- **A database for the ML feature store.** Parquet is the correct technology for
  wide float matrices; see the feature-store item above.
- **Postgres for persistence** remains genuinely open, but for *records* rather
  than cache or features: download history/audit, feedback (currently
  `feedback_log.jsonl`), and the KPI ring buffer that does not survive restart.
