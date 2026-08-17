# TODO

**Pending work only.** Anything that ships moves to DONE.md with the finding
that outlived it — a measured number, or a decision with its reason attached —
so it is not re-derived or re-litigated. Several items below depend on a
measurement recorded there; those cross-references are load-bearing, not
decoration.

Sections are ordered by what unblocks the most other work, not by size. Numbers
were measured, not estimated; re-verify before relying on any of them if it has
been a while.

---

## 1. Detection — the half that is still open

Three detectors ship (eddies, marine heatwaves, coastal upwelling) over a
percentile climatology. What is left is tracking, corroboration and breadth.

### Eddy tracking

The open half of the first detector. Nothing in `services/eddies.py` holds state
between refreshes, deliberately, so this starts from a clean sheet.

- It is a frame-to-frame assignment problem. An eddy that flickers identity
  between timesteps produces a "trajectory" that is an artefact of the matcher
  presented as an observation.
- **Validate against a published eddy atlas, not against how plausible the tracks
  look.** This is the whole difficulty; a matcher can be tuned until its output
  is beautiful and wrong.
- Also open: closed-SSH-contour detection as a cross-check on the count.

### Upwelling corroborated by SST

`services/upwelling.py` ships the wind-derived index and says explicitly that it
is not an observation of upwelled water. The SST half is now affordable, since
the percentile climatology exists — a favourable-wind cell with a coincident
negative SST anomaly is a materially stronger claim than either alone.

Keep the two separable in the response. "Wind favourable" and "wind favourable
*and* the water responded" are different findings and a user needs to know which
one they are looking at.

### Anomaly explorer

Ranking "SST +2.7σ, chlorophyll +2.1σ" over a point or a box.

**Bounded by sources, not by code.** `services/climatology/build.py` is
variable-agnostic, but OISST serves SST alone, so every further variable needs a
long-record source of its own. Until the climatology covers more than one
variable this is a one-variable feature and not worth shipping.

**Only variables with a real baseline may appear.** A ranked list that silently
omits half the catalogue is the same failure as an event list that omits the
events a user most expects.

### Marine heatwave duration and onset

The detector reports "Nth consecutive day above threshold *within the window
examined*" and censors at the window. Real onset dates and cumulative intensity
need identity held across days — the same assignment problem as eddy tracking,
and worth doing after it rather than twice.

---

## 2. Drift: the field ships, the trajectory does not

The combined drift field ships (`u_total = u_curr + u_stokes + alpha * u_wind`,
with `alpha` a named object preset). **Trajectory integration is the
architectural jump and it is the half that is left.**

`VectorFieldParticleLayer` advects against a **single snapshot texture** — every
particle sees the same instant forever, which is correct for an animated
streamline and wrong for a drift forecast, where a 48-hour trajectory must cross
48 hours of changing field.

- That needs a time-indexed stack of textures with interpolation in the update
  pass, or a server-side integrator returning a polyline. **Prefer the
  server-side integrator**: it is testable against known drifter tracks, and a
  trajectory is a *result* the user wants to export, brief on and compare — not a
  visual effect.
- **State the uncertainty or do not ship it.** A single deterministic track reads
  as a prediction of where the object *is*. Operational SAR drift is run as an
  ensemble over perturbed start position, `alpha` and field error, and what is
  drawn is a probability envelope. A lone line on a map, in a product someone
  might actually search from, is the most dangerous thing in this file.
- A forecast drift horizon is now possible — the `wind_u`/`wind_v` grids exist —
  but the live field's wind term is still observation-only.

---

## 3. Explainability for the derived indices

`forecasting/shap_explainer.py` exists and the metric pages render an
Explainability section, but **HAB risk and habitat suitability have no SHAP
path** — the two things a user most wants explained are the two that cannot
answer.

The honest version is not small. `services/predictions.py` deliberately serves
precomputed grids so `machine_learning/` stays out of the backend import graph,
and that boundary is worth keeping. So local attribution means **exporting
per-cell top-k SHAP as a grid** from the ML side, alongside the prediction grid.

