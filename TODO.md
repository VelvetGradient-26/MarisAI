# TODO

Open work only. Items are removed from this file when they ship — what survives
a deletion is the *finding*: a measured number, or a decision with the reason
attached, kept so it is not re-derived or re-litigated. Sections are ordered by
what unblocks the most other work, not by size.

Numbers here were measured, not estimated. Re-verify before relying on any of
them if it has been a while.

---

## 1. Machine time, not code

These are the shortest entries in the file and the largest fraction of what is
actually blocking. Nothing here needs a design decision; each needs a run.

### `wind_u` / `wind_v` training and grid builds — the biggest single unblock

```bash
python scripts/train_forecasting.py --variable wind_u
python scripts/train_forecasting.py --variable wind_v
python scripts/build_forecast_grid.py --variable wind_u
python scripts/build_forecast_grid.py --variable wind_v
```

Everything else is done: registry entries (from the Copernicus wind provider's
`eastward_wind`/`northward_wind`, which it already served), YAML blocks carrying
`wind_speed`'s covariates, and a `VectorPair` registered **before its grids
exist, deliberately** — the catalog reports it with an explicit reason and the
frontend hook logs that, which beats a layer silently not existing.

Three separate features are waiting on this one run:

- **Forecast wind particles**, which cannot be composed from `wind_speed` +
  `wind_direction`: direction is circular while every step to the screen is
  linear, so a vector built from those two grids flows backwards along every
  wrap through north.
- **A forecast drift field.** The live one ships (§3); its wind term is
  observation-only until these exist.
- **Upwelling detection** (§4), which needs Ekman transport, which needs wind
  *components* — a bearing cannot supply them.

Apply the usual bar to the training log: skill > 0 **and** ≤1 of 5 folds
negative, read from `metrics.json` rather than the aggregate line. The same move
would make `wind_direction` a derived field rather than a trained one, which is
the better answer for it anyway.

### Retrain the 13 variables affected by the mixed-cadence merge

`cleaning.py::build_dataframe` merged providers and *then* resampled, so an
hourly covariate paired with a daily target survived as its 00:00 sample
standing in for a 24-hour mean. Fixed 2026-08-10 by reordering to **resolve
codes → aggregate per provider → merge**; on a synthetic 3 °C diurnal cycle the
old path returned **23.0 where the daily mean is 20.0** — wrong by the full
amplitude, in the same direction, in every row, with nothing raised.

**13 of the 32 configured variables trained on this**: all five wave variables
(3-hourly target against hourly wind), all seven biogeochemistry variables
(daily target against hourly SST), the three depth-resolved ones and
`sea_level_anomaly`. Nothing is *unsafe* about the shipped models — they are
self-consistent, trained and served on the same features — but they are fitted
on a covariate that misrepresents its own day.

The built grids in that set should be rebuilt with the models, so the features
change once. Settle the daily-product question below first for the same reason.

### Finish the `--all` forecast grid build

**8 of the 26 griddable variables are built** (count the directory; do not quote
a number from a document). 5 of the 31 trained variables can *never* be gridded
— Open-Meteo is a point API with a 900-point cap, and
`grid_history.ungriddable_reason` already encodes this; extend it rather than
working around it.

- Cost is dominated by the fetch and is **independent of output resolution**:
  ~1080 whole-globe reads (~35 min) plus ~15 min of cell loop at 1°.
  `--resolution 4.0` speeds up only the loop; `--skip-fresh HOURS` is what makes
  an interrupted run resumable.
- **The build is affordable because the fetch cache was fixed.** It keyed on the
  exact field list, so `current_u` fetching `(uo, zos)` and `current_v` fetching
  `(vo, zos)` missed each other and each paid 35 minutes for the same product. A
  cached entry that *contains* the requested fields is now a hit, and `--all`
  warms the union first: one fetch window covering 31 codes instead of 26
  separate fetches.

### The four unrun HAB regions

`config.HAB_REGIONS` holds five boxes — Arabian Sea, Bay of Bengal, Benguela,
California Current, Baltic — and only the Arabian Sea control has data. One
fetch each. Thresholds and climatology stay fitted **per region**: they define
what counts as a bloom, and one region's distribution must not set another's
labels.

**HAB is multi-region rather than global on arithmetic**, not preference: the
same six years worldwide at 0.25° is ~1.6 billion rows and **~650 GB**, most of
it open-ocean rows that are near-constant negatives.

