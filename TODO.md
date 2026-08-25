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
percentile climatology, and upwelling is now corroborated against SST — weakly,
which was measured rather than assumed. What is left is tracking, breadth, and
the one lever measurement has not yet ruled out: a wind history long enough to
test the claim fairly (both SST-side levers — closing the latency gap, and
fitting the baseline on the scored product — were tried and measured worse).

### Eddy tracking — the matcher shipped, the atlas comparison didn't

`services/eddy_tracking.py` gives eddies frame-to-frame identity (nearest-
neighbour matching, gated and polarity-separated, solved exactly within each
locally ambiguous cluster via `linear_sum_assignment` rather than greedily)
over `services/eddies.py`'s own hourly detection passes. See DONE.md's "Eddy
tracking: frame-to-frame identity over a live detection grid" for what
shipped, the scaling design (KD-tree + connected components, not a dense
matrix — verified live at 2177 real global eddies in 16ms), and the three
things checked before calling the matcher correct. What's left:

- **Validation against a published eddy atlas remains undone, but only for
  lack of two downloaded files, not for lack of a path.** AVISO+'s Mesoscale
  Eddy Trajectory Atlas needs a registered account — confirmed three ways
  2026-08-24 (the product page; its THREDDS catalog, whose *listing* is
  public but whose data answers `401 Unauthorized`; a direct `fileServer`
  request) — the same shape of blocker as WDPA for `services/geofencing.py`.
  What shipped instead: the product handbook is openly downloadable (no
  account) and gave the real NetCDF schema, not a guessed one; `scripts/
  compare_against_eddy_atlas.py` reads it, runs `eddies.detect()` against a
  **historical** reanalysis current field for the requested date (the atlas's
  own coverage ends 2023-09-08, already years behind live operation, so a
  same-instant comparison was never going to be possible — see the script's
  own docstring), and matches the two detections with the same gated,
  optimal-assignment shape `eddy_tracking.py` uses. **Live-verified for the
  half that doesn't need the atlas**: `fetch_currents_day` and the full
  detect-against-history pipeline both run correctly against the real
  Copernicus reanalysis (2020-06-15: 2097 eddies, 954 cyclonic / 1143
  anticyclonic — the same order as the live cache's 2177). What's left is
  registering an AVISO+ account, downloading the two files, and running the
  script — not writing any more code.
  - Also open: closed-SSH-contour detection as a cross-check on the count —
    `py-eddy-tracker` (github.com/AntSimi/py-eddy-tracker), the actual
    open-source algorithm AVISO's own atlas is built from, is pip-installable
    and unblocked by the AVISO+ account wall entirely. Worth trying against
    the live SSH-adjacent field this platform already has before assuming a
    from-scratch contour detector is needed.
- **No map layer or chat tool yet** — `GET /api/ocean/eddies/tracks` exists
  and is tested, but nothing visualises a track's path the way `/eddies`
  itself is drawn. A natural next step once the atlas comparison above says
  the tracks are trustworthy enough to show.
- Also open: closed-SSH-contour detection as a cross-check on the count.

### A rolling wind history, so the corroboration can be tested fairly

**Both baseline levers have now been tried and both failed** — see
`services/sst_anomaly.py`'s docstring and DONE.md for the full numbers. Neither
closing the OISST/live-field latency gap (2026-08-17) nor fitting the
climatology on the Copernicus reanalysis instead of OISST (2026-08-25, a real
30-year build, measured against a paired same-snapshot control) widened the
favourable/downwelling contrast; the second attempt made the strong (below-p10)
tier substantially worse (-0.051 against OISST's -0.001). Both the product and
the baseline it is scored against have now been ruled out, which points at what
is left: the wind and SST snapshots on both sides of the control are
instantaneous.

Upwelling responds to wind *integrated over days*, not to the instantaneous
stress the index computes. Nothing here keeps more than the latest wind
timestep, so the favourable/downwelling contrast above is measured against a
snapshot on both sides — which is a weaker test than the physics deserves, and a
plausible part of why the contrast is small. A short trailing wind buffer (the
KPI ring buffer in `services/dashboard/history.py` is the shape) would let the
index be computed on a multi-day mean and the control re-run against it. This is
now the only untried lever — re-run
`scripts/measure_sst_corroboration.py` (either source) once it exists, rather
than reaching for a third SST variant.

### Upwelling corroborated by chlorophyll

The third leg, still blocked on the same thing it always was: there is no
resident chlorophyll field and no long-record chlorophyll climatology to make an
anomaly out of, so "nutrient-rich water reached the surface *and* something ate
it" cannot be said. `services/climatology/build.py` is variable-agnostic and
would fit it — what is missing is a long daily chlorophyll record to fit on, the
same source problem as the anomaly explorer below. Worth doing *after* the
baseline item above, since it inherits whatever that settles about scoring one
product against another's climatology — a chlorophyll baseline fitted on one
sensor and applied to another would repeat the same mistake in a field with a
far worse dynamic range.

### Anomaly explorer

Ranking "SST +2.7σ, chlorophyll +2.1σ" over a point or a box.

**Bounded by sources, not by code.** `services/climatology/build.py` is
variable-agnostic, but OISST serves SST alone, so every further variable needs a
long-record source of its own. Until the climatology covers more than one
variable this is a one-variable feature and not worth shipping.

**The scoring half is now built, though**, which was not true when this was
written: `heatwaves.sst_anomaly_field()` exports the per-cell anomaly and the
p10 deficit against the fitted baseline, and `services/upwelling.py` consumes it
across a grid change. A second variable would reuse that path rather than start
one. What is missing is still only the record to fit on.

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

The three named targets ship (see DONE.md) — all three in CSS, no new JS and no
new dependency.

**Native CSS scroll-driven animations now drive the hero parallax and the
platform cards' 3D glyphs** (see DONE.md). The JS path stays as the fallback for
browsers without `animation-timeline`, and is disabled rather than overridden
where the CSS is in charge.

What is left of this item is the rest of the landing page's reveals, and they
are deliberately *not* urgent: `useReveal` detaches its own listeners the moment
it fires, so eight reveals cost eight one-shot subscriptions and nothing
thereafter. Convert them for consistency, not for performance.

- **`overflow: hidden` on any ancestor silently freezes a view timeline** — it
  makes that element a scroll container, and `view()` measures the nearest
  scrollport rather than the viewport. Use `overflow: clip`. Three ancestors on
  the landing page were doing it and the animations still reported themselves as
  running.
- **A screenshot cannot verify a scroll-driven animation.** Sample the computed
  matrix at several scroll positions; a static pose looks identical to a moving
  one in any single frame.

**The no-go list is the important half — all three were paid for once:**

- **Never wrap the `/map` route in a keyed animated wrapper.** A remount destroys
  and rebuilds the MapLibre WebGL context and discards the layer state
  `mapPreferencesStore` exists to preserve.
- **No JS mount animation on dashboard panels.** `AnalyticsGrid`'s `LazyMount`
  decides what to render by *measuring geometry*, and Recharts' entry animation
  is already disabled for starting before `ResponsiveContainer` settled its
  width. Moving and rescaling the thing being measured, as it is measured, is the
  same hazard. Hover is safe. **Opacity is also safe, and that is now load-
  bearing** — it is why `.oid-swap-in` fades and never slides.
- **Reduced motion resolves to the finished state**, never to a faster animation.

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

---

## 8. SIH Problem Statement 2 — the agentic marine intelligence platform

Phase 1 shipped: the Ocean Assistant is now a real multi-agent system — an
orchestrator delegating to three specialists (`services/chat/specialists.py`,
`services/chat/orchestrator.py`), each its own bounded tool-calling sub-loop,
sharing one `Ledger` so grounding still covers every specialist's numbers.
Three new capabilities feed it: `services/geofencing.py` (India EEZ/IMBL/MPA
proximity), `services/pfz.py` + `services/copernicus_chlorophyll.py` (a
heuristic potential-fishing-zone scan), and `services/routing.py` (candidate-
route hazard comparison). Regional-language response is LLM-native (a system
prompt instruction, no detection/translation pipeline) and was verified live
in Hindi. What's below is what Phase 1 deliberately left out, plus what using
it live surfaced as worth doing next.

### Cyclone/severe-weather alerts — shipped, three things left

The gap this section named is closed — see DONE.md's "Cyclone and
severe-weather alerts, from GDACS and IMD's CAP feed". `get_cyclone_alerts`
(GDACS, global tropical-cyclone tracking) and `get_severe_weather_alerts`
(IMD's own CAP feed — heavy rain, heatwave, cold wave, thunderstorm/lightning)
are live chat tools on the `weather_safety` specialist, verified end to end
against the real APIs and a live LLM. What's left:

- **No REST endpoint, matching `geofencing`/`pfz`/`routing`'s existing
  precedent** (all three are chat-tool-only, no router) — but unlike those
  three, a cyclone/severe-weather map layer is a plausible, genuinely useful
  next surface (a polygon/point overlay, same shape as `eddies`/`upwelling`).
  Worth doing if this becomes more than a chat-only feature; the services
  already return real geometry (GDACS track points, IMD CAP polygons/circles)
  so a router would be thin.
- **`check_point`'s cyclone proximity is a circle around the last reported
  fix, not an intersection with the storm's forecast cone or wind-radius
  polygons.** GDACS's `getgeometry` endpoint exposes exactly that (per-
  timestep `PointRadii` features carrying real 34/50/64kt wind radii) — see
  `services/cyclones.py`'s docstring. Left out of this pass to keep the
  fetch to one call per check rather than one per active storm; worth doing
  if the coarse radius proves too imprecise in practice.
- **The IMD CAP feed's RSS index has only ever been observed carrying 7
  items.** That is fine for "currently active" (alerts are rarely valid
  longer than ~48h) but was never confirmed against the aggregator's own
  behavior under a burst of alerts (e.g. a real landfall issuing many warnings
  in one day) — worth re-checking during the next actual severe-weather event
  rather than assumed safe from today's quiet-season sample.

### Geofencing — three of four fixed, one blocked on a key

Three of the four approximations `services/geofencing.py` used to warn about
itself are shipped — see DONE.md's "Real EEZ and IMBL geometry for
geofencing". What's left:

- **The MPA registry is still hand-curated, not WDPA** (now 9 named sites,
  up from 4, each individually verified — see DONE.md). WDPA's API needs a
  registered key (`api.protectedplanet.net` returns 401 unauthenticated,
  checked 2026-08-24) and its bulk release is not a plain scriptable download
  either — both real blockers, not unchecked assumptions. Getting a key is a
  human action this workflow can't self-serve; once one exists, the fetch
  shape would follow `services/eddies.py`'s pattern for a slow-changing
  reference dataset, same as the EEZ/IMBL fetch that just shipped.

### Routing — now a planner; two items carried over, one new

The three-candidate comparison is gone — `plan_route` is a real A* search
over a live grid now, land/IMBL/MPA-excluding by construction. See DONE.md's
"A* route planning over a live hazard grid" for what shipped and how it was
verified. What's left:

- **Waypoints are still linearly interpolated in lat/lon for bbox/heading
  math, not a true geodesic.** Unchanged from before — fine at the coastal/
  fishing-vessel route lengths this is built for; re-check before using this
  for anything ocean-basin-scale.
- **Still no vessel profile.** Speed, fuel range and draft are not inputs;
  every route is scored on wave hazard alone.
- **The search grid trades resolution for Open-Meteo request volume, and
  the failure mode when that trade is too coarse is a hard error, not a
  degraded answer.** A start/end point enclosed by land tighter than
  `_MAX_CONNECT_RADIUS_CELLS` (an actual narrow inlet, or just an unlucky
  coastline shape at this grid's resolution), or a route whose only real
  detour exceeds the search bbox margin (open-ocean circumnavigation of an
  island, say), correctly raises `RoutingError` rather than returning a
  route that secretly crosses something — verified live for exactly that
  case (Palk Strait to the open sea east of Sri Lanka correctly reports no
  path, since going around Sri Lanka is outside the search box). Worth
  watching whether real usage hits this often enough to justify widening the
  margin or the connect radius as a follow-up, now that it ships.

### PFZ — a heuristic, not a validated model

`services/pfz.py` composes raw chlorophyll + SST with a documented but
untested rule (chlorophyll above the local sample's own median, SST inside a
broad band). It has never been checked against real catch data or INCOIS's
own PFZ advisories, which use validated chlorophyll/SST *front* detection —
a genuinely different and more sophisticated technique than a threshold. If
this is going to be presented as more than a screening aid, it needs that
validation pass; the honest caveat currently baked into every response is a
substitute for that, not a step toward it.

### Multi-agent — one thing still owed

The prompt tightening, the delegation reasoning trace, and the false-refusal
check all shipped and were verified live against the configured provider —
see DONE.md's "Multi-agent: prompt tightening and a visible delegation trace"
and "Catching a false refusal — the check `grounded` cannot make". What's
left:

- **A live browser pass on `/assistant`** — the specialist-name pill on each
  tool call, the delegation line, and the new false-refusal banner
  (`AssistantThread.tsx`) have only been verified via the raw SSE event
  stream and a typecheck, not eyeballed in the UI. Same "agent-driven Chrome
  tabs are always hidden, `requestAnimationFrame` never fires" limitation
  section 6 already names for the map — needs one human look, not a repeat
  automation attempt.

---

## 9. Competition UI/UX push (2026-08-24)

A batch from a competition-prep pass. None of these are measured yet — they're
requests, not findings — so verify the premise named in each bullet before
building.

### Metric pages: forecast should be warm before the click, not triggered by it

`/dashboard/<variable>` currently calls forecast inference on the click that
opens the page — the user experiences the click as "it starts forecasting".
`services/predictions.py` already establishes the pattern this should move
to: precomputed output served on request, nothing computed synchronously in
the request path. The forecasting engine (`backend/forecasting/`,
`POST /api/v1/forecast`) is the thing actually being invoked late — check
whether a metric page's forecast section calls it inline on mount rather than
reading something pre-warmed. If so, either move the compute to the existing
12-hourly grid-build scheduler job (`scripts/build_forecast_grid.py`'s
pattern — background thread, never on the event loop, per
`test_the_cell_loop_does_not_run_on_the_event_loop`) or add a per-point cache
warmed on a schedule. Whichever: the click should always read a cache, never
originate a computation.

### Fun, non-decorative loading states

Section 5's "visual standard" already drew this line and it still holds:
**no fake confidence, no skeleton implying data that isn't coming.** The
constraint here is animating the *wait*, not the *data* — a fish swimming
across the panel, bubbles rising, a submarine sweeping a light back and forth
while a real fetch is in flight is fine, because it makes no claim about the
data's shape or value. A shimmering skeleton row that mimics a chart's
eventual layout is the thing to avoid, because it implies specific content is
about to resolve. Scope: replace the current skeleton loaders (dashboard
panels, metric pages) with a small set of playful SVG/CSS loop animations,
picked contextually (e.g. a submarine light-sweep for a map/geo fetch, bubbles
for a numeric KPI). Keep them opacity/transform-safe per the existing
`LazyMount`-measures-geometry constraint in section 5, and give every one a
reduced-motion resting frame.

### Ocean Assistant: general questions without forcing a tool call, plus image upload

Two separate gaps in `services/chat/`:

- **Not every user turn should force a tool call.** If the current loop
  always dispatches to a specialist/tool even for a question answerable from
  general knowledge ("what causes upwelling" vs. "what's the SST at this
  point"), that's a routing problem — the orchestrator
  (`services/chat/orchestrator.py`) or the specialists
  (`services/chat/specialists.py`) should be able to answer directly for
  general marine-science questions and only reach into `build_tools()`
  (`services/chat/tools.py`) when the question needs a live number. Check
  whether the model already has this freedom (tool_choice="auto" style) before
  assuming a routing layer needs to be built — this may already be a prompting
  fix, not an architecture change.
- **Image upload / vision.** The user wants to attach an image and have the
  assistant describe/answer about it. This means passing image content
  through to the LLM provider's multimodal input on a turn (provider-
  dependent content-block shape), plus a composer affordance in
  `features/assistant/` to attach a file. Check the provider client already in
  use in `services/chat/` for whether it already exposes an image content
  type — this is very likely additive to the existing message-building code,
  not a new client.

### Ocean Assistant: answer questions about the software itself, with doc links

Right now the assistant only reasons about ocean data. It should also be able
to answer "how do I use X feature" / "where's the download page" /
"what does the grounding badge mean" and point at the real docs — the
platform already has a documentation section
(`frontend/src/pages/docs/`, chapters per feature: `Assistant.tsx`,
`DashboardCharts.tsx`, `ForecastMap.tsx`, etc., indexed by
`DocsSearch.tsx`/`searchIndex.tsx`). This is a **self-knowledge** capability,
distinct from the ocean-data tools: likely a small retrieval step over the
existing docs chapters (they're already React/TS source, not prose files, so
decide whether to index rendered text or keep a parallel plain-text/markdown
copy for retrieval) plus a system-prompt instruction to link `/docs/...`
routes rather than inventing paths. Scope this as its own tool
(`get_documentation` or similar) rather than folding it into an existing
specialist, since its source of truth (the docs pages) is unrelated to any
ocean-data provider.

### Data Quality section: each card should open a full model dossier

`services/dashboard/data_quality.py` reports `models_trained` — **116** models
across the forecasting engine's variables x horizons — but
`DataQualityPanel.tsx` currently surfaces a partial list (checked live:
**14** of 116). Two asks, and they compound:

- **List all 116, not a subset.** If the panel currently truncates for
  layout/perf reasons, that needs a paginated or scrollable list instead —
  dropping 102 trained models from view understates what actually shipped
  (same "never substitute a number for missing data" principle section 5
  already holds, applied to *omission* here rather than fabrication).
- **A per-model detail page**, one click from any card, that makes the model
  reproducible from what's shown: what water/points it was trained on, the
  feature list `forecasting/`'s pipeline built (`build_features`), the
  algorithm (LightGBM, per CLAUDE.md), the delta-vs-level target-mode
  decision, the CV fold scores and `skill_score` against persistence *and*
  climatology (the two-baseline point in section — already computed, not
  fabricated for the page), and a SHAP explainability panel
  (`forecasting/shap_explainer.py`, already exists and is rendered on metric
  pages — reuse it rather than rebuilding). This is presentation of numbers
  already computed and logged (`_reports/runs/<timestamp>/`,
  `marine_ml.tracking`), **not new modelling work** — the honesty constraint
  is the same one metric pages already meet ("Ocean Story computes first,
  phrases second" — every figure on this page must be traceable to a real
  training-run artifact, none invented for narrative).

### Live ocean data, satellite products, and data source status: same "click for detail" treatment

Three panels get the same ask — right now clicking a station/product/source
does nothing or shows too little, and it's not verifiable at a glance whether
what's listed is real:

- **Live ocean stations** (`services/ndbc.py`) — clicking a station should
  show its real identity (NDBC station ID, coordinates, what it actually
  measures) and enough of its raw feed/history to visibly confirm it's a real
  instrument, not a placeholder — this addresses "I don't know if the
  stations are true or false" directly, so the detail view's whole job is
  proving provenance.
- **Recent satellite products** (`services/gibs.py`) — clicking a product
  should show the source (which GIBS layer), the coverage/resolution, and the
  actual imagery/tile preview, not just a name and timestamp.
- **Data source status** — clicking a source should show what's cached, when
  it last refreshed, and why (the existing `ready`/`warming`/`unavailable`
  three-way state from section 5 is the right foundation — extend it with
  detail, don't replace it).

All three are "expose more of what the backend already tracks," not new data
collection — check what each service already returns/logs before assuming a
new fetch is needed.
