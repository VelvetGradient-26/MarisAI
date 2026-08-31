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

- Closed-SSH-contour detection as a cross-check on the count — tried
  2026-08-28, not viable as a quick addition. See DONE.md's "`py-eddy-tracker`
  cross-check — tried, and not viable without a legacy environment": the
  PyPI package (`pyeddytracker`) is numpy<1.23-pinned by its own maintainers
  and, even shimmed past that, breaks inside Matplotlib's own contour
  internals (not a renamed symbol — a real structural change). Revisit only
  with a dedicated legacy-pinned environment, not as an addition to this
  backend's own dependencies.
- **No map layer or chat tool yet** for eddy tracks — `GET
  /api/ocean/eddies/tracks` exists and is tested, but nothing visualises a
  track's path the way `/eddies` itself is drawn. Do this once the atlas
  comparison above says the tracks are trustworthy enough to show.

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

The criteria, unchanged as the ongoing bar new work should keep meeting:

- **Three surfaces carry the product**: the landing page, `/map`,
  `/dashboard`.
- **Criteria, not vibes**: one type scale used everywhere (audit for
  literals bypassing the tokens); a real empty / loading / error state for
  every panel; the contrast floors the map ramps already meet (≥3:1 against
  the Abyss basemap, ≥2:1 for the hatched unforecastable mark) applied to the
  chrome too.

**A first dated audit-and-fix pass against this bar shipped 2026-08-30** —
see DONE.md's "The visual standard" entry for the measured findings (a
missing dashboard type scale, two real contrast failures, states already
solid everywhere they were checked). One judgment call it deliberately left
open: `eddy-status__dot--live`'s light-mode contrast vs. its pinned match to
the eddy layer's own map ramp colour. Re-audit next time a new panel or
surface is added rather than assuming this pass covers it forever.

---

## Hard

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
- **Multiple flow layers running concurrently on a mid-range GPU — the one
  piece the first browser pass didn't cover.** Globe recentre and each of
  the seven flow layers individually were human-verified working in a real
  browser 2026-08-31 (CDP-driven tabs can't run this check at all —
  `requestAnimationFrame` never fires there, so this genuinely needed a
  human look, and now has had one; see DONE.md's "Browser verification:
  globe recentre and flow-layer particle animations"). What's still
  unchecked is several of those seven independent `requestAnimationFrame` +
  `map.redraw()` loops and trail framebuffers running *at once*,
  uncoordinated, on a mid-range GPU — a contention/perf question one-at-a-
  time checking cannot answer.
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
