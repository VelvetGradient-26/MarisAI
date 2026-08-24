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
the two things that measurement pointed at: a baseline fitted on the product
being scored, and a wind history long enough to test the claim fairly.

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

### A climatology fitted on the product being scored

**The latency answer has been tried and it is the wrong lever** (measured
2026-08-17, written up in `services/sst_anomaly.py` and DONE.md). Scoring the
live hourly SST field instead of the 14.5-day-old OISST record left the weak
tier's contrast unchanged and *inverted* the strong one, because the climatology
is fitted on OISST and a different product carries **0.76 degC of per-cell
disagreement across the coastal band** — wider than the 0.5 °C threshold it is
compared against, and twice the open-ocean figure (0.47) because a 1° coastal
cell is an average of a coastline the two products resolve differently.

So the open item is the baseline, not the observation: **fit a climatology on
the Copernicus physics reanalysis**, whose record reaches 1993, and score the
live field against its own product.

- `services/climatology/build.py` is variable- and source-agnostic already; what
  it needs is a fetch that hands it a long daily record. `sources` guidance in
  CLAUDE.md applies — global reanalysis at 1/12° must be coarsened *while the
  array is still lazy*, and needs a server-side depth bound or it pulls 50
  levels and never finishes.
- **Re-run the control after, not before, deciding it worked.** The measurement
  that matters is whether the favourable/downwelling contrast widens beyond
  +0.026. If it does not even with a matched product, the honest conclusion is
  that a wind snapshot and an SST snapshot do not agree at this resolution, and
  the layer should say so more loudly rather than be tuned until it looks better.
- It would also give the anomaly explorer below a second baseline variable
  nearly free, since the same fetch carries salinity and currents.

### A rolling wind history, so the corroboration can be tested fairly

Upwelling responds to wind *integrated over days*, not to the instantaneous
stress the index computes. Nothing here keeps more than the latest wind
timestep, so the favourable/downwelling contrast above is measured against a
snapshot on both sides — which is a weaker test than the physics deserves, and a
plausible part of why the contrast is small. A short trailing wind buffer (the
KPI ring buffer in `services/dashboard/history.py` is the shape) would let the
index be computed on a multi-day mean and the control re-run against it.

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

### Geofencing — the approximations that should not ship to production

`services/geofencing.py` says this about itself, and it is worth restating as
tasks:

- **Andaman & Nicobar and Lakshadweep EEZs are not represented.** Only
  mainland coastal waters are. A fisherman operating from either archipelago
  gets no geofencing at all today.
- **The IMBL is hand-placed from public descriptions, not the treaty's
  surveyed coordinates.** Worth sourcing the actual 1974/1976 India-Sri Lanka
  agreement coordinates rather than an eyeballed sketch, given this is the
  real-world hazard (fishermen straying across it) the feature exists for.
- **The India EEZ polygon is a coastline sketch offset by a fixed degree
  margin**, not a geodesic buffer of a real coastline dataset. Marine Regions'
  WFS (`geo.vliz.be/geoserver/MarineRegions/wfs`, reachable per CLAUDE.md's
  EMODnet probe) is the natural upgrade — a `GetFeature` call against the
  World EEZ layer, cached like every other slow-changing reference dataset.
- **Only 4 MPAs are registered**, hand-picked, not sourced from India's MPA
  registry. WDPA (protectedplanet.net) is the standard source; whether it has
  a clean API or is bulk-download-only was not checked this pass.

### Routing — currently a comparison, not a planner

- **Three candidate routes (direct + two lateral offsets), not a pathfinder.**
  A real hazard-aware router (A*/Dijkstra over a gridded wave/wind cost
  surface, the way the forecast grid already tiles the ocean) would find
  routes the three-candidate comparison structurally cannot, e.g. routing
  around a headland. This is the biggest single accuracy gap in `plan_route`.
- **Waypoints are linearly interpolated in lat/lon, not a true geodesic.**
  Stated as fine at coastal/fishing-vessel route lengths in
  `routing.py`'s docstring — re-check that assumption before using this for
  anything ocean-basin-scale.
- **No vessel profile.** Speed, fuel range and draft are not inputs; every
  route is scored on wave/wind hazard alone.

### PFZ — a heuristic, not a validated model

`services/pfz.py` composes raw chlorophyll + SST with a documented but
untested rule (chlorophyll above the local sample's own median, SST inside a
broad band). It has never been checked against real catch data or INCOIS's
own PFZ advisories, which use validated chlorophyll/SST *front* detection —
a genuinely different and more sophisticated technique than a threshold. If
this is going to be presented as more than a screening aid, it needs that
validation pass; the honest caveat currently baked into every response is a
substitute for that, not a step toward it.

### Multi-agent — two things still owed

The prompt tightening and the delegation reasoning trace shipped and were
verified live against the configured provider — see DONE.md's "Multi-agent:
prompt tightening and a visible delegation trace". What's left:

- **A live browser pass on `/assistant`** — the specialist-name pill on each
  tool call and the new delegation line (`AssistantThread.tsx`) have only been
  verified via the raw SSE event stream and a typecheck, not eyeballed in the
  UI. Same "agent-driven Chrome tabs are always hidden, `requestAnimationFrame`
  never fires" limitation section 6 already names for the map — needs one
  human look, not a repeat automation attempt.
- **Grounding cannot catch a false refusal, and one was observed live.** Of
  three live runs of the same Kochi→Kanyakumari question, one had the
  orchestrator claim it "couldn't pull a safe-route plan" after
  `plan_safe_route` and `get_seafloor_depth` had already succeeded and
  populated the ledger — `grounded` stayed `true` because a refusal states no
  numbers to check against the ledger, so today's checker is structurally
  blind to this failure mode. A repeat of the identical question immediately
  succeeded, so this reads as the small provider model (`gpt-oss:20b-cloud`
  via `ollama`) occasionally discarding a successful tool result during
  synthesis, not a deterministic bug in the loop. `_ungrounded_numbers` checks
  "does the answer claim a number the ledger doesn't have" — the missing
  symmetric check is "does the ledger have data the answer claims is
  unavailable", e.g. flag (or log) a turn where `ledger.observations` is
  non-empty but the final text matches a refusal/apology pattern. Worth doing
  before a demo relies on this path, since the current failure is silent —
  no flag, no log line, just a bad answer that looks exactly as confident as
  a correct "I don't have that" would.