### Validate the global PFZ model on the *regional* holdout

The code side is built (both pipelines take `--region`; the default region keeps
its historic artifact names so the regional models remain the baseline). What
has not been done is the comparison that matters: a global model that scores
well on a global average can still be worse over the Indian Ocean, which is the
region this platform exists for.

---

## 2. Settle the daily-Copernicus question before the retrains

The ~40x cheaper daily products would change what every affected variable trains
on, so this gates §1's retrains.

- **Re-measure through the real fetch path.** Probed 2026-08-10 by reading one
  global surface field strided to 1°: hourly physics **34–46 s/timestep**, daily
  thetao **84–104 s/timestep** — the daily product is ~2.5x *slower per read*,
  because those datasets carry 50 depth levels and a geo-series chunk brings the
  whole depth column down for a surface field. 45 × ~98 s still beats 1080 × ~39
  s on paper, but that probe read the lazy array directly rather than going
  through `copernicus.fetch_global`, and neither figure reconciles with the ~35
  min a real SST grid takes. Redo it through the real path **with a server-side
  depth bound** (`minimum_depth`/`maximum_depth`) — the same omission
  `machine_learning/` documents turning a 15-minute-plus fetch into ~60 s, and
  possibly the entire discrepancy.
- The 1.05 s / 0.60 s per-timestep figures previously recorded in
  `grid_history.py` were **not** measured through this path. Do not trust them.
- The *merged* daily product `cmems_mod_glo_phy_anfc_0.083deg_P1D-m` is **not**
  the substitute — it carries `zos`/`tob`/`sob`/`mlotst` and sea ice but not
  `thetao`/`so`/`uo`/`vo`. The per-variable daily datasets
  (`...phy-thetao...`, `...phy-so...`, `...phy-cur...`, all 50-level) are.