The cheap alternative — serving the global importances already in
`reports/*_shap_*.csv` — answers "what drives this model" rather than "why is it
0.71 *here*". Worth shipping only if labelled as exactly that.

---

## 4. Machine learning

### Union GBIF with OBIS

Still the biggest cheap win for the habitat model: **3–6x the tuna labels inside
the existing 2000–2013 window** (measured 2026-08-05).

| species | 2000–2013 OBIS | 2000–2013 GBIF |
| --- | --- | --- |
| *Thunnus albacares* | 394 | **1228** |
| *Katsuwonus pelamis* | 280 | **1622** |
| *Thunnus obesus* | 283 | **678** |
| *Rastrelliger kanagurta* | **67** | 9 |
| *Sardinella longiceps* | **112** | 9 |

- **It must be a union, not a switch.** GBIF dominates for the three tunas; OBIS
  dominates ~10x for Indian mackerel and oil sardine — the two species that
  matter most for Indian coastal fisheries.
- **It needs dedup** on `occurrenceID`, falling back to (dataset, catalogNumber,
  lat, lon, date). Much of GBIF's marine holdings are OBIS datasets republished,
  so merging naively double-counts precisely where the pseudo-absence scheme is
  most sensitive to sampling effort.

It does **not** extend the window — the post-2014 drought is real in both
sources. Do it when the habitat pipeline is next touched, since it changes labels
and wants a retrain anyway.

### Stacking on out-of-fold predictions

The softmax-weighted ensemble ships (see DONE.md). Stacking is the more
principled version and was never attempted.

### ConvLSTM / U-Net for spatial forecasting

**The argument is architectural, not decorative.** `grid_predictor` scores every
cell **independently** — deliberately, to avoid train/serve skew — so the model
cannot see spatial structure at all: not an eddy, not a front, not the shape of a
bloom. A gradient-boosted tree over per-cell features is structurally blind to
the neighbourhood, and that is a real gap a convolutional model fills.

- Baseline to beat is strong and measured: delta-target LightGBM at skill +0.20
  vs persistence. **Trees beating neural nets on tabular data is the norm** — the
  claim to make is "DL where trees are provably blind (fields), trees where they
  win (points)", not "DL is better".
- **Start with U-Net segmentation of HAB bloom extent** over chlorophyll fields:
  contained, and 3.9M labelled rows already exist.
- The gridded training data is the expensive prerequisite. The climatology build
  is the same fetch shape and its cached years are a starting point.

### ARGO float profiles

The only in-situ source that could validate the depth-resolved variables
(`water_temperature`, `water_salinity`, `currents_depth`), which today are served
and forecast with **no independent check against an instrument**. NDBC is already
in (`services/ndbc.py`); ARGO is the subsurface counterpart and nothing reads it.

Scope it as **validation first and bias correction second** — correcting a model
against floats before measuring the offset is how a bug becomes a feature.

---

## 5. Product surfaces

### Saved locations, and the regional brief

Two features that share one unresolved question, so do them together or not at
all.

- Saved **points** are small: a table and a sidebar, following
  `app/models/chat/session.py` as the DB-backed reference.
- A **regional brief** extends `services/brief.py` from a point to a bbox, which
  is mostly the same document over reduced fields.
- **Both need a reduction named.** Mean, max and area-over-threshold are three
  different answers and a user will assume whichever one confirms their fear. A
  polygon-clipped seasonal anomaly additionally needs a climatology per variable,
  which does not exist yet (see §1).

Reuse `DrawableAreaMap` rather than building a second drawing surface.

### Ocean heat content as a map field

The four charted layers ship (0-50 / 0-100 / 0-200 / 0-700 m). A *field* is a
different cost class: it needs the global depth-resolved temperature fetch, so
**do it as a grid build, not as a dashboard change**.

