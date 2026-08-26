# SIH TODO

Gap list against the SIH problem statement (Agentic AI marine conversational
platform) and the guide's follow-up spec, checked against the actual repo
state on 2026-08-26 — not against CLAUDE.md, which is stale on this section.
PFZ, geofencing, routing, cyclones and severe-weather alerts already exist as
chat tools (`services/pfz.py`, `services/geofencing.py`, `services/routing.py`,
`services/cyclones.py`, `services/severe_weather.py`, wired into
`services/chat/specialists.py`) but have **no REST router and no frontend
surface** — confirmed by grep: nothing under `backend/*/routers/` references
any of the five, and nothing under `frontend/src` renders them outside the
docs chapters (`Habitat.tsx`, `Features.tsx`, `Overview.tsx` mention them as
text, not UI). That gap is item 1 below and is the highest-leverage item: the
computation is already done, only the visibility is missing.

Ordered easiest → hardest, per the ranking already discussed in chat.

---

## 1. Surface the five existing chat-only tools in the UI

Nothing to build algorithmically — this is routing + a map/response layer over
work that already exists and is already tested.

- **PFZ** (`services/pfz.py`): add a router endpoint (e.g.
  `GET /api/ocean/pfz`), return nearest-zone geometry/coordinates, add a map
  marker/layer so "nearest PFZ" renders a pin, not just a chat sentence.
- **Geofencing** (`services/geofencing.py`): endpoint (e.g.
  `GET /api/ocean/geofence?lat=&lon=`), render the India-EEZ / MPA polygon the
  point falls in (or nearest boundary) as a map overlay, not just JSON in a
  tool response.
- **Routing** (`services/routing.py`): endpoint to run the A* search and
  return a route geometry; draw the planned route as a line layer, distinct
  from the old three-candidate line it replaced.
- **Cyclones** (`services/cyclones.py`, GDACS feed): endpoint + map markers for
  active tracks, distinct from severe-weather alerts.
- **Severe weather** (`services/severe_weather.py`, IMD CAP feed): endpoint +
  an alerts panel/badge, since this is the platform's actual answer to "any
  lightning alerts in my area" (cyclones.py is the "cyclone" half — see that
  module's own docstring on the split).

Each of these should follow the existing router convention (thin router,
service-specific exception → real HTTPException, no raw provider traceback —
see `routers/marine.py`, `routers/tiles.py`) and the existing
`available`/`unavailable_reason` pattern used everywhere else in this
codebase, rather than inventing a new response shape per endpoint.