- The join half of the objection is **fixed** (see §1's retrain entry); only the
  cost question is open.

---

## 3. Drift: the field ships, the trajectory does not

The combined drift field ships (2026-08-14): `u_total = u_curr + u_stokes +
alpha * u_wind` through `vector_source`, with `alpha` a named object preset
rather than a constant, one map layer per preset, and coverage taken as the
intersection of the two water terms. See CLAUDE.md for what is load-bearing.

**Trajectory integration is the architectural jump, and it is the half that is
left.** Roadmap framings that call drift one feature miss this:
`VectorFieldParticleLayer` advects against a **single snapshot texture** — every
particle sees the same instant forever, which is correct for an animated
streamline and wrong for a drift forecast, where a 48-hour trajectory must cross
48 hours of changing field.

- That needs a time-indexed stack of textures with interpolation in the update
  pass, or a server-side integrator returning a polyline. **Prefer the
  server-side integrator**: it is testable against known drifter tracks, and a
  trajectory is a *result* the user wants to export, brief on and compare — not
  a visual effect.
- **State the uncertainty or do not ship it.** A single deterministic track
  reads as a prediction of where the object *is*. Operational SAR drift is run
  as an ensemble over perturbed start position, `alpha` and field error, and
  what is drawn is a probability envelope. A lone line on a map, in a product
  someone might actually search from, is the most dangerous thing in this file.
- The live field's wind term is observation-only until `wind_u`/`wind_v` train
  (§1), so there is no forecast drift horizon yet.

### Verify the particle animation in a real browser

Everything up to and including the texture and its sampling math is verified
against live data — `tests/test_vector_field.py` reimplements the shader's
`fieldUV()` in Python and asserts the encoded texture decodes back to the input
velocity, and the live fetch was checked against known features (Gulf Stream
1.44 m/s NE, Agulhas 0.54 m/s SW, no data below 80°S). **The moving pixels
themselves have not been seen.** Browser tabs driven from the agent harness are
always hidden, so `requestAnimationFrame` never fires, the map never initialises
and every animation freezes — a limitation of the harness, not evidence of a
problem. Needs one human look at `/map`.

Worth checking at the same time: **several particle systems running at once** on
a mid-range GPU. There are now seven possible flow layers (wind, currents,
Stokes, four depth levels, three drift presets), each an independent
`requestAnimationFrame` + `map.redraw()` loop with its own trail framebuffers at
drawing-buffer resolution, and nothing coordinates them.

---

## 4. From variables to events — the missing stage

> The platform serves 32 variables. It does not say **what is happening**.

The framing worth keeping is **observe → detect → explain → predict → decide**:
it says what each existing subsystem is for (map/downloader observe, forecasting
predicts, SHAP explains) and names the stage missing entirely — **detect**.

### The prerequisite nobody costed: there is exactly one climatology

`services/crw.py` (NOAA Coral Reef Watch) carries the only real climatology in
the codebase, and it is **SST only**. That is why bleaching risk, heat-stress
extent and SST anomaly are possible at all — and it is also why *nothing else*
can have an anomaly.

It is a hard prerequisite hiding under at least four proposed features, each of
which would otherwise discover it independently:

- **An anomaly explorer** ranking "SST +2.7σ, chlorophyll +2.1σ" needs a
  per-cell, per-day-of-year baseline **distribution** for every variable ranked.
- **Polygon/regional seasonal anomalies** (§5) need the same thing, which is why
  that item already stalls on it.
- **Marine heatwaves** need more than a mean: the Hobday definition is a
  **90th-percentile** threshold over a 30-year daily baseline, exceeded for ≥5
  days. CRW's is a climatology of means, so even the one variable with a
  baseline does not have the *right* baseline.
- **Cold spells, extreme-wave events and low-oxygen events** are all
  percentile-relative by definition and inherit it exactly.

**Build the climatology as its own item**, scoped honestly: an offline job
against the expensive global fetch path (§1 — ~35 min per fetch window,
independent of output resolution), over enough years to make a percentile mean
something. It is not a UI feature and must not be scheduled as one. The output
is a per-variable, per-cell, per-day-of-year percentile stack on disk, in the
same shape as the forecast grids so `field_sampling.py` serves it unchanged.

**Consequence: an anomaly explorer is not a first item**, despite being the
obvious headline. The detectors that need no climatology come first.

### Detectors affordable now, because they need no climatology

- **Eddy detection** from sea-level anomaly + currents. `sea_level_anomaly` is
  trained and shipped (h1 +0.367, h3 +0.394, both 0/5 folds negative) and the
  currents fields are live and gridded. Okubo-Weiss or the closed-SSH-contour
  method identifies them; radius, polarity and intensity fall out of the same
  pass. **Age and trajectory are a separate, harder half** — a frame-to-frame
  assignment problem, where an eddy that flickers identity between timesteps
  produces a "trajectory" that is an artefact of the matcher. Ship detection
  first, tracking second, and validate tracking against a published eddy atlas
  rather than against how plausible the tracks look.
- **Upwelling detection.** Alongshore wind stress → Ekman transport,
  corroborated by the SST-down/chlorophyll-up signature. **Blocked on
  `wind_u`/`wind_v`** (§1), and it also needs coastline geometry to resolve the
  alongshore component, which no current service provides. High local relevance
  (Somalia/Oman/southwest India), and it produces the chain the platform is
  otherwise missing: **upwelling → productivity → chlorophyll → habitat
  suitability → fisheries**.
- **Marine heatwaves, properly.** Needs the SST percentile climatology above,
  which is the *cheapest* instance of that project since CRW already supplies
  the field and the coverage — so doing MHW first is also the pilot for the
  climatology job. The existing maskings in `crw.py` are load-bearing and apply
  unchanged: aggregate over 60°S–60°N or ice-margin cells triple the mean.

**Do not put cyclones, storm surge or coastal flooding in the first event
list.** No cyclone track source is integrated (IBTrACS/IMD/JTWC are all external
and unwired), and `tidal_height` is `available: false` with no global source. An
event list that silently omits the events a user most expects is worse than a
shorter list that says what it covers.

### Suggested order

1. **`wind_u` / `wind_v` training runs** (§1) — already the bottleneck for three
   things.
2. **Eddy detection**, detection only.
3. **The climatology job**, piloted on SST.
4. **Marine heatwaves** on that pilot, then **upwelling**.
5. **Anomaly explorer**, once the climatology covers more than one variable.

---

## 5. Feature candidates, surveyed and kept

Ordered by value per unit of work. Each was considered against the codebase
rather than brainstormed.

### Alerts you can subscribe to — the real product gap

The dashboard already computes threshold alerts over real fields, and
`services/feedback.py` already sends mail through Gmail SMTP. What is missing is
the noun: *"watch this point, tell me when bloom risk at +3d crosses 0.4"*.

The persistence decision is **already taken** — `app/models/chat/session.py` is
the codebase's first DB-backed feature — so this follows it rather than forcing
it. Scope it as subscription rows, a scheduler job evaluating them against the
caches that already exist, and an unsubscribe link.

Traps worth writing down before anyone starts:

- **An alert is a claim.** Everything in `services/dashboard/` is careful to say
  its alerts are threshold rules over model fields, not issued warnings. An
  email is read far from that disclaimer, so it has to carry it.
- **The bloom model's +7d precision is 0.202.** Emailing week-ahead bloom alerts
  at four-in-five false would train recipients to ignore the +3d one that is
  actually useful. If alerts ship for HAB, they ship at +3d.
- **Reuse `client_id`, but not naively.** It is a browser-generated UUID that
  scopes a person's own history and is explicitly *not* access control. A
  subscription raises a stake a transcript does not: it carries an email
  address, and a guessable-UUID-scoped table that can be made to send mail to an
  address of the caller's choosing is a spam relay. Creation must confirm the
  address (double opt-in) and every message must carry a signed unsubscribe
  token independent of `client_id`.
- **Polygon triggers are a later increment.** A pin plus a threshold is
  evaluable directly against the cached global fields. A polygon needs a
  reduction decided per rule — mean, max, or area-over-threshold are three
  different alerts and users will assume whichever one confirms their fear. Ship
  the point trigger; when polygons arrive, name the reduction explicitly and
  reuse `DrawableAreaMap` rather than building a second drawing surface.
- **Webhooks are not a free second channel.** Outbound POSTs to user-supplied
  URLs make the backend an SSRF vector against its own network, and they need
  retry/backoff and a dead-letter path that email does not. Email first.
- **The scheduler job must not fetch.** Everything it needs is already cached.
  An evaluation pass that triggers upstream fetches turns N subscriptions into N
  Copernicus reads and will blow the same quotas a training day was already lost
  to.

### Union GBIF with OBIS

Measured 2026-08-05 and still the biggest cheap win for the habitat model: **3–6x
the tuna labels inside the existing 2000–2013 window**.

| species | 2000–2013 OBIS | 2000–2013 GBIF |
| --- | --- | --- |
| *Thunnus albacares* | 394 | **1228** |
| *Katsuwonus pelamis* | 280 | **1622** |
| *Thunnus obesus* | 283 | **678** |
| *Rastrelliger kanagurta* | **67** | 9 |
| *Sardinella longiceps* | **112** | 9 |

Two conclusions, both load-bearing:

- **It must be a union, not a switch.** GBIF dominates for the three tunas;
  OBIS dominates ~10x for Indian mackerel and oil sardine — the two species that
  matter most for Indian coastal fisheries. Dropping OBIS for GBIF would gut
  exactly the local species the model exists to serve.
- **It needs dedup** on `occurrenceID`, falling back to (dataset, catalogNumber,
  lat, lon, date). Much of GBIF's marine holdings are OBIS datasets
  republished, so merging naively double-counts precisely where the
  pseudo-absence scheme is most sensitive to sampling effort.

It does **not** extend the window: the post-2014 drought is real in both sources
(bigeye, 4 records either way). Do it when the habitat pipeline is next touched,
since it changes labels and wants a retrain anyway.

### True absences — the biggest accuracy lever, and a strategic call

ICES DATRAS (trawl surveys with real zero-catch hauls) and RLS (standardised
reef transects with abundance and real zeros) are the only true-absence sources
found in the 2026-08-05 survey. They would remove pseudo-absences entirely,
which is worth more than any change to the classifier — `fish_habitat` only
draws a target-group background because nothing else was available.

The catch is geographic: DATRAS is North Atlantic/European and RLS is reef
transects. Adopting either **relocates the habitat model out of the northern
Indian Ocean**, which is the platform's reason for existing. So this is a
decision about what the product is, not a data-ingestion task, and it should be
taken as one. A defensible middle path is a *second* model in a DATRAS region,
kept beside the regional one as evidence of how much the pseudo-absence scheme
costs.

### ConvLSTM / U-Net for spatial forecasting

**The argument is architectural, not decorative.** `grid_predictor` scores every
cell **independently** — it loops cell by cell through the point pipeline,
deliberately, to avoid train/serve skew. The consequence is that the model
cannot see spatial structure at all: not an eddy, not a front, not the shape of
a bloom. A gradient-boosted tree over per-cell features is structurally blind to
the neighbourhood, and that is a real gap a convolutional model fills.

- Baseline to beat is strong and measured: delta-target LightGBM at skill +0.20
  vs persistence. **Trees beating neural nets on tabular data is the norm** — the
  claim to make is "DL where trees are provably blind (fields), trees where they
  win (points)", not "DL is better".
- **Start with U-Net segmentation of HAB bloom extent** over chlorophyll fields:
  contained, and 3.9M labelled rows already exist. ConvLSTM grid-to-grid
  forecasting is the bigger version and directly extends the forecast map.
- Cost: the gridded training data is the expensive part (~35 min per fetch
  window, resolution-independent). Budget for that before any modelling.
- MLflow exists, so "did it help?" is now answerable. That was the blocker.

### Smaller things considered and not done

- **A saved-locations workspace.** Everything is ephemeral today; the Zustand
  `persist` pattern already exists for preferences and the persistence decision
  is taken. Two increments, and only the first is small: saved *points* are a
  table and a sidebar; **polygon-clipped statistics are a different feature** —
  a clipped seasonal anomaly against a baseline means choosing a reduction *and*
  a climatology, and there is only one climatology in the codebase (§4).
- **A *regional* brief.** `services/brief.py` + `brief_pdf.py` ship a point
  brief and `services/compare.py` ships a two-point comparison. Extending to a
  bbox is mostly the same document over reduced fields — and inherits the same
  reduction question as polygon workspaces, so do them together or not at all.
- **ARGO float profiles**, for model bias correction. NDBC is in
  (`services/ndbc.py`); ARGO is the subsurface counterpart and nothing reads it.
  It is the only in-situ source that could validate the depth-resolved variables
  (`water_temperature`, `water_salinity`, `currents_depth`), which today are
  served and forecast with **no independent check against an instrument**. Scope
  it as validation first and bias correction second — correcting a model against
  floats before measuring the offset is how a bug becomes a feature.
- **"Why?" for derived indices.** `forecasting/shap_explainer.py` exists and the
  metric pages render an Explainability section. The gap is that **HAB risk and
  habitat suitability have no SHAP path** — the two things a user most wants
  explained are the two that cannot answer.
- **Ocean heat content as a map field.** The four charted layers ship (0-50 /
  0-100 / 0-200 / 0-700 m). A *field* is a different cost class: it needs the
  global depth-resolved temperature fetch, which is §1's fetch path, not a
  series call. Do it as a grid build, not as a dashboard change.
- **Per-model-member MLflow tracking** for the habitat ensemble. Both pipelines
  currently log a single run per invocation (one per horizon for HAB). Natural
  extension, nothing blocked on it.

### Reviewed and rejected, with the reason

Recorded so these are not re-proposed:

- **A Fishing Opportunity Index** (one number from habitat + SST + chlorophyll +
  vessel activity). Composite indices with hand-chosen weights have nothing to
  validate against — the habitat model has a holdout TSS of 0.792, an FOI has no
  ground truth at all. Folding in GFW vessel activity also makes it circular
  ("fish are where the boats are") and turns an environmental product into an
  effort-disclosure one. **Ship the components side by side.**
- **Maritime route optimisation.** A different product — routing graph, land
  mask, traffic separation schemes, a vessel performance model — and a liability
  surface far past a dashboard if anyone navigates by it. The honest 10% version
  is **conditions along a route the user supplies**: no optimisation, no
  recommendation, and every field it needs already exists.
- **Scenario simulator ("what if SST +2 °C, wind −15%?").** This asks a LightGBM
  model fitted on observed covariance about a joint state it has never seen, and
  it will answer confidently and meaninglessly — extrapolation off the training
  manifold, presented as prediction. SHAP already provides the defensible
  version: local sensitivity, in-distribution.
- **"Ocean digital twin."** A renaming of what the platform already is.
- **An ocean time machine scrubbing 2000–2026.** Rejected on cost being
  mis-stated as a slider. Global fields are ~35 min per fetch window and ~70 MB
  per timestep per variable; a scrubbable multi-decade global map is a
  **precomputed tile archive**, not a UI control. The affordable version is
  precomputed coarse monthly or annual means for a few variables. The forecast
  horizon animation already shipped, so the control exists — it is the history
  behind it that is unaffordable.
- **"Open marine data API."** The API already exists (~40 endpoints; it is how
  the frontend works) and `services/rate_limit.py` is there. What is proposed is
  documentation, versioning and a stability contract — worth doing only when
  there is an actual external consumer, since a public contract is a promise not
  to change things and this codebase still changes weekly.
- **"RAG over ocean data."** A category mismatch: RAG retrieves from
  unstructured text, and this platform's data is numeric grids and time series.
  You do not retrieve SST, you query it. The catalog version shipped as
  prompt-stuffing (`services/chat/catalog_context.py`, ~900 tokens derived from
  the registries) — standing up a vector store for ~36 records was the trap.
  **Scientific literature on HABs and the target species is the one legitimate
  RAG target left**, and it is a separate ingestion project that does not touch
  the platform's own data path. Treat it as its own effort, not as a chatbot
  feature.
- **A vector database, generally.** See above and the deferred list below.

---

## 6. Platform, structure and presentation

Requested 2026-08-14, worked 2026-08-15. Most of it shipped; what is left below
is what is genuinely still open, with the measurement that made it a decision.

Two of the nine conflicted with decisions already recorded here. Both were
narrowed rather than reversed, and the narrowing is described where it landed.

### 6.1-6.7 — shipped

| | outcome |
|---|---|
| 6.1 observability | `app/core/logging.py` + `middleware.py`. See the finding below — it was not a feature request, it was a bug. |
| 6.2 globe click | Rotates toward a clicked point out near the limb. Rotation only, globe only, past a screen-space threshold. |
| 6.4 field documentation | Two chapters in a new "Ocean & atmosphere" docs group. |
| 6.5 backend strays | `test.py` (0 bytes), `others/`, `dependencies/` gone; runtime state moved to `backend/data/`. |
| 6.6 README | Rewritten. It described the product as "a single interactive map". |
| 6.7 branches | 8 remote branches to 1. The prototype is preserved as tag `prototype-2026-07`. |

**The observability finding is worth keeping even though the work is done.**
Two logging systems had grown side by side — loguru in 13 modules, stdlib
`logging` in 31 — and *nothing in the server process configured either*:

    logging.getLogger("services.forecast_tiles").isEnabledFor(logging.INFO)  -> False
    logging.getLogger().handlers                                             -> []

So every `logger.info(...)` in 31 modules was discarded at source, including
most of the forecasting engine and the whole chat agent, while `WARNING`+
survived only through `logging.lastResort` as bare unformatted stderr text. The
lesson generalises: **this codebase's silent failures need the log to be the
mitigation**, since the caches are fire-and-forget tasks whose exceptions
asyncio swallows. If a second logging library ever appears, it has to route into
the configured one rather than sit beside it.

### 6.5 — the part deliberately not done: regrouping `services/`

Measured before deciding: the 31 flat modules under `services/` are referenced
from **222 import sites** across routers, services, tests and scripts, several
of them grouped `from services import (a, b, c)` blocks that would have to be
split across whatever new packages they landed in.

Against that cost, the taxonomy is genuinely arguable — `forecast_tiles` is as
much delivery as it is a derived field — and CLAUDE.md currently documents the
flat layout as the convention. A large, history-obscuring rename that imposes a
debatable grouping over a documented one is a bad trade, so it was not done on
momentum. If it is ever taken up: one mechanical commit, no behaviour change,
prose updated in the same commit, and settle the taxonomy first.

Likewise **`models/` was not renamed** despite genuinely colliding with
`app/models/`. It holds 114 trained models and 8 grids, is untracked, and
represents hours of training; the README's structure listing now disambiguates
the two, which buys most of the clarity for none of the risk.

### 6.3 / 6.8 — motion foundation shipped, application half open

Shipped: a motion budget in `styles/tokens.css` (four durations named by what
the motion is *for*, plus an entrance easing), `useReveal` promoted out of
`pages/landing/` into `hooks/`, the `.ma-reveal` utility, and both applied to
the compare page along with a real loading state.

What is left is applying it, and the **no-go list is the important half** —
all three were paid for once:

- **Never wrap the `/map` route in a keyed animated wrapper.** A remount
  destroys and rebuilds the MapLibre WebGL context and discards the layer state
  `mapPreferencesStore` exists to preserve.
- **No JS mount animation on dashboard panels.** `AnalyticsGrid`'s `LazyMount`
  decides what to render by *measuring geometry*, and Recharts' entry animation
  is already disabled for starting before `ResponsiveContainer` settled its
  width. An animation that moves and rescales the thing being measured, as it is
  measured, is the same hazard. Hover is safe.
- **Reduced motion resolves to the finished state**, never to a faster
  animation.

Remaining targets, none of which touch the above: the dashboard's range-change
transitions, the map's layer picker, and the metric pages' chart swaps.

Also worth measuring before adding more JS: **native CSS scroll-driven
animations** (`animation-timeline: view()`). They run off the main thread, need
no library, and degrade to "already visible" where unsupported — which is the
same resolution reduced motion already takes.

### 6.9 "Awwwards-level UI/UX" — still open, and still a standard rather than a task

The motion budget above is the first of its criteria. The rest needs deciding
rather than doing, and it collides with three rules this codebase holds
deliberately: no UI kit or CSS framework outside `features/dashboard/`; one
place chooses a colour (`styles/tokens.css` exists because seven private
palettes had drifted into four dark canvases and two accents); and reduced
motion resolves to the finished state.

It also collides with something more important than any of them: **this
product's distinguishing property is that it never substitutes a number for
missing data.** Award-site polish trends toward decorative confidence —
skeletons implying data is coming when the cache is cold, animated counters on
estimates, "94% confident" chips. The dashboard's three-way `ready` / `warming`
/ `unavailable` and the refusal to invent a "Confidence: 91%" are the standard
to hold; a redesign that softens them is a regression however good it looks.
The compare page's loading state is the shape to copy: it says what is happening
and why it takes time, and does not draw a ghost of a table whose shape is
exactly what the request is still deciding.

To make it actionable:

- **Three surfaces carry the product**: the landing page, `/map`, `/dashboard`.
  Everything else can follow.
- **Criteria, not vibes**: one type scale used everywhere (the tokens exist —
  audit for literals that bypass them); a real empty / loading / error state for
  every panel, since that is where this app is unusually honest and unusually
  plain; contrast floors that the map ramps already meet (>=3:1 against the
  Abyss basemap, >=2:1 for the hatched unforecastable mark) applied to the
  chrome too.

### Still unverified in a browser

The globe recentre, the drift layers and the particle animations have never
been *seen*. Browser tabs driven from the agent harness are always hidden, so
`requestAnimationFrame` never fires, the map never initialises and every
animation freezes — a limitation of the harness, not evidence of a problem.
One human look at `/map` covers all of them, and should also check several
particle systems running at once on a mid-range GPU: there are now seven
possible flow layers, each an independent `requestAnimationFrame` +
`map.redraw()` loop with its own trail framebuffers, and nothing coordinates
them.

---

## Bugs and correctness

### Circular variables — the modelling half is still open

`current_direction`, `wind_direction` and `wave_direction` are degrees on 0–360.
Everything between the trained model and the screen is fixed (2026-08-13):
sin/cos resampling recombined with `atan2`, a signed veer wrapped to [−180, 180)
for `change` mode, a cyclic ramp on the true 0–360 domain, and `circular` living
in exactly one place (`VariableInfo` in the download registry, inherited by
`VariableConfig`).

**The model itself is still linear.** With `target_mode: delta` the target is
the *change* in degrees, so a 5° veer across north trains as −355. The fix is to
predict components and derive the angle, which is what `current_u`/`current_v`
already do — and why the currents *particle* layer was never affected. That
makes `current_direction` and `wind_direction` derived fields rather than
trained ones, and it is waiting on the same `wind_u`/`wind_v` run as everything
else in §1.

### Fish-habitat ensemble — stacking was never attempted

Fixed 2026-08-13 by weighting members with a **softmax over CV TSS** at
temperature 0.05 rather than proportionally; the ensemble is finally above every
member (0.792 against LightGBM's 0.788). **The cost is real and is why the
temperature is a named constant:** Boyce falls 0.936 → 0.905, so the old
ensemble was the better spatially *calibrated* surface (still better than
LightGBM alone at 0.895). `proportional` is kept so the earlier baseline
reproduces exactly.

Open: **stacking on out-of-fold predictions** is the more principled version and
was not attempted.

### HAB t+7 sits at the edge of usefulness

At the 0.8-recall operating point: precision 0.202, false-alarm rate 0.798 —
four of every five alerts are false. Defensible for a screening tool where a
miss costs more than a false alarm, and **recorded as a decision rather than
left implicit**: the layer is named `Bloom Risk (+7d, screening)` and its
attribution carries the per-horizon operating point (+3d 0.449 / +5d 0.280 / +7d
0.202) with an explicit "use it to decide where to look, not that a bloom is
happening".

Not a bug. Listed because it constrains anything built on top of it — see the
alerts item in §5.

### Rejections to respect, not retry

Do not blindly retrain these expecting better. A horizon ships only if **overall
skill > 0 AND at most 1 of 5 folds is negative**; the second clause is
load-bearing, and *six* of the rejected horizons print `beats persistence` on
the aggregate line the training log shows.

- **`sea_surface_salinity` — dropped entirely.** h3 −0.152, h7 −0.118; the
  passing horizons were inside fold noise.
- **`water_salinity` h3/h7 deleted, h1+h30 kept.** Same physics, different
  evidence: its h1 is +0.179 with 0/5 folds negative and tightly clustered
  (+0.110..+0.225), against surface salinity's noisy +0.085.
- **`bottom_temperature` h1 only.** h3 −0.056, h7 −0.060, h30 −0.025 (4/5 folds
  negative). "Forecastable a day out, not beyond" is the honest claim.
- **`humidity` h1 deleted.** −0.020 with 2/5 folds negative (one at −0.435).
- **`nitrate` h3 deleted.** +0.050 on the mean, folds spanning −0.123..+0.208.
- **`sea_level_anomaly` h7/h30 deleted.** Both printed `beats persistence`
  (+0.073, +0.111) with **2 of 5 folds negative**. The cleanest demonstration in
  the repo of why the second clause exists.

Weakest thing kept: `diffuse_attenuation` h3 at +0.026 (1/5 negative). Revisit
it first if the bar is ever tightened.

### Hazards that will bite the next person

- **Partial success is the more dangerous failure mode.** Training the full
  variable set in one day exceeds Open-Meteo's free quota. When it blew,
  `sea_level_anomaly` failed *loudly* (all 24 points gone → hard error, nothing
  written) while `rainfall` **degraded silently** — enough points survived to
  train, but only 10 of 24 and every one northern-hemisphere, with a different
  subset per horizon. A global model carrying lat/lon as features and no
  southern data extrapolates across the equator on the one variable whose
  seasonality inverts. **Check `skipped_points` before shipping, not just the
  metrics.** Spread Open-Meteo variables across days, or use a paid key.
- **Widening what the model is shown widens what it is allowed to say.**
  `agent._ungrounded_numbers` permits every figure the model was shown, which
  includes the system prompt. Adding the dataset catalog there made
  `GLOBAL_ANALYSISFORECAST_BGC_001_028` parse as the numbers 1 and 28, so a
  fabricated "28.4 °C" traced back to a product code and passed the check — a
  safety check that failed by going quiet. Fixed with `_quantities()` (a digit
  run preceded by a letter, underscore or dot is a name, not a measurement).
  Any future addition to `_SYSTEM_PROMPT` or a tool description is also an
  addition to the permitted set: **check the negative case after adding prompt
  context.**
- **ERDDAP hosts flap, and a 404 is not proof of permanence.** NOAA CoastWatch
  went fully 503, and `NOAA_DHW` and `GEBCO_2020` each 404'd for ~100 s before
  returning to 200 — ERDDAP answers 404 "Currently unknown datasetID" while
  reloading a dataset, indistinguishably from a removed one. Hence
  `history.is_retryable` retries 404 exactly once. **Do not "fix"
  `services/crw.py`'s `NOAA_DHW` id**; switching to a `_Lon0360` dataset would
  silently change the longitude convention of reported coordinates while the
  query kept working.

---

## Documentation drift

- CLAUDE.md's forecast-map section no longer quotes a grid count and says to
  count the directory instead. Keep it that way — the number moves with every
  `--all` run.

---

## Deferred / considered and rejected

- **A database for caching.** Every in-process cache is already bounded with
  eviction; the on-disk fetch cache is 4.6 MB. Memory was concentrated in a few
  global float64 arrays, addressed directly (SST cache: ~140 MB → ~35 MB via
  float32 plus removing a duplicated array). Redis/Mongo would relocate those
  bytes while adding a second resident copy plus serialization on the hot path.
- **A database for the ML feature store.** Parquet is the correct technology for
  wide float matrices: the store is 3.9M rows × 151 columns at 1.59 GB, and a
  20-column read costs 0.1 s / 1.08 GB against 3.5 s / 2.82 GB for the full
  table. Row stores read all 151 columns to serve 12. If it outgrows one
  machine, DuckDB reads these same files in place with no import step.
- **Postgres for persistence** remains genuinely open, but for *records* rather
  than cache or features: download history/audit, feedback (currently
  `feedback_log.jsonl`), and the KPI ring buffer that does not survive restart.
  Chat sessions are already there and are the reference implementation.
