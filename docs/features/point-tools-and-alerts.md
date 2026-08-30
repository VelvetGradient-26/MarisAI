# MarisAI — Point Tools, Brief/Compare, and Alerts

> Split out of `CLAUDE.md` on 2026-08-28 to keep the root file lean (it was ~155KB and loaded on every conversation regardless of relevance). Read this file when working in this area; see `CLAUDE.md`'s Feature reference index for the full list.

- Point brief and comparison (`services/brief.py`, `services/brief_pdf.py`,
  `services/compare.py`, `routers/brief.py`, `/compare`) — one coordinate as a
  document, and two coordinates aligned against each other.
  - **Composition, not computation.** Every number already has an endpoint; the
    brief lays them out. Each section carries `available` plus a reason, and
    model output is labelled as model output — stricter here than on screen,
    because a PDF is read where nobody can hover over a blank panel.
  - **`compare.py` is a view over `brief.py`, not a second assembly.** Two
    briefs are gathered and aligned on `(section, row label)`. A parallel
    pipeline would let the two disagree about one coordinate, which is fatal for
    a feature whose entire output is a difference.
    - **A delta is computed only when both sides parse as numbers in the same
      unit**, and the number regex handles thousands separators for the same
      reason the assistant's grounding checker learned to — "1,204 m" read as
      "1" turns a 1,200 m difference into 1 m, in the right units, silently.
    - **A row only one point has is kept and labelled `only_at`.** The asymmetry
      ("suitability 0.71 here, outside the model's region there") is often the
      most informative part; dropping it reports two points as more alike than
      they are.
    - **It does not rank.** No composite score — same reason the Fishing
      Opportunity Index was rejected: there is nothing to validate it against.
  - **Recorded biodiversity comes from OBIS** (`services/biodiversity.py`,
    `GET /api/ocean/biodiversity`, and the brief's last section). Two cheap
    calls — `/v3/statistics` and `/v3/checklist` over a box. **The counts are
    survey effort, not biodiversity**, so `bias_note` is a required field rather
    than small print: record density tracks marine institutes and shipping
    lanes, and it is the *same* bias `fish_habitat`'s target-group background
    exists to correct. Correcting it in the model and printing an uncorrected
    headline beside it would be indefensible. An empty box is an answer with a
    reason, never "nothing lives here" — OBIS is presence-only.
- Agentic tool surfaces on the map (`routers/tools.py`,
  `features/map/hooks/{usePfzZones,useGeofenceStatus,useRoutePlanner,useCyclones,
  useSevereWeatherAlerts}.ts`) — PFZ, geofencing, routing, cyclones and severe
  weather already backed chat tools (`services/chat/tools.py`,
  `services/pfz.py`/`geofencing.py`/`routing.py`/`cyclones.py`/
  `severe_weather.py`) but had no REST route and no map/panel surface outside
  chat (sihtodo.md item 1, closed 2026-08-26). `routers/tools.py` is a second
  `/api/ocean` router beside `routers/marine.py`, not an extension of it — kept
  separate because every endpoint here wraps a service that used to be
  chat-only, which is a different provenance worth being able to find in one
  file. Two of the five never raise (`pfz.find_zones`, `geofencing.check`, both
  either local-cache or pure-local-geometry, per their own docstrings); the
  other three (`routing`, `cyclones`, `severe_weather`) depend on a live
  upstream fetch on *every* call — none is a cache this server warms — so a
  failure there maps to 502, the same split `/biodiversity` already draws
  against `/eddies` in `routers/marine.py`.
  - **The chat response schema was deliberately not touched.** The gap
    analysis that motivated this work also flagged that a chat turn carries no
    structured-geometry field (`map_layers`/`markers`/`polygons`), so a tool
    call inside chat still has nothing for the frontend to render from. That
    is real and unresolved — see the alternative the analysis itself named:
    the five new REST endpoints drive the map layers directly, independent of
    chat, which is what was built. Wiring chat's own turns to the map remains
    open.
  - **PFZ and geofencing are click-triggered, gated on their own layer
    toggle** (`pfz-zones`, `geofence-status` in `layerRegistry.ts`), the exact
    same "layer active -> fetch at the selected point" shape
    `SelectedLocationPanel.tsx` already used for SST/wind/currents/predictions
    — so a heuristic PFZ scan or a geometry check does not run on every map
    click regardless of whether the layer is switched on. Both hooks are
    called from `Map.tsx` like every other data-feed hook (`usePfzZones` needs
    `manager` directly for its hover tooltip's pixel math to line up with
    `.map-root`, not with whatever rail panel happens to render it), and write
    their result into a small new `store/toolsStore.ts` — a one-way mirror,
    same rule `mapStore` follows for MapLibre state — so `SelectedLocationPanel`
    only *reads* the result rather than re-fetching it itself.
  - **`geofencing.check()` grew two additive fields for this**:
    `india_sri_lanka_imbl.nearest_point` (the actual projected point on the
    treaty line, not just its distance) and each `nearby_protected_areas[]`
    entry's `bounds` (the area's real registered box, from `Polygon.bounds` —
    not a simplification, since every entry in that registry already *is* a
    hand-drawn box). Both are additive and covered by new tests
    (`test_geofencing.py`); nothing that already read this dict's original
    keys is affected. **The India EEZ boundary itself is deliberately not
    redrawn in the point-check response** — it would mean shipping a
    multi-hundred-vertex polygon on every click when the existing `eez`
    reference layer (Marine Regions WMS) already renders it; the panel states
    inside/outside and zone as text and leaves the boundary rendering to that
    layer.
  - **Severe weather is a panel/badge, not a map layer, and that split is
    forced by the data, not a style choice.** `_Alert.summary()` in
    `services/severe_weather.py` never exposes the CAP polygon/circle it
    parses internally, so there is no geometry for a `useDetectorCells`-style
    layer to draw — matches sihtodo.md item 1's own framing of severe weather
    as the panel/badge half and cyclones as the map-marker half.
    `useSevereWeatherAlerts.ts` has no `MapManager` dependency at all (the only
    hook here that doesn't) and polls independently of any panel-open state,
    so a collapsed badge still carries a live count;
    `store/uiStore.ts`'s new `hazardsPanelOpen` defaults to collapsed because
    most visits have nothing to report.
  - **Cyclones reuse the polling shape but not the hook** `useDetectorCells`
    already provides for heatwaves/upwelling (global, timer-refreshed, no bbox
    — GDACS's whole active-storm list is a handful of features worldwide, the
    same reasoning that hook documents). `useCyclones.ts` is its own hook
    instead because a storm benefits from the same per-feature hover tooltip
    `useEddies` has, which the generic cell hook does not provide. Marker
    colour is GDACS's own three-level alert scale (Green/Orange/Red), not a
    wind-speed category this app assigns.
  - **Routing has no click-two-points map interaction** — there was none to
    extend (`services/routing.py`'s own docstring is about the *backend*
    replacing a three-candidate line, not a frontend that existed for it, and
    the guide agent that scoped this confirmed zero frontend route-planning UI
    existed anywhere, chat included). Instead `store/routeStore.ts` holds two
    points set via `SelectedLocationPanel`'s "Set as start"/"Set as
    destination" buttons acting on the same shared `selectedLocation` every
    other panel section already reads, and `useRoutePlanner.ts` (called from
    inside the panel via `useMapManagerContext()`, since drawing the result
    needs no hover/pixel-math and so has none of `usePfzZones`'s reason to live
    in `Map.tsx` instead) turns the `planned-route` layer on and feeds it on a
    successful plan. Line colour is the route's overall `hazard_level`.
  - **Boundary watch — notifications when approaching a boundary, from the
    device's own live position (sihtodo.md item 9, closed 2026-08-27),
    entirely frontend.** The item's own framing ("needs an actual position
    feed... no AIS/GPS input exists here") was about server-side ingestion;
    the browser's own Geolocation API is that position feed, and needs no
    new backend surface at all — `useBoundaryWatch`
    (`features/map/hooks/useBoundaryWatch.ts`) calls
    `navigator.geolocation.watchPosition`, throttles to one check per 15s,
    and re-calls the existing `GET /api/ocean/geofence` (item 1, above) on
    each fix. Detection is edge-triggered, not level-triggered — a pure
    function, `evaluateBoundaryEvents`, fires once on the false->true
    transition into "near" (tracked via `wasNearImbl`/`nearMpaNames`
    threaded through, not recomputed each tick), so lingering near a
    boundary for minutes does not spam an event every 15 seconds. Three
    event types: an actual EEZ inside/outside crossing (always fires, no
    dedup needed — a crossing is inherently discrete), approaching the
    India-Sri Lanka IMBL, approaching/entering a Marine Protected Area.
    `BoundaryWatchPanel` mirrors `SevereWeatherPanel`'s badge+panel
    convention exactly (collapsed by default); unlike that badge, here the
    badge is *only* the open/collapse toggle and starting/stopping tracking
    is its own button inside the body, since a user opts in once and then
    just glances at the badge. State lives in a new `boundaryWatchStore`,
    deliberately **not** persisted (no `persist` middleware, unlike
    themeStore/timezoneStore) — a location-permission session must default
    off on every fresh page load, not silently resume watching position.
    - **Verified live, and it caught a real bug before shipping.** No
      frontend test runner exists in this repo (confirmed via
      `package.json` — no vitest/jest, no `test` script), so verification
      was `npm run dev` plus a stubbed `navigator.geolocation` driven
      through Chrome's automation protocol (real GPS movement isn't
      available here). Stepping through real coordinates near Rameswaram/
      Adam's Bridge fired an MPA-approach event (Gulf of Mannar, 5.6 km),
      then an IMBL-approach event (14.6 km) without re-firing the
      already-active MPA one, then an EEZ-crossing event on actually
      leaving the mainland zone, with the still-near IMBL event correctly
      not re-firing either — the dedup logic works as designed. That same
      live testing is what caught the bug: the permission-denied path
      originally called two separate store writes in sequence (set the
      error message, then a generic `disable()`), and `disable()`'s own
      reset of `unavailableReason` to null silently clobbered the message
      that had just been set — invisible from reading either function
      alone, only visible by actually triggering the path. Fixed with one
      atomic `disableWithError` action that sets every field in a single
      `set()` call.
    - **No live position marker is drawn on the map.** The item asks for
      notifications, not a tracking display, and none of `layerRegistry.ts`'s
      existing categories (`ocean`/`flow`/`ai`/`reference`) fit a
      self-locating aid tied to an ephemeral tracking session rather than a
      toggleable data overlay — left for later. Polygon/route-ahead
      prediction is likewise out of scope, matching the point-first scoping
      discipline the earlier (dropped, see below) subscribable-alerts design
      applied to itself.
    - **A different, previously-shelved feature was investigated and
      explicitly not built this round.** sihtodo.md item 8 (proactive email
      alerts) turned out to have already been designed in detail and then
      dropped from TODO.md on 2026-08-17 at the user's request (`git show
      8618f77`) — its scoping notes (double opt-in, a signed unsubscribe
      token independent of `client_id`, "the scheduler job must not fetch,"
      bloom alerts at +3d only, no webhooks) are real and still the right
      design if that feature is ever revisited, but weren't rebuilt here.
      Investigating it surfaced genuine orphaned state: the local dev
      Postgres carried an `alerts.subscriptions` table and an
      `alembic_version` pointing at a migration file that existed in no
      branch — a prior attempt that got as far as applying a migration
      locally before the code was reverted, without ever running `alembic
      downgrade`. Confirmed empty, dropped, and Alembic re-stamped to the
      real head (`0148ba922c31`) — `alembic current` is clean again. Worth
      remembering if `alembic current` ever mismatches what
      `alembic/versions/` holds again: check for this class of drift before
      assuming the migration history itself is broken.
  - **Item 4 (controlled internet tools) closed 2026-08-27 — see the "Ocean
    Assistant" section's own subsection on it, above.**
  - **This entire section was, until 2026-08-26, sitting on an unmerged
    branch (`worktree-sihtodo-item1`) despite this file describing it as
    shipped.** The branch was clean, pushed to origin, and simply never
    merged into `main` — `routers/tools.py` did not exist on `main` until it
    was. Same for sihtodo.md item 3's glossary guardrail
    (`worktree-sih-item-3-glossary`, see the Ocean Assistant section below).
    Both merged with zero conflicts and the full suite passed immediately
    after. **A "closed \<date\>" docstring is a claim about a branch, not
    proof the branch reached `main` — check before building on top of
    documented-but-unverified work.**
- Deterministic risk assessment and cross-variable correlation
  (`services/marine_risk.py`, `services/correlation.py`) — sihtodo.md items
  10 and 7, closed 2026-08-26. Both extend the tool surface item 1 built
  rather than replacing any of it.
  - **`assess_marine_risk` runs the four live "is it safe" checks
    (`get_current_conditions`, `get_severe_weather_alerts`,
    `get_cyclone_alerts`, `check_geofence`) and reduces them through a fixed
    rule table**, so the same underlying conditions always produce the same
    `risk_level` (low/moderate/high/extreme) rather than a verdict that
    varies with how the model phrases a turn. Escalation only ever goes up,
    and only from a check that actually returned data — a failed sub-check
    (a dead upstream) lands in `could_not_verify`, never silently read as
    "safe". Boundary/Marine Protected Area proximity is a legal/navigational
    caution, not a weather hazard, so on its own it can only reach
    "moderate" — it never combines with calm seas to read as "extreme" the
    way an active cyclone does. Wired into the `weather_safety` specialist
    (its system prompt now tells the model to call this rather than
    synthesising a verdict itself from the individual tools) and exposed at
    `GET /api/ocean/risk`, following `routers/tools.py`'s convention exactly
    — it never raises, so no error-mapping is needed there.
  - **`analyze_variable_correlation` aligns 2-4 variables to a shared daily
    cadence before computing pairwise Pearson correlation** — the identical
    aggregate-before-merge ordering the Universal Ocean Data Downloader's
    `cleaning.py` already established for the same reason (mixing an hourly
    reading against a different variable's daily mean under no shared clock
    silently misrepresents both). Every response carries a fixed
    correlation-is-not-causation disclaimer and the tool/specialist prompts
    are worded "moved together", never "caused" — the model is a more
    effective source of over-claiming than any user, and nothing downstream
    would catch a causal sentence this tool's own output invited. Built on
    `services/dashboard/trends.py::multi_series`, which already existed;
    fishing effort and the upwelling index are **not** offered as variables
    — neither has a point historical series anywhere in this codebase (GFW
    is a raster tile proxy with no per-point endpoint; upwelling computes
    live with no archive) — stated in the module docstring rather than
    silently doing less than sihtodo.md's own example implied. Wired into
    `ocean_analytics`; REST at `GET /api/dashboard/trends/correlation`
    (400 on a malformed request — bad variable count or an hourly-only
    range — the same client-correctable class `TrendsError` already gets).
  - Both tools push the count in `test_chat.py::test_every_tool_declares_a_
    description_and_schema` from 15 to 17.
  - **sihtodo.md items 5, 6, 12 were investigated the same day** (probe
    live, document the finding, don't assume) — verdicts in DONE.md. Item 5
    (INCOIS/MOSDAC PFZ feed): infeasible — a real keyless GeoServer exists
    but serves only raw SST/chlorophyll rasters, zero vector FeatureTypes.
    Item 12 (INCOIS tsunami feed): infeasible with a keyless probe, same
    verdict RSMC New Delhi's cyclone bulletins got. Item 6 (Indian tide
    data): still open, not closed — a shallower pass than 5/12, worth a
    second look with a real browser session against the live TEWS map.

- Tide-gauge sea level (`services/tides.py`, chat tool `get_tide_level`,
  `GET /api/ocean/tide`) — sihtodo.md item 6, closed 2026-08-27 after being
  left open the day before. The 2026-08-26 static-probe pass (portal pages,
  guessed endpoint paths) found nothing; a real browser session watching
  `tsunami.incois.gov.in/TEWS/`'s own network traffic while clicking a
  tide-gauge marker on the map found it in minutes — the lesson item 6 itself
  predicted, now confirmed rather than assumed.
  - **The feed is two endpoints the map's own JS calls with no auth**:
    `/itews/homexmls/TideStations.xml` (~50 Indian stations, position +
    Reporting/Not Reporting status) and `/itews/JSONS/{STATION_REAL_NAME_
    UPPERCASE}_{1,7,30}.json` (that station's sea-level series at 1-minute
    cadence for the last 1/7/30 days — verified, all three windows, same
    cadence throughout). `nearest_station()` only ever fetches the `_1`
    window; a longer history was not needed for "what is the tide doing now".
  - **This is measured real-time sea level, not a predicted tide table, and
    the response says so on every call.** It folds in storm surge and wave
    setup along with the astronomical tide. INCOIS's actual tide-*prediction*
    page (`ITCOocean/tides.jsp`) still 404s exactly as the original probe
    found — that specific gap is real and this does not close it, it answers
    an adjacent, arguably more useful question instead ("what is the water
    doing right now" beats a prediction for a fisherman about to go out).
  - **The series' timestamp is not a real epoch, found by cross-checking the
    JSON against the station page's own displayed numbers.** Naively decoded
    as epoch-milliseconds, the last point of `GARDENREACH_1.json` lands in
    the year 126 — every other field (month/day/hour/minute, and the water
    level) matched the page's displayed "Last Reported Date&Time(UTC)" and
    "Last Reported Value(m)" exactly. The gap is exactly 1900 years on every
    point, every station, every window tried: the classic legacy
    `java.util.Date(year, month, day)` constructor (which takes `year -
    1900`) evidently got round-tripped through epoch-millis math server-side
    without the 1900 ever being added back. `_decode_timestamp` corrects only
    the year field — adding a fixed millisecond offset would drift across
    1900 years of leap-year differences and not reproduce the display exactly
    the way replacing the year does.
  - **A "Not Reporting" station's series is `[{"data": []}]`, not a 404 or
    frozen stale values** — verified live against `VISAKHAPATNAM_1.json`
    while its own station-list entry reads `Not Reporting`. `nearest_station`
    prefers a `Reporting` station over a closer `Not Reporting` one, and
    falls back to the nearest `Not Reporting` one with a plain "not currently
    reporting" answer rather than claiming no station exists at all — the
    same `available`/`reason` discipline as everywhere else in this file.
  - **INCOIS's own "Reporting" status flag lags reality, so it is not
    trusted alone.** Chennai read `Reporting` live 2026-08-27 while its own
    latest point was ~3.8 hours old. `nearest_station` computes staleness
    itself (`stale: true` past 60 minutes) rather than repeating the
    station list's word for it, the same "don't trust the index, check the
    data is actually there" lesson `copernicus_wind.py`'s NRT trailing-NaN
    check already encodes for a different provider.
  - **`tsunami.incois.gov.in` fails Python's default TLS verification —
    curl and a browser reach it fine, `httpx` does not.** `openssl s_client
    -showcerts` shows the handshake carries only the leaf certificate,
    issued by "GlobalSign RSA OV SSL CA 2018"; the server never sends that
    intermediate. `certifi`'s bundle holds GlobalSign's *root* but not this
    intermediate, so strict verification fails with "unable to get local
    issuer certificate" — browsers/curl tolerate the gap via OS-level
    Authority Information Access fetching or a cached intermediate, Python's
    `ssl`/`certifi` path does not attempt either. `services/tides.py` builds
    an `ssl.SSLContext` from `certifi`'s roots plus this one intermediate
    (fetched once from GlobalSign's own AIA URL and embedded in the module,
    valid until 2028-11-21) rather than fetching it at request time or
    disabling verification. This is the first place this codebase's backend
    talks to `*.incois.gov.in` directly over TLS from Python — every other
    INCOIS-adjacent service here (PFZ's Copernicus fetch, the S3-hosted IMD
    CAP feed, GDACS) never hit this host, which is why the quirk surfaced
    only now. `certifi` is declared as a direct `pyproject.toml` dependency
    (previously only transitive, via `httpx`) since this module imports it.
  - **Deliberately scoped to the India-only station list.** The same feed's
    `TideIntStations.xml` lists 832 more stations worldwide (part of the same
    global tsunami-warning network — Sri Lanka, Maldives, Pakistan,
    Bangladesh, Oman all present), left for later: MarisAI's coastal-
    fisherman use case is India-scoped everywhere else in this codebase, and
    the naming convention (uppercase real name -> JSON filename) has only
    been verified against India's ~50 single-word station names.
- Feedback (`services/feedback.py`, `pages/FeedbackPage.tsx`): Gmail SMTP via
  stdlib `smtplib`, needs `SMTP_USERNAME`/`SMTP_PASSWORD` (a Google App
  Password) in `backend/.env` to actually send.
- Proactive alert watches (`app/models/alerts/`, `services/watch_tokens.py`,
  `services/watch_alerts.py`, `routers/watch.py`, `SelectedLocationPanel.tsx`'s
  "Watch this location" section, `pages/{Confirm,Unsubscribe}WatchPage.tsx`)
  at sihtodo.md item 8, closed 2026-08-27 — a subscription row plus a
  scheduled evaluation pass that emails a confirmed address when severe
  weather, a cyclone, or harmful algal bloom risk appears at a saved point.
  - **This is the second time this feature was built.** It was designed in
    detail on 2026-08-17 and then explicitly dropped at the user's request
    (`git show 8618f77`, "Subscribable alerts removed as requested") — the
    dropped design's scoping notes (double opt-in, a signed token
    independent of `client_id`, no webhooks, +3d-only bloom alerts, point
    triggers only) survived only in git history and are exactly what got
    rebuilt here, recovered by reading that commit before designing anything
    new. **Investigating this item first turned up real orphaned state**: the
    local dev Postgres carried an `alerts.subscriptions` table and an
    `alembic_version` pointing at a migration revision that existed in no
    branch — the earlier attempt had run a migration locally, then the code
    was reverted without ever running `alembic downgrade`. Confirmed empty,
    dropped (`DROP SCHEMA alerts CASCADE`), and Alembic re-stamped
    (`alembic stamp --purge 0148ba922c31`, the real head) before this
    session's migration was written — `alembic stamp` alone errored on the
    same phantom-revision problem `alembic upgrade`/`current` did; `--purge`
    was needed to actually clear the stored version row rather than trying
    to validate a path to it. Worth remembering if `alembic current` ever
    disagrees with what `alembic/versions/` holds again: check for this
    class of drift (an abandoned feature's migration applied then reverted
    in code only) before assuming the migration history itself is corrupt.
  - **`client_id` scopes "my watches"; a signed token, not `client_id`,
    gates whether mail actually gets sent.** Creating a watch only opens it
    (`confirmed_at IS NULL`) — no alert is ever sent to an unconfirmed
    address. `services/watch_tokens.py` is hand-rolled HMAC-SHA256
    (payload `"<id>:<purpose>:<expires_at>"`, `hmac.compare_digest`d against
    a `WATCH_TOKEN_SECRET` setting) rather than a new dependency —
    itsdangerous/pyjwt do not appear anywhere in this backend already, and a
    purpose-scoped, timed, signed token is small enough to match this
    codebase's standing "stdlib over a package for a narrow need" choice
    (`services/webpage.py`'s `html.parser`, `severe_weather.py`'s stdlib
    `ElementTree`). The signature covers the *purpose* too, not just the
    subscription id — verified by test, a confirm token does not also work
    as an unsubscribe token. Confirm tokens expire in 24h; unsubscribe
    tokens in 1 year, since an unsubscribe link must keep working for as
    long as the subscription might still be sending mail, from any device,
    not just the one that created it.
  - **A real ordering bug was found and fixed by actually testing the
    permission-denied-shaped path, not by reading the code**: an early
    version of the `PERMISSION_DENIED`-equivalent error path called a bare
    "set the error message" function, then a separate `disable()` call —
    `disable()` unconditionally resets the message field to `null`, so the
    two sequential writes raced and the just-set message was silently
    clobbered before it ever reached a caller. (This specific bug is
    `useBoundaryWatch`'s from sihtodo.md item 9, not this feature's own —
    recorded here because it is the same *class* of bug this feature's own
    `disableWithError`-shaped atomic writes in `services/watch_alerts.py`
    were written to avoid from the start, having watched it happen once
    already this session.)
  - **"The evaluation job must not turn N subscriptions into N live
    upstream fetches" is satisfied by construction, not by extra
    plumbing.** `services/severe_weather.py` (IMD CAP) and
    `services/cyclones.py` (GDACS) are each a single worldwide feed behind
    an in-process TTL cache (10 min / 15 min) — `check_point(lat, lon)`
    fetches the whole feed once and filters locally, so N subscriptions
    checked in one scheduler tick cost at most one real fetch per feed,
    however many subscriptions share it.
    `services/predictions.py::hab_point` (bloom risk, **+3d only** — +7d
    precision is 0.202, too many false alarms) is a pure in-memory read
    over an `lru_cache`-held NetCDF grid, zero network ever.
  - **"High waves" — named explicitly in the PS — is a stated v1 scope cut,
    not a silently missing signal.** `services/ocean_state.py` (which backs
    the dashboard's own wave alert) reduces its global wave grid to
    min/max/p90/p99 and **discards the grid** — there is nothing left to
    sample at an arbitrary point, confirmed by reading `_area_weighted_stats`
    before assuming a point-level reader existed. A forecast-grid
    workaround (`forecast_tiles.point(...)["last_observed"]`, the anchor
    field a trained variable's grid already carries) exists in principle
    but depends on `significant_wave_height`/`maximum_wave_height` happening
    to have a trained model and was not built for this purpose — left as a
    stated gap. `assess_marine_risk`/`get_active_alerts` remain the
    pull-based way to check wave height today.
  - **Dedup is by a signature, not a boolean "already notified" flag.**
    `last_alert_signature` is the sorted, comma-joined set of currently-
    active alert ids (`severe:<CAP url>`, `cyclone:<name>`, `bloom`) — an
    email sends only when this *changes*, so an ongoing, unchanged cyclone
    does not re-notify every 15-minute tick, but a second, different alert
    appearing alongside it does, and the same cyclone clearing then
    reappearing later does too (the stored signature goes empty on clearing,
    so the next sighting reads as new again). No "all clear" email in v1 —
    a stated scope cut, not an oversight.
  - **Verified live against the real local Postgres and real Gmail SMTP**,
    not just mocked: the full create → confirm → unsubscribe round trip
    through the actual browser (not curl) for both pages, including the
    invalid/expired-token error state; CORS confirmed working cross-origin
    from the Vite dev origin to the backend. **One real, measured finding**:
    a confirmation-email send takes **~17 seconds** end-to-end in this
    environment — slow enough that several curl/browser test timeouts (5s,
    10s, 45s) fired and read as a hung request before the send actually
    completed a little later. Not a bug — `services/feedback.py`'s own
    submit endpoint has the identical synchronous-within-the-request-thread
    shape already (`await asyncio.to_thread(_send_sync, ...)` blocks the
    HTTP response, not the event loop); this is only the first time that
    latency was actually measured rather than assumed fast. Every send
    during this verification pass went to a reserved, non-deliverable test
    domain (`example.com`/`example.org`) — several were triggered
    inadvertently while what looked like a hang was being diagnosed, a
    process lapse worth naming rather than glossing over: sending mail
    should have paused for confirmation the moment a real send was suspected,
    not after several had already gone out.

