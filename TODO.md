# TODO

**Pending work only.** Anything that ships moves to DONE.md with the finding
that outlived it — a measured number, or a decision with its reason attached —
so it is not re-derived or re-litigated. Several items below depend on a
measurement recorded there; those cross-references are load-bearing, not
decoration.

Merged 2026-08-28 from the former `sihtodo.md` (SIH problem-statement gap
list) into this file — `sihtodo.md` is gone, this is now the one TODO.
Sections are ordered by difficulty (Easy → Medium → Hard → Blocked/Parked),
not by size or by which project thread they came from. Numbers were measured,
not estimated; re-verify before relying on any of them if it has been a while.

**Three of that merge's "Easy" items were already shipped and stale on
arrival** (found 2026-08-28, re-verifying before implementing): tool
REST/map surfacing and the specialist-naming pass had both merged to `main`
on 2026-08-26 (`git merge-base --is-ancestor` confirmed), and a live check
against the real configured model found the third — general questions
answered without forcing a tool call — already working with no code change
needed. `sihtodo.md` itself was never struck through as those items closed,
so its stale copy carried straight into this file's merge. See DONE.md for
each. Lesson repeated from DONE.md's own "two finished branches" entry:
check `main`, not a doc, before starting an "easy" item.

---

## Easy

### Motion: finish converting the landing page's remaining reveals

The three named targets ship (hero parallax, platform-card 3D glyphs, all
CSS scroll-driven, see DONE.md). The rest of the landing page's reveals
(`Metrics`, and seven more `useReveal<HTMLDivElement>()` call sites in
`pages/LandingPage.tsx`, plus one in `ComparePage.tsx`) are still driven by
`useReveal` — a JS scroll/resize listener plus `IntersectionObserver` as a
backup trigger — rather than pure `animation-timeline: view()` CSS.