**This item is bigger than "add five endpoints" — confirmed the chat
response itself carries no structured geometry at all.** Grepped
`routers/chat.py`/`services/chat/agent.py`: no `map_layers`/`markers`/
`polygons` field anywhere, the response is text + sources only. So even
once a tool call happens inside chat, there is nothing for the frontend to
render on the map from it. A REST endpoint per tool is necessary but not
sufficient — the chat response schema needs a structured-geometry field too
(per the guide's section 17), or the map layers have to be driven by the new
REST endpoints directly rather than by the chat turn.

## 2. Multi-agent orchestration framing

`services/chat/specialists.py` already has three named specialists with
per-tool allowlists — confirm the second/third specialists' names and whether
they map cleanly onto the PS's suggested roles (planning, risk assessment,
visualization, reporting), and only rename/split where the mapping is
genuinely unclear. This is mostly a documentation/labeling pass, not new
architecture — CLAUDE.md doesn't currently document `specialists.py` at all,
which should be fixed alongside this so the next session doesn't repeat the
mistake made in this one (assuming PFZ/geofencing/routing didn't exist).

## 3. Regional Indian language support

Confirmed absent — no hits for language/multiliteral/Hindi/Kannada/etc.
anywhere under `backend/services`. Needs: language detection on the incoming
message, response generation in the detected language, and a fixed glossary
for terms that must not be mistranslated (SST, chlorophyll, wave height, wind
speed, cyclone, PFZ, marine advisory — per the guide's section 16). Likely the
cheapest of the three genuinely-missing capabilities, since the LLM
(`LLM_PROVIDER=gemini`, per `backend/app/core/config.py`) can plausibly do
both detection and generation directly with a prompt change plus a
terminology-consistency check — no new data source, no new algorithm.

## 4. Controlled internet tools — closed 2026-08-26

`web_search`, `fetch_webpage`, `search_scientific_literature` — confirmed
absent (no hits under `backend/services`). Needed for the guide's example
("why is the Arabian Sea unusually warm this week?"). Must preserve
provenance (title, URL, source, date, snippet) per section 3/13/14 of the
guide, and the response must distinguish retrieved facts from model
inference — this codebase already has that discipline for tool-grounded chat
(`agent.py`'s grounding check), so the new tools need to feed the same
mechanism rather than bypass it.

**Built**: a fourth chat specialist, `web_research` (`services/chat/
specialists.py`), rather than three top-level tools — these are live external
measurements like every other specialist's tools, not static self-knowledge
like `get_documentation`, so routing them through a delegate loop is what
makes them share the existing `Ledger`/grounding check for free (no new
checker was written; `_ungrounded_numbers`/`_false_refusal` already scan the
whole ledger regardless of which specialist populated it). Three modules,
one per capability: `services/literature.py` (Crossref, keyless, **verified
live** 2026-08-26 — Semantic Scholar was tried first and rate-limited 429 on
the first unauthenticated request), `services/web_search.py` (Tavily, gated
on `TAVILY_API_KEY`, **unverified against a live key** — none exists in this
environment, so re-verify before trusting it the way this codebase's other
integrations have been trusted), and `services/webpage.py` (generic fetch, no
provider — its risk is SSRF, not upstream flakiness, so it resolves the
target host itself and rejects private/loopback/link-local/reserved
addresses before connecting, re-validating every redirect hop). Full
findings in DONE.md.

## 5. Direct INCOIS/MOSDAC advisory ingestion — investigated 2026-08-26, no usable feed found

`services/pfz.py`'s own docstring is explicit that it is a heuristic proxy
(chlorophyll-above-local-median + SST band), not INCOIS's actual validated
PFZ advisory. Investigated whether INCOIS exposes a machine-readable PFZ feed
(WMS/WFS/JSON), the way `services/cyclones.py` and `services/severe_weather.py`
did for IMD — probed live 2026-08-26, verdict below. Full findings in DONE.md.

**INCOIS does run a real, live, keyless GeoServer**
(`incois.gov.in/geoserver/PFZ-TUNA-SST-CHL/{wms,wfs}`, both `GetCapabilities`
200) — but it only serves the underlying satellite SST/chlorophyll rasters as
WMS tiles (`sst`, `chl` layers), the same raw fields `copernicus_sst.py`/
`copernicus_chlorophyll.py` already fetch. Its WFS `GetCapabilities` lists
**zero vector FeatureTypes** — no queryable PFZ zone geometry exists here at
all, confirming there is nothing to align against the existing heuristic. Two
other endpoints referenced in the portal's own JS
(`/geoportal/pfzjsondata/OSF_Json/<date>_..._current_0m.json`, a per-day
ocean-current JSON; `/thredds/wms/pfz/`, a THREDDS raster server) exist in
principle but are currently dead — 404 across the last 11 days and a 500 on a
guessed dataset name respectively. The actual validated PFZ advisory (1223
coastal nodes, INCOIS's own marketing figure) is distributed only via
`PfzWebGis`/`PfzAdvisory`/`TextDataHome` HTML/text pages — scraping, not an
API, and out of scope here.

**MOSDAC's "API based Access" and "Order Data" sit behind a login/SignUp
wall** (`mosdac.gov.in`'s own nav requires an account) — same Tier 2 gated
posture as GFW/Movebank/AIMS in CLAUDE.md's existing survey, not a keyless
integration.

**Verdict: `services/pfz.py`'s heuristic proxy remains the ceiling.** This
was a real possible outcome the item itself named ("may turn out infeasible")
and it is what was found — not a shortcut skipped.

## 6. Tide data — a hard gap, and the PS names it explicitly — investigated 2026-08-26, still open

`services/download/registry.py`'s `tidal_height` entry is `available=False` —
no global source is wired at all (per CLAUDE.md, no global tidal product was
found when the downloader was built). The PS's own example query — "*What are
the tide, weather, and sea conditions near my fishing location?*" — cannot be
fully answered today; the tide half is silently missing. Investigated a
source hunt scoped to Indian ports (INCOIS/IHO tide-station feeds are
typically per-station, not global — fine for a fisherman's near-coast query).

**No live, keyless, machine-readable INCOIS tide feed was found, probed
2026-08-26.** `incois.gov.in/ITCOocean/tides.jsp` (astronomical tide
predictions) 404s outright. The real-time tide-gauge network genuinely exists
— 36 stations, 1-5 min cadence, per INCOIS's own published description — but
every portal page probed (`tsunami.incois.gov.in/TEWS/Abouttideguage.jsp`,
`services.incois.gov.in/iogoos/indoos/insitu_sealevel.jsp`, the TEWS map
app's `app.js`/`custom.js`) is either informational-only or renders without
an inspectable JS-driven data endpoint; a `UpdateReportingStations.do?stType=
TIDE` URL surfaced by search 404s. Full probe log in DONE.md.

**Still open, not closed as infeasible** — unlike item 5's PFZ verdict, this
was a shallower pass (no account/dev-tools session against the live TEWS map
to watch its actual network requests, which would likely reveal the real
per-station data endpoint the map itself must be calling). A `WorldTides`/
harmonic-constituent-model alternative (global tide prediction independent of
INCOIS) was noted but not evaluated — a materially larger scope, not a
source-hunt shortcut. Worth a second pass with a real browser session before
concluding this is a dead end the way item 5 was.

## 7. No causal/correlation tool for "why has X declined" — closed 2026-08-26

`get_historical_series` (`services/chat/tools.py`) only returns summary
statistics for one variable at one point over a time range — there is no tool
that aligns SST + chlorophyll + currents + upwelling + fishing effort over
time and looks for correlations, which is what the PS's "*why has fish
productivity declined in this region?*" and the guide's section 10 ask for.
Real analytical work: temporal/spatial alignment across heterogeneous series,
then a correlation/statistics pass — and the response has to keep "observed
relationship" separate from "possible explanation" separate from "established
finding," the same causation-vs-correlation discipline the guide's section 10
demands. Comparable in difficulty to route optimization, maybe harder, since
the hard part is the response discipline, not the statistics.

**Built**: `services/correlation.py` (`analyze()`) aligns 2-4 variables to a
shared daily-aggregated cadence — the exact aggregate-before-merge ordering
`services/download/cleaning.py` established — then reports pairwise Pearson
`r`, strength, significance and a fixed correlation-is-not-causation
disclaimer. Chat tool `analyze_variable_correlation`, wired into
`ocean_analytics`; REST at `GET /api/dashboard/trends/correlation`. Fishing
effort and the upwelling index are deliberately not offered as variables —
neither has a point historical series in this codebase (see the module
docstring). `tests/test_correlation.py` + two router tests in
`test_dashboard.py`.

## 8. Alerts are pull, not proactive

The PS asks for "*proactive alerts for adverse weather, high waves, lightning,
cyclones*." Today `get_active_alerts`/`get_cyclone_alerts`/
`get_severe_weather_alerts` only fire when a user asks inside chat, and the
dashboard's alert panel is likewise something a user has to visit. Nothing
watches a saved location and pushes a notification (email/SMS/in-app) without
the user opening the app. `services/feedback.py`'s Gmail SMTP is the closest
existing plumbing to reuse for delivery; the missing piece is a scheduled job
that evaluates saved locations against the existing alert/cyclone/severe-
weather services and a place to store "this user cares about this location"
(same `client_id`-scoping question CLAUDE.md already answers for chat
sessions — reuse it, but note a delivery target raises the stakes the same
way CLAUDE.md's chat-session section already warns about).

## 9. Geofencing is a snapshot, not a boundary-crossing trigger

`check_geofence` answers "is this point inside a zone" for one coordinate on
demand. The PS wants "*notifications when approaching* international maritime
boundaries, restricted waters, [...]" — that implies tracking a vessel's live
position over time and firing when it nears a boundary, not a single
point-in-time query answered once in chat. Meaningfully harder than item 1's
"surface it in the UI": it needs an actual position feed, and nothing in the
codebase currently ingests a user's own vessel position (no AIS/GPS input
exists here — GFW's AIS data is about *other* vessels' effort, not the
user's own location).

## 10. No deterministic risk-assessment tool for "is it safe to venture" — closed 2026-08-26

Answering that question today means the LLM independently calls
`get_current_conditions` + `get_active_alerts` + `get_severe_weather_alerts` +
`get_cyclone_alerts` + `check_geofence` and synthesizes a verdict itself,
turn by turn. The guide's section 7 wants one deterministic
`assess_marine_risk` tool that combines these under fixed rules, so a
safety-critical verdict doesn't vary with how the model happens to phrase its
reasoning. Debatable priority — the current LLM-orchestrated approach is
arguably more in the spirit of "agentic," just less consistent for a
safety-critical answer — but worth a decision either way rather than leaving
it implicit.

**Built**: `services/marine_risk.py` (`assess()`) runs the four live checks
(sea conditions, IMD severe weather, cyclones, geofencing) and reduces them
through a fixed rule table to `risk_level` (low/moderate/high/extreme) —
escalation only ever goes up, and only from a check that actually returned
data (a failed sub-check lands in `could_not_verify`, never silently read as
"safe"). Chat tool `assess_marine_risk`, wired into `weather_safety`; REST at
`GET /api/ocean/risk`. `tests/test_marine_risk.py` + two router tests in
`test_tools_router.py`.

## 11. Data-quality caveat to state, not fix

`check_geofence`'s own docstring says the Marine Protected Area list is "a
hand-curated set of named sites, not a surveyed footprint" (EEZ/IMBL geometry
is real; MPAs are not). Fine for a demo as long as it's stated up front if
this is presented as authoritative — not a build item, just something to say
out loud rather than let a judge assume otherwise.

## 12. Tsunami/marine-warning coverage — investigated 2026-08-26, no pollable feed found

The PS's INCOIS section lists "*tsunami/marine warning information where
publicly available*" and there is no tsunami source anywhere in
`backend/services` — confirmed by grep. INCOIS runs a Tsunami Early Warning
Centre; investigated the same way `services/cyclones.py` and
`services/severe_weather.py` were built — probed live 2026-08-26. Full probe
log in DONE.md.

**A real bulletin viewer exists but is not a discoverable feed.**
`tsunami.incois.gov.in/TEWS/displaybulletinslightweight.jsp` renders a real
bulletin (200, HTML) — but only given an `eventId` you must already know
(e.g. `incois2026arpe`), with no list/latest/index endpoint found alongside
it to discover that id for an active event. No RSS/CAP XML feed was found at
any guessed path (`TEWS/rss.xml`, `itews/api/events`, both 404) — unlike
IMD's own CAP feed, which is exactly this kind of pollable list.
`searlywarnings.jsp` (the early-warnings listing page) rendered with no
inspectable JS-driven data call underneath it.

**Verdict: infeasible with a keyless request-only probe, the same result
RSMC New Delhi's cyclone bulletins got** — the possible outcome this item
itself named. Same caveat as item 6: this was a static-probe pass, not a
real browser session watching TEWS's own network traffic, so "no feed found"
is not certain to survive a deeper look — but nothing found here is buildable
today.

## 13. Everything above is static review — nothing has been run live yet

No Dockerfile/render/fly/vercel config exists anywhere in the repo, and every
finding in this file came from reading code, not from executing it. Two
separate risks follow: there is currently no way to demo this to anyone
without them running `uvicorn`/`npm run dev` locally, and the cyclone/
severe-weather/geofencing docstrings' live findings are dated 2026-08-24 —
recent, but this codebase's own convention (ERDDAP flapping, INCOIS/IMD hosts
being unreliable, elsewhere in CLAUDE.md) is that external feeds move. Before
building on top of `pfz.py`/`geofencing.py`/`routing.py`, boot the backend and
frontend and actually run a few of the guide's ten "definition of success"
queries against a live instance to confirm the baseline still holds, rather
than assuming the dated docstrings are still accurate.
