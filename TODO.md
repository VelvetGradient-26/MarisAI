# TODO

Open work only. Items are removed from this file when they ship — what survives
a deletion is the *finding*: a measured number, or a decision with the reason
attached, kept so it is not re-derived or re-litigated. Sections are ordered by
what unblocks the most other work, not by size.

Numbers here were measured, not estimated. Re-verify before relying on any of
them if it has been a while.

---

## 1. Machine time — done, and what the runs settled

Everything this section tracked has now run. What survives is the findings, per
this file's own rule.

**Verified on disk 2026-08-17, not read off this document:** 28 forecast grids
exist; the only 5 trained variables without one are the Open-Meteo point-API
variables `grid_history.ungriddable_reason` already refuses, so the `--all`
build is complete. **0 grids are stale** against their models (every `_grids/*.nc`
mtime compared against the newest `trained_at` across its horizons). Count the
directory, never a number in a document.

### What the `wind_u`/`wind_v` grids unblocked — and one thing they did not

Both variables ship at all four horizons, 0 of 5 folds negative everywhere:

| | h1 | h3 | h7 | h30 |
| --- | --- | --- | --- | --- |
| `wind_u` | +0.217 | +0.301 | +0.385 | +0.398 |
| `wind_v` | +0.300 | +0.366 | +0.398 | +0.450 |

Forecast wind particles ship. Both grids carry **no covariates at all** —
`pressure` and `air_temperature` are Open-Meteo, so no global field for them can
exist — and `missing_covariates` names them in the layer attribution, because
LightGBM routes an absent feature down its missing-value branch without
complaint and the map would otherwise look exactly as confident as a complete
one.

**Upwelling was never actually blocked on this run, and that was a mistake in
this file.** What upwelling needs is wind *components*, because a bearing cannot
be projected onto a coastal normal — and `copernicus_wind.snapshot()` has
exposed live `u`/`v` all along, for `services/drift.py` to sum. The training run
produced *forecast* grids, which is a different thing and the wrong footing for
a detector claiming to say what is happening now. Shipped 2026-08-17 reading the
live caches. The lesson generalises: check what a dependency actually needs
before recording it as blocked.