**Re-examined 2026-08-28 and *not* converted — this is a real conflict, not
just unfinished polish.** `useReveal`'s own docstring documents two
deliberate properties: reveal only forward ("a reveal never flips back...an
entrance that replays every time you scroll past is a distraction"), and
geometry measured directly rather than trusting `IntersectionObserver` alone
(written after `AnalyticsGrid` shipped with an observer that never fired,
leaving every chart unmounted — see `hooks/useReveal.ts`). A pure scroll-linked
CSS timeline can't reproduce the first property: its progress is a function
of *current* scroll position only, so scrolling back above an entry range and
back down again necessarily replays the animation — exactly the flicker
`useReveal` was written to prevent. Converting these eight call sites the
same way the hero/platform-card *continuous* effects were converted would
trade a documented reliability fix for a real regression, not just change
the implementation technique.

If this is still wanted for consistency, the open question is a product
one, not an engineering one: accept occasional replay-on-scroll-back for a
one-less-hook codebase, or keep `useReveal` for one-shot reveals and reserve
`animation-timeline: view()` for continuous/non-monotonic effects (its
current, working use). Needs a call from whoever wants "consistency" enough
to accept the tradeoff — not a default to implement silently.

- **`overflow: hidden` on any ancestor silently freezes a view timeline** —
  it makes that element a scroll container, and `view()` measures the
  nearest scrollport rather than the viewport. Use `overflow: clip`.
- **A screenshot cannot verify a scroll-driven animation.** Sample the
  computed matrix at several scroll positions; a static pose looks identical
  to a moving one in any single frame.
- **Reduced motion resolves to the finished state**, never to a faster
  animation.
- **Never wrap the `/map` route in a keyed animated wrapper** — a remount
  destroys and rebuilds the MapLibre WebGL context and discards the layer
  state `mapPreferencesStore` exists to preserve.
- **No JS mount animation on dashboard panels** — `AnalyticsGrid`'s
  `LazyMount` decides what to render by measuring geometry; moving/rescaling
  the thing being measured, as it is measured, is the hazard. Hover and
  opacity are safe (`.oid-swap-in` fades, never slides).

### Documentation drift

CLAUDE.md's forecast-map section already avoids quoting a grid count and
says to count the directory instead — keep it that way, since the number
moves with every `--all` run. Not a task so much as a standing rule to not
regress.

---

## Medium

### Eddy atlas validation

`services/eddy_tracking.py` gives eddies frame-to-frame identity
(nearest-neighbour matching, gated and polarity-separated, solved exactly
within each locally ambiguous cluster via `linear_sum_assignment`) over
`services/eddies.py`'s hourly detection passes. See DONE.md's "Eddy
tracking: frame-to-frame identity over a live detection grid" for the
scaling design (KD-tree + connected components — verified live at 2177 real
global eddies in 16ms).

**Validation against a published eddy atlas remains undone, but only for
lack of two downloaded files, not for lack of a path.** AVISO+'s Mesoscale
Eddy Trajectory Atlas needs a registered account — confirmed three ways
2026-08-24 (product page; THREDDS catalog whose *listing* is public but
whose data answers `401 Unauthorized`; a direct `fileServer` request) — same
shape of blocker as WDPA for `services/geofencing.py`. What shipped instead:
the product handbook is openly downloadable and gave the real NetCDF schema;
`scripts/compare_against_eddy_atlas.py` reads it, runs `eddies.detect()`
against a **historical** reanalysis current field (the atlas's own coverage
ends 2023-09-08), and matches detections with the same gated,
optimal-assignment shape `eddy_tracking.py` uses. **Live-verified for the
half that doesn't need the atlas**: 2020-06-15 gives 2097 eddies, 954
cyclonic / 1143 anticyclonic — same order as the live cache's 2177. What's
left is registering an AVISO+ account, downloading the two files, and
running the script — not writing any more code.

- Also open: closed-SSH-contour detection as a cross-check on the count —
  `py-eddy-tracker` (github.com/AntSimi/py-eddy-tracker), the actual
  open-source algorithm AVISO's own atlas is built from, is pip-installable
  and unblocked by the AVISO+ account wall entirely. Worth trying against
  the live SSH-adjacent field this platform already has before assuming a
  from-scratch contour detector is needed.
- **No map layer or chat tool yet** for eddy tracks — `GET
  /api/ocean/eddies/tracks` exists and is tested, but nothing visualises a
  track's path the way `/eddies` itself is drawn. Do this once the atlas
  comparison above says the tracks are trustworthy enough to show.

### A rolling wind history, so upwelling corroboration can be tested fairly

**Both baseline levers have now been tried and both failed** — see
`services/sst_anomaly.py`'s docstring and DONE.md for the full numbers.
Neither closing the OISST/live-field latency gap (2026-08-17) nor fitting
the climatology on the Copernicus reanalysis instead of OISST (2026-08-25, a
real 30-year build, measured against a paired same-snapshot control) widened
the favourable/downwelling contrast; the second attempt made the strong
(below-p10) tier substantially worse (-0.051 against OISST's -0.001). Both
the product and the baseline it is scored against are now ruled out, which
points at what's left: the wind and SST snapshots on both sides of the
control are instantaneous.

Upwelling responds to wind *integrated over days*, not to instantaneous
stress. Nothing here keeps more than the latest wind timestep. A short
trailing wind buffer (the KPI ring buffer in `services/dashboard/history.py`
is the shape) would let the index be computed on a multi-day mean and the
control re-run against it. This is the only untried lever — re-run
`scripts/measure_sst_corroboration.py` (either source) once it exists,
rather than reaching for a third SST variant.

### Saved locations, and the regional brief

Two features that share one unresolved question, so do them together or not
at all.

- Saved **points** are small: a table and a sidebar, following
  `app/models/chat/session.py` as the DB-backed reference.
- A **regional brief** extends `services/brief.py` from a point to a bbox,
  mostly the same document over reduced fields.
- **Both need a reduction named.** Mean, max and area-over-threshold are
  three different answers and a user will assume whichever one confirms
  their fear. A polygon-clipped seasonal anomaly additionally needs a
  climatology per variable, which does not exist yet (see the anomaly-explorer
  and eddy-atlas items above).

Reuse `DrawableAreaMap` rather than building a second drawing surface.

### The visual standard — a standard, not a task

Collides with three rules this codebase holds deliberately (no UI kit
outside `features/dashboard/`; one place chooses a colour; reduced motion
resolves to the finished state) and with something more important than any
of them:

**This product's distinguishing property is that it never substitutes a
number for missing data.** Award-site polish trends toward decorative
confidence — skeletons implying data is coming when the cache is cold,
animated counters on estimates, "94% confident" chips. The dashboard's
three-way `ready` / `warming` / `unavailable` is the standard to hold; a
redesign that softens it is a regression however good it looks. The compare
page's loading state is the shape to copy: it says what is happening and why
it takes time, rather than drawing a ghost of a table whose shape is exactly
what the request is still deciding.

The actionable, auditable half:

- **Three surfaces carry the product**: the landing page, `/map`,
  `/dashboard`.
- **Criteria, not vibes**: one type scale used everywhere (audit for
  literals bypassing the tokens); a real empty / loading / error state for
  every panel; the contrast floors the map ramps already meet (≥3:1 against
  the Abyss basemap, ≥2:1 for the hatched unforecastable mark) applied to the
  chrome too.

### Postgres for persistence

For *records* rather than cache or features: download history/audit,
feedback (currently `feedback_log.jsonl`), and the KPI ring buffer that does
not survive a restart. Chat sessions are already there and are the reference
implementation.

### Ocean Assistant: image upload / vision

The user wants to attach an image and have the assistant describe/answer
about it. Means passing image content through to the LLM provider's
multimodal input on a turn (provider-dependent content-block shape), plus a
composer affordance in `features/assistant/` to attach a file. Check the
provider client already in use in `services/chat/` for whether it already
exposes an image content type — this is very likely additive to the
existing message-building code, not a new client.

---

## Hard

### Drift: the field ships, the trajectory does not

The combined drift field ships (`u_total = u_curr + u_stokes + alpha *
u_wind`, with `alpha` a named object preset). **Trajectory integration is
the architectural jump and it is the half that is left.**

`VectorFieldParticleLayer` advects against a **single snapshot texture** —
every particle sees the same instant forever, which is correct for an
animated streamline and wrong for a drift forecast, where a 48-hour
trajectory must cross 48 hours of changing field.

- That needs a time-indexed stack of textures with interpolation in the
  update pass, or a server-side integrator returning a polyline. **Prefer
  the server-side integrator**: it is testable against known drifter
  tracks, and a trajectory is a *result* the user wants to export, brief on
  and compare — not a visual effect.
- **State the uncertainty or do not ship it.** A single deterministic track
  reads as a prediction of where the object *is*. Operational SAR drift is
  run as an ensemble over perturbed start position, `alpha` and field error,
  and what is drawn is a probability envelope. A lone line on a map, in a
  product someone might actually search from, is the most dangerous thing
  in this file.
- A forecast drift horizon is now possible — the `wind_u`/`wind_v` grids
  exist — but the live field's wind term is still observation-only.

### Explainability for the derived indices (SHAP)

`forecasting/shap_explainer.py` exists and the metric pages render an
Explainability section, but **HAB risk and habitat suitability have no SHAP
path** — the two things a user most wants explained are the two that cannot
answer.

The honest version is not small. `services/predictions.py` deliberately
serves precomputed grids so `machine_learning/` stays out of the backend
import graph, and that boundary is worth keeping. So local attribution means
**exporting per-cell top-k SHAP as a grid** from the ML side, alongside the
prediction grid.

The cheap alternative — serving the global importances already in
`reports/*_shap_*.csv` — answers "what drives this model" rather than "why
is it 0.71 *here*". Worth shipping only if labelled as exactly that.

### ConvLSTM / U-Net for spatial forecasting

**The argument is architectural, not decorative.** `grid_predictor` scores
every cell **independently** — deliberately, to avoid train/serve skew — so
the model cannot see spatial structure at all: not an eddy, not a front, not
the shape of a bloom. A gradient-boosted tree over per-cell features is
structurally blind to the neighbourhood, and that is a real gap a
convolutional model fills.

- Baseline to beat is strong and measured: delta-target LightGBM at skill
  +0.20 vs persistence. **Trees beating neural nets on tabular data is the
  norm** — the claim to make is "DL where trees are provably blind (fields),
  trees where they win (points)", not "DL is better".
- **Start with U-Net segmentation of HAB bloom extent** over chlorophyll
  fields: contained, and 3.9M labelled rows already exist.
- The gridded training data is the expensive prerequisite. The climatology
  build is the same fetch shape and its cached years are a starting point.

### PFZ validation against real catch data / INCOIS advisories

`services/pfz.py` composes raw chlorophyll + SST with a documented but
untested rule (chlorophyll above the local sample's own median, SST inside a
broad band). It has never been checked against real catch data or INCOIS's
own PFZ advisories, which use validated chlorophyll/SST *front* detection —
a genuinely different and more sophisticated technique than a threshold. If
this is going to be presented as more than a screening aid, it needs that
validation pass; the honest caveat currently baked into every response is a
substitute for that, not a step toward it.

### Upwelling corroborated by chlorophyll

The third leg, still blocked on the same thing it always was: there is no
resident chlorophyll field and no long-record chlorophyll climatology to
make an anomaly out of, so "nutrient-rich water reached the surface *and*
something ate it" cannot be said. `services/climatology/build.py` is
variable-agnostic and would fit it — what's missing is a long daily
chlorophyll record to fit on, the same source problem as the anomaly
explorer below. Worth doing *after* the rolling-wind-history item above,
since it inherits whatever that settles about scoring one product against
another's climatology — a chlorophyll baseline fitted on one sensor and
applied to another would repeat the same mistake in a field with a far worse
dynamic range.

### Anomaly explorer

Ranking "SST +2.7σ, chlorophyll +2.1σ" over a point or a box.

**Bounded by sources, not by code.** `services/climatology/build.py` is
variable-agnostic, but OISST serves SST alone, so every further variable
needs a long-record source of its own. Until the climatology covers more
than one variable this is a one-variable feature and not worth shipping.

**The scoring half is now built, though**: `heatwaves.sst_anomaly_field()`
exports the per-cell anomaly and the p10 deficit against the fitted
baseline, and `services/upwelling.py` consumes it across a grid change. A
second variable would reuse that path rather than start one. What is
missing is still only the record to fit on.

**Only variables with a real baseline may appear.** A ranked list that
silently omits half the catalogue is the same failure as an event list that
omits the events a user most expects.

---

## Blocked / parked

Not abandoned — each is blocked on something this workflow cannot self-serve
(a human action, a real live event, an account/API key, an upstream too slow
to call live, or a product decision), not on missing code.

- **Cyclone proximity: forecast cone, not a fixed circle — blocked on GDACS's
  own latency, not an account wall.** `check_point`'s proximity is still a
  circle around the storm's last reported fix. Live-verified 2026-08-28
  against the then-active SAUDEL-26 (`eventid=1001305`) that GDACS really
  does expose per-storm wind-radii/buffer geometry
  (`properties.url.geometry`, `properties.impacts[].resource.buffer74/39` on
  a real `geteventdata` response) — but every one of those sub-resource
  endpoints (`getgeometry`, `getimpact`, `getepisodedata`) failed to respond
  at all within 120 seconds, while `geteventlist`/`geteventdata` themselves
  reliably return in ~20-40s. A per-storm fetch that may never return cannot
  go in a live chat-tool/REST call; the response shape was consequently never
  even observed, so implementing a parser now would mean guessing at a wire
  format rather than verifying it, which is not how any other provider here
  was integrated. See `services/cyclones.py`'s docstring for the full
  finding. **The path that would work**: warm a cache of each currently
  active storm's polygon on a schedule, the same shape
  `services/forecast_warm.py` and `services/eddy_tracking.py` already use for
  a slow upstream, with `check_point` reading it opportunistically and
  falling back to today's circle for any storm with no cached polygon yet.
- **Browser verification of the globe recentre, the drift layers and the
  particle animations.** Agent-driven Chrome tabs are always hidden, so
  `requestAnimationFrame` never fires, the map never initialises and every
  animation freezes — a limitation of the harness, not evidence of a
  problem. Needs one human look at `/map`, which should also check several
  particle systems at once on a mid-range GPU: there are seven possible flow
  layers, each an independent `requestAnimationFrame` + `map.redraw()` loop
  with its own trail framebuffers, and nothing coordinates them.
- **Live browser pass on `/assistant`.** The specialist-name pill on each
  tool call, the delegation line, and the false-refusal banner
  (`AssistantThread.tsx`) have only been verified via the raw SSE event
  stream and a typecheck, not eyeballed in the UI. Same CDP/`requestAnimationFrame`
  limitation as above — needs one human look, not a repeat automation
  attempt.
- **DATRAS/RLS true absences — the biggest accuracy lever, and a product
  call.** ICES DATRAS (trawl surveys with real zero-catch hauls) and RLS
  (reef transects with abundance and real zeros) are the only true-absence
  sources found in the 2026-08-05 survey. They would remove pseudo-absences
  entirely, which is worth more than any change to the classifier. But
  DATRAS is North Atlantic/European and RLS is reef transects, so adopting
  either **relocates the habitat model out of the northern Indian Ocean**,
  which is the platform's reason for existing. That is a decision about what
  the product *is*, not a data-ingestion task. A defensible middle path is a
  *second* model in a DATRAS region, kept beside the regional one as
  evidence of what the pseudo-absence scheme costs.
- **WDPA MPA registry.** The MPA registry is still hand-curated (9 named
  sites, up from 4, each individually verified — see DONE.md), not WDPA.
  WDPA's API needs a registered key (`api.protectedplanet.net` returns 401
  unauthenticated, checked 2026-08-24) and its bulk release is not a plain
  scriptable download either — both real blockers. Getting a key is a human
  action; once one exists, the fetch shape would follow `services/eddies.py`'s
  pattern for a slow-changing reference dataset.
- **Routing search-grid resolution vs. Open-Meteo request volume.** The
  search grid trades resolution for request volume, and the failure mode
  when that trade is too coarse is a hard error (`RoutingError`), not a
  degraded answer — verified live for Palk Strait to the open sea east of
  Sri Lanka (correctly reports no path, since going around Sri Lanka is
  outside the search box). Worth widening the margin/connect radius only if
  real usage hits this often enough to justify it — needs real traffic to
  judge, not more code today.
- **IMD CAP feed's RSS index under a burst of alerts.** Only ever observed
  carrying 7 items — fine for "currently active" but never confirmed against
  the aggregator's own behavior during a real landfall issuing many warnings
  in one day. Re-check during the next actual severe-weather event.
- **Tsunami/marine-warning coverage.** No tsunami source anywhere in
  `backend/services`. Investigated live 2026-08-26 the same way
  `services/cyclones.py`/`services/severe_weather.py` were built: a real
  bulletin viewer exists (`tsunami.incois.gov.in/TEWS/displaybulletinslightweight.jsp`)
  but only given an `eventId` you must already know, with no list/latest/index
  endpoint found to discover it. No RSS/CAP XML feed found at any guessed
  path. **Verdict: infeasible with a keyless request-only probe** — but this
  was a static-probe pass, not a real browser session watching TEWS's own
  network traffic, the way a real browser session is exactly what eventually
  found the tide-gauge feed (see DONE.md) after an earlier static probe
  failed the same way. Worth one more look with that method before calling
  it fully closed.
- **MPA data-quality caveat.** `check_geofence`'s own docstring says the
  Marine Protected Area list is "a hand-curated set of named sites, not a
  surveyed footprint" (EEZ/IMBL geometry is real; MPAs are not). Not a build
  item — just something to say out loud if this is presented as
  authoritative, rather than let a judge/user assume otherwise.
</content>