### Motion, applied

The budget exists in `styles/tokens.css`. Remaining targets: the dashboard's
range-change transitions, the map's layer picker, the metric pages' chart swaps.

**The no-go list is the important half — all three were paid for once:**

- **Never wrap the `/map` route in a keyed animated wrapper.** A remount destroys
  and rebuilds the MapLibre WebGL context and discards the layer state
  `mapPreferencesStore` exists to preserve.
- **No JS mount animation on dashboard panels.** `AnalyticsGrid`'s `LazyMount`
  decides what to render by *measuring geometry*, and Recharts' entry animation
  is already disabled for starting before `ResponsiveContainer` settled its
  width. Moving and rescaling the thing being measured, as it is measured, is the
  same hazard. Hover is safe.
- **Reduced motion resolves to the finished state**, never to a faster animation.

Worth measuring before adding more JS: **native CSS scroll-driven animations**
(`animation-timeline: view()`). They run off the main thread, need no library,
and degrade to "already visible" where unsupported — the same resolution reduced
motion already takes.

### The visual standard — a standard, not a task

It collides with three rules this codebase holds deliberately (no UI kit outside
`features/dashboard/`; one place chooses a colour; reduced motion resolves to the
finished state) and with something more important than any of them:

**This product's distinguishing property is that it never substitutes a number
for missing data.** Award-site polish trends toward decorative confidence —
skeletons implying data is coming when the cache is cold, animated counters on
estimates, "94% confident" chips. The dashboard's three-way `ready` / `warming` /
`unavailable` is the standard to hold; a redesign that softens it is a regression
however good it looks. The compare page's loading state is the shape to copy: it
says what is happening and why it takes time, rather than drawing a ghost of a
table whose shape is exactly what the request is still deciding.

The actionable, auditable half:

- **Three surfaces carry the product**: the landing page, `/map`, `/dashboard`.
- **Criteria, not vibes**: one type scale used everywhere (audit for literals
  bypassing the tokens); a real empty / loading / error state for every panel;
  the contrast floors the map ramps already meet (≥3:1 against the Abyss basemap,
  ≥2:1 for the hatched unforecastable mark) applied to the chrome too.

---

## 6. Parked — blocked on something this workflow cannot supply

Not abandoned.

- **Browser verification of the globe recentre, the drift layers and the particle
  animations.** Agent-driven Chrome tabs are always hidden, so
  `requestAnimationFrame` never fires, the map never initialises and every
  animation freezes — a limitation of the harness, not evidence of a problem.
  Needs one human look at `/map`, which should also check several particle
  systems at once on a mid-range GPU: there are seven possible flow layers, each
  an independent `requestAnimationFrame` + `map.redraw()` loop with its own trail
  framebuffers, and nothing coordinates them.
- **DATRAS/RLS true absences — the biggest accuracy lever, and a product call.**
  ICES DATRAS (trawl surveys with real zero-catch hauls) and RLS (reef transects
  with abundance and real zeros) are the only true-absence sources found in the
  2026-08-05 survey. They would remove pseudo-absences entirely, which is worth
  more than any change to the classifier. But DATRAS is North Atlantic/European
  and RLS is reef transects, so adopting either **relocates the habitat model out
  of the northern Indian Ocean**, which is the platform's reason for existing.
  That is a decision about what the product *is*, not a data-ingestion task. A
  defensible middle path is a *second* model in a DATRAS region, kept beside the
  regional one as evidence of what the pseudo-absence scheme costs.

---

## 7. Still genuinely open, smaller

- **Postgres for persistence**, for *records* rather than cache or features:
  download history/audit, feedback (currently `feedback_log.jsonl`), and the KPI
  ring buffer that does not survive a restart. Chat sessions are already there
  and are the reference implementation.
- **Documentation drift**: CLAUDE.md's forecast-map section no longer quotes a
  grid count and says to count the directory instead. Keep it that way — the
  number moves with every `--all` run.