Still genuinely waiting on those grids: **a forecast drift field** (the live
field's wind term is observation-only), and the **circular-variable modelling
half** below.

**The partial-success hazard fired again**, exactly as this file predicts. A
`wind_v` h1 first trained on **21 of 24 points** — Open-Meteo 429'd for three
sites — and printed `beats persistence` regardless. **Read `skipped_points` in
`metadata.json` after every run**; the aggregate line will not tell you.

### The 13 mixed-cadence variables — retrained, and it changed almost nothing

`cleaning.py` merged providers and *then* resampled, so an hourly covariate
paired with a daily target survived as its 00:00 sample standing in for a
24-hour mean — on a synthetic 3 degC diurnal cycle the old path returned **23.0
where the daily mean is 20.0**. Fixed 2026-08-13 by reordering to resolve codes
-> aggregate per provider -> merge.

**Skill then moved by less than +/-0.03 everywhere, in no consistent direction**
(worst: `chlorophyll_a` h30 -0.028, `nitrate` h7 -0.030). This does not make the
fix wrong — the old path provably misrepresented a daily mean by the full
diurnal amplitude — but it answers "how much was riding on it": on these series,
the difference between a covariate's daily mean and its midnight sample does not
propagate into forecast skill. Worth knowing before budgeting a retrain against
a similar find.

**The rejections reproduced, which is the more interesting half.** A retrain
trains every *configured* horizon and has no concept of rejection, so the batch
silently resurrected six horizons deleted on their own merits — and all six
failed again with the same signature. So the 2026-08-10 rejections were signal,
not fold noise. `scripts/apply_shipping_bar.py` now makes that check mechanical:
it reads `metrics.json` rather than the aggregate log line, and **moves** failures
to `_rejected/<date>/` because the artifact is the evidence for the decision.
Run it after every batch retrain; nothing else catches a resurrected horizon.

### The HAB regions — all four run, and base rate does not explain the Arabian Sea

All of `california_current`, `benguela`, `baltic_sea` and `bay_of_bengal` are
trained and shipped beside the `arabian_sea` control. Thresholds and climatology
stay fitted **per region** — they define what counts as a bloom, and one
region's distribution must not set another's labels.

**Held-out, at the 80%-recall operating point:**

| region | base rate | t+3 precision | t+7 precision | t+7 PR-AUC | persistence | t+7 lift |
| --- | --- | --- | --- | --- | --- | --- |
| arabian_sea (control) | 0.076 | 0.449 | 0.202 | 0.362 | 0.309 | +0.053 |
| bay_of_bengal | 0.078 | 0.461 | 0.187 | 0.365 | 0.215 | **+0.150** |
| baltic_sea | 0.139 | 0.699 | 0.416 | — | — | — |
| benguela | 0.154 | — | 0.566 | 0.705 | 0.594 | +0.111 |
| california_current | 0.266 | — | 0.844 | 0.884 | 0.808 | +0.076 |

**The bay_of_bengal run settled a question the earlier three left open.** With
three regions it was reasonable to read the whole spread as prevalence: California's
alert is right 84% of the time against the Arabian Sea's 20%, and California's
base rate is 3.5x higher. The Bay of Bengal breaks that reading — **the same base
rate as the Arabian Sea (0.078 vs 0.076) and roughly 3x the lift** (+0.150 vs
+0.053 at t+7; +0.225 vs the Arabian Sea's weakest at t+3). A neighbouring basin
at identical prevalence forecasts substantially better.

So the two framings are still both needed — **a user experiences precision**,
four-in-five false alarms being unusable however good the lift, while **a
modeller has to judge lift** because a high base rate makes precision cheap — but
the conclusion sharpens: **the Arabian Sea is genuinely the hard region, not
merely the low-prevalence one.** Whatever makes it hard is physical rather than
statistical, and that is now a question worth asking rather than an artefact to
explain away.

Consequence for the alerts item in §5 stands and is now per region with evidence:
"if alerts ship for HAB, they ship at +3d" was the Arabian Sea's rule. A +7d
California alert at 0.844 is a defensible product; a +7d Arabian Sea alert at
0.202 is not; the Bay of Bengal at 0.187 is not either, despite forecasting
*better* than the Arabian Sea — which is precisely why precision and lift have to
be quoted together.

**HAB stays multi-region rather than global on arithmetic**: the same six years
worldwide at 0.25 degrees is ~1.6 billion rows and **~650 GB**, most of it
open-ocean rows that are near-constant negatives. The disk constraint this file
recorded (13 GB free) is stale — there is 121 GB as of 2026-08-17.

### The global PFZ model is **worse over the Indian Ocean** — measured 2026-08-15

Settled, and the answer is the one the item was worried about. Scored on
**identical rows** (the regional model's own spatial-block holdout, 885 rows /
167 presences):

| | TSS | PR-AUC | ROC-AUC | Boyce |
| --- | --- | --- | --- | --- |
| regional model | **+0.798** | **+0.804** | **+0.945** | **+0.923** |
| global model | +0.448 | +0.489 | +0.790 | +0.721 |

Not close, and not a rounding difference: the global model loses 0.35 TSS on the
water this platform exists for, despite training on 123,104 rows against the
regional model's 1,902. **The regional models stay the baseline and the served
artifact.** Going global buys ~170x the labels and spends it on the wrong ocean.

Two things make the comparison trustworthy, and both had to be built —
`scripts/validate_global_on_region.py`:

- **The two shipped reports could not answer this.** Each model's holdout is its
  own spatial block of its own store; two numbers from two different sets of
  water are not a comparison.
- **The shipped global model was trained on this water**, so scoring it directly
  would have measured memorisation. The script refits the global ensemble with
  the regional holdout's **spatial blocks** removed from the global training set
  — blocks, not matching rows, because a global point 50 km from a held-out
  regional point is the same water. 217 of 123,321 global rows fall in those 15
  blocks, so the global model keeps essentially all its data and still loses.

Worth keeping: the global ensemble's *members* disagree about how they fail —
maxent holds Boyce at 0.938 (better than the regional ensemble's 0.923) while
scoring TSS 0.449. It ranks this water plausibly and discriminates in it badly.

---

## 2. The daily-Copernicus question — settled 2026-08-15: **do not swap**

Measured through `copernicus.fetch_global` (the real path, not a lazy array),
one global surface field strided to 1°, on a 10-day window:

| | s/timestep | a 45-day grid window |
| --- | --- | --- |
| hourly physics (`PT1H-m`), thetao+so | **0.89** | 1080 reads = **15.9 min** |
| daily thetao (`P1D-m`), depth-bounded | **1.16** | 45 reads = **0.9 min** |
| daily thetao, *no* depth bound | 8.63 (2-day window) | 45 reads = 6 min |

So the daily product is **~18x cheaper for a global window, not ~40x**, and the
hourly path costs ~16 min rather than the ~35 min on record. **Every earlier
figure in this section was wrong**, in both directions: hourly was recorded at
34–46 s/timestep and is 0.89; daily was recorded as *slower per read* and is
1.16. A short window is dominated by per-request overhead (the same daily read
measured 3.89 s/timestep over 2 days and 1.16 over 10), which is how a probe
produces a number that reverses the ranking. The depth-bound trap is real and
confirmed: omitting it costs **2.2x** on a 50-level dataset.

**The swap is still rejected, on grounds cost does not settle:**

- **It would cost the downloader its hourly cadence.** `Resolution.hourly` is a
  live API option, and the seven variables on `copernicus_physics` (SST, SSS,
  SSH, all four current fields) can serve it only because their provider is
  hourly. Repointing them at daily datasets removes a shipped capability to save
  15 minutes on an offline job that runs twice a day behind a 6-hour cache.
- **One provider would become three.** `thetao`, `so` and `cur` are separate
  daily datasets, and "one provider == one upstream dataset" is what keeps
  `catalog.py` honest about coverage windows.
- **An hourly source aggregated by `cleaning.py` is strictly more informative
  than a daily product**, now that aggregation happens per provider *before* the
  merge. It can answer a daily question and an hourly one; the daily product can
  only answer the daily one.
- **It would force a full retrain, not a partial one.** Seven variables change
  source, and everything carrying them as a covariate changes with them —
  otherwise the grid path and the point path disagree, which is exactly the
  train/serve skew `test_grid_matches_the_point_path` exists to prevent.

Revisit only if the grid builder becomes fetch-bound again (it is not: the wind
grids' fetch was a cache hit and the 25-minute cost was all cell loop), or if a
*new* variable needs a daily-only field, where the daily dataset is simply its
provider and none of the above applies.

The merged daily product `cmems_mod_glo_phy_anfc_0.083deg_P1D-m` remains **not**
the substitute — it carries `zos`/`tob`/`sob`/`mlotst` and sea ice but not
`thetao`/`so`/`uo`/`vo` — and is already the provider for `bottom_temperature`
and `bottom_salinity`, which is the shape of the "new variable" exception above.

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

## 4. From variables to events — the stage that was missing

> The platform serves 32 variables. It does not say **what is happening**.

The framing worth keeping is **observe → detect → explain → predict → decide**:
it says what each existing subsystem is for (map/downloader observe, forecasting
predicts, SHAP explains) and named the stage that was missing entirely —
**detect**. Three detectors now exist (eddies, marine heatwaves, upwelling) and
the prerequisite under four more is built. What is left is reaching them from
the UI, and tracking.

### The climatology — built 2026-08-17, and the cost was mis-stated here

`services/climatology/` now holds a per-cell, per-day-of-year **percentile**
stack; `services/crw.py`'s SST-only climatology of *means* is no longer the only
baseline in the codebase. This unblocks the anomaly explorer, polygon seasonal
anomalies, marine heatwaves (shipped, below) and every percentile-relative event.

**Two things this entry got wrong, both worth keeping:**

* **"An offline job against the expensive global fetch path" was the wrong
  costing, because that path cannot supply it at all.** Every Copernicus
  provider in `services/download/catalog.py` starts recently — physics
  2022-06-01, waves 2022-11-01, wind 2024-06-13, BGC 2021-11-01. A 30-year
  baseline is not expensive there; it does not exist. **NOAA OISST v2.1**
  (`ncdcOisst21Agg_LonPM180`, daily 0.25 degrees, 1981-09-01 onward) is on the
  same CoastWatch ERDDAP `crw.py` already uses. Measured 2026-08-17: one year
  strided to 1 degree is **94.6 MB in 51s**, so the standard WMO 1991-2020
  baseline is ~25 minutes and ~2.8 GB, not hours.
* **The archive is gappy and that is the archive, not the transport.** Whole-year
  requests return 365 days for 1991 and **163** for 1993. The first diagnosis was
  truncation under load — the host was flapping at the time — and it was wrong:
  re-fetching 1993 healthy returns the identical 163 days, and the dataset
  reports `evenlySpaced=false` over 15,210 values across ~16,400 days, i.e.
  **~1,200 days genuinely absent**, concentrated in the early record. The
  per-year completeness check written against the wrong diagnosis would have
  rejected a real baseline forever. What protects a percentile is a floor on
  samples per *estimate* — a day-of-year percentile does not care which years its
  samples came from — and the artifact records `baseline_completeness` so two
  builds can be compared.

Two constructions in the fit are load-bearing and silent when wrong: the
day-of-year index is **leap-adjusted** (pandas puts 1 March at 60 in a common
year and 61 in a leap one, so raw pooling aligns March with late February), and
the pooling window **wraps the year** (or its two ends are fitted from disjoint
samples and disagree exactly where the hemispheres are at their extremes).

**Extending it to a second variable is the remaining work**, and it is bounded by
source rather than by code: `build.py` is variable-agnostic, but OISST serves
SST alone, so every further variable needs a long-record source of its own.
Until then the anomaly explorer stays a one-variable feature, which is not worth
shipping — hence its position below.

### The detectors themselves — three shipped

- **Eddy detection — the detection half shipped 2026-08-15.**
  `services/eddies.py` + `GET /api/ocean/eddies` + an `Eddies (detected)` map
  layer. Okubo-Weiss (W < −0.2σ) over the live surface-current cache, which
  costs a numpy pass over a grid already resident rather than a second global
  fetch — `sea_level_anomaly` exists as a *forecast* grid, which is the wrong
  footing for a detector claiming to say what is happening now. Measured on the
  live field: **2,097 features globally**, densest exactly where they should be
  (Gulf Stream, Kuroshio at 35N/155E, Agulhas, the Somali Great Whirl at
  11.8N/47.8E), median radius ~55 km, whole pass **0.1 s**.
  - **The per-component loop is where the cost was**, and it is worth not
    reintroducing: `np.nonzero(labels == index)` per feature rescans the whole
    grid once per detection — ~2 billion comparisons at global scale, measured
    **37 s**. Sorting the labelled cells once and slicing costs 0.1 s for a
    bit-identical answer.
  - **Age and trajectory are the separate, harder half, and are still open** — a
    frame-to-frame assignment problem, where an eddy that flickers identity
    between timesteps produces a "trajectory" that is an artefact of the matcher.
    Validate tracking against a published eddy atlas rather than against how
    plausible the tracks look. Nothing in the service holds state between
    refreshes, deliberately, so tracking starts from a clean sheet.
  - Known and documented rather than hidden: the OW threshold is relative to the
    variance of the field in view, so this is a consistent detector and **not a
    census**; the ~0.25° grid sets the smallest resolvable feature (submesoscale
    is absent, not zero); the ±5° equatorial band is excluded because polarity is
    meaningless where f vanishes; and the derivative stencil loses coastal cells
    against the land mask, so nearshore eddies are under-detected. A strong jet
    can also merge into one 245-cell "eddy" at the 300 km cap — the Somali
    current does exactly this in the SW monsoon.
  - **On white noise the detector still returns features** — a relative
    threshold always has cells below it — but every one comes back at the 40 km
    floor. So a *large* detection is evidence of real structure while a small one
    may not be, and a test pins that asymmetry.
  - The point brief carries it too (`eddies.nearest` → a row in `_flow_section`):
    "inside an anticyclonic eddy, 244 km equivalent radius" at the Great Whirl,
    "nearest detected eddy 386 km away" in the open Arabian Sea. The distance is
    reported either way rather than the row omitted — a point far from every
    detection is an answer, and a missing row reads as "no eddies anywhere".
    `services/compare.py` picks this up for free, being a view over the brief.
  - Not yet done: closed-SSH-contour detection as a cross-check on the OW count,
    and validating the count against a published eddy atlas.
- **Upwelling detection — shipped 2026-08-17.** `services/upwelling.py` +
  `GET /api/ocean/upwelling`. Bakun's index: Ekman transport from bulk wind
  stress, projected onto the offshore normal. Reads the live wind and currents
  caches, so it is a numpy pass over resident grids like the eddy detector.
  - **It was never blocked on `wind_u`/`wind_v`** — see §1. It needed wind
    *components*, which the live field always had.
  - **The coastal normal is derived from the currents field's own land mask**
    (smooth the ocean mask, take its gradient, and it points from land into
    water by construction), because no service here supplies coastline geometry.
    That is coarse at ~0.25 degrees, so `coastline_confidence` reports how
    well-defined each normal is and an ambiguous cell is dropped rather than
    given an invented bearing. The mask cannot come from the *wind* field: wind
    is defined over land, so its coverage edge is the whole globe.
  - **The hemisphere asymmetry falls out of the sign of f**, never a latitude
    branch — the same failure mode as eddy polarity, and pinned by a test that
    mirrors identical geometry and identical wind across the equator.
  - **Not corroborated against SST or chlorophyll, deliberately.** Bakun's index
    says the wind is favourable, not that cold nutrient-rich water surfaced.
    Corroboration is a second claim needing its own baseline — and the SST half
    is now affordable, since the percentile climatology exists. That is the
    natural next increment.
- **Marine heatwaves — shipped 2026-08-17.** `services/heatwaves.py` +
  `GET /api/ocean/heatwaves`, to the Hobday definition: SST above the
  seasonally-varying 90th percentile for **at least five consecutive days**,
  categorised by multiples of the mean-to-p90 gap.
  - **The five-day clause is what separates an event from a warm afternoon.** A
    detector comparing today's field to today's threshold reports weather and
    calls it a heatwave; `detect` takes a stack of consecutive daily fields and
    refuses when handed too few.
  - Each day is compared against **its own** threshold: over a 30-day window in
    spring the seasonal p90 moves measurably, and reusing the latest day's
    threshold biases run length in whichever direction the season is going.
  - `crw.py`'s 60S-60N masking is inherited for **aggregates only**; the per-cell
    field is unmasked, because a Barents Sea heatwave is real.
  - **It detects and does not track**, like the eddy detector: onset date,
    duration and cumulative intensity all need identity held across days, which
    is the frame-to-frame assignment problem with the same failure of presenting
    a matcher's artefact as an observation. Run lengths are censored at the
    window and `run_days_censored` says so.

**Still open in this section**: the map layers and point-brief rows for both new
detectors — the services and endpoints ship, the UI does not yet reach them.

**Do not put cyclones, storm surge or coastal flooding in the first event
list.** No cyclone track source is integrated (IBTrACS/IMD/JTWC are all external
and unwired), and `tidal_height` is `available: false` with no global source. An
event list that silently omits the events a user most expects is worse than a
shorter list that says what it covers.

### What is left in this section

1. **Map layers and brief rows** for the heatwave and upwelling detectors. The
   backend ships; nothing in the UI reaches it yet.
2. **Eddy tracking** — the open half of the first detector. Validate against a
   published eddy atlas, not against how plausible the tracks look.
3. **Upwelling corroborated by SST**, now that a percentile baseline exists.
4. **Anomaly explorer**, once the climatology covers more than one variable —
   which is bounded by finding long-record sources, not by code.

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
trained ones.

**No longer waiting on anything**: the `wind_u`/`wind_v` grids exist (§1), so
this is now unblocked work rather than a dependency. Two parts have to move
together — the point path (`forecasting/predictor.py`) and the grid path — and
`test_grid_matches_the_point_path` is what keeps them honest. The interval is
the interesting part: a confidence interval on a bearing cannot be the interval
on `atan2` of two independent intervals, so it needs propagating deliberately
rather than by construction. **`wave_direction` has no components in the
registry and stays trained**; that asymmetry must be stated in the catalog
rather than hidden, since one direction variable would then be derived and
another not.

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

## Parked, with the reason

Not abandoned — blocked on something this workflow cannot supply.

- **Browser verification of the globe recentre, the drift layers and the
  particle animations.** Agent-driven Chrome tabs are always hidden, so
  `requestAnimationFrame` never fires, the map never initialises and every
  animation freezes — a limitation of the harness, not evidence of a problem.
  Needs one human look at `/map`, which should also check several particle
  systems at once on a mid-range GPU: there are now seven possible flow layers,
  each an independent `requestAnimationFrame` + `map.redraw()` loop with its own
  trail framebuffers, and nothing coordinates them.
- **DATRAS/RLS true absences.** §5 is right that this is a decision about what
  the product *is*, not a data-ingestion task: adopting either relocates the
  habitat model out of the northern Indian Ocean, which is the platform's reason
  for existing. It needs a product call before any code.

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
