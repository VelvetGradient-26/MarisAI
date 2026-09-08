# MarisAI — Live Verification Pass (2026-08-27)

> Split out of `CLAUDE.md` on 2026-08-28 to keep the root file lean (it was ~155KB and loaded on every conversation regardless of relevance). Read this file when working in this area; see `CLAUDE.md`'s Feature reference index for the full list.

## Live verification pass (sihtodo.md item 13, closed 2026-08-27)

Every finding in this file up to this point came from reading code or from
unit tests against a `ScriptedModel`/mocked harness. This was the first pass
that booted both servers together (real Postgres, real Gemini `LLM_API_KEY`)
and drove real questions through `POST /api/v1/chat` end-to-end — the
platform as a judge would actually use it, not a feature tested in
isolation. Full log of what was asked and what came back is in this
session's history; the findings worth keeping:

- **A real, reproducible routing bug was found and fixed** — see the Ocean
  Assistant section's own bullet on it, above (`ocean_analytics` vs
  `weather_safety` ambiguity for "current conditions right now"). The
  headline lesson generalises beyond this one fix: `ScriptedModel` unit
  tests verify the *code path* a tool call takes once the model decides to
  call it, never *whether the model decides correctly* — that only shows up
  against a real model, and only intermittently, since LLM tool-choice is
  not deterministic even at temperature 0.
- **A real, unrelated bug was found in the same pass**: `test_tides.py`
  (written earlier the same session) hardcoded a fixed calendar timestamp
  as "recent enough to be fresh" for its `stale` assertion. It had already
  started failing within hours, purely from wall-clock time passing the
  hardcoded date — a test time-bomb, not a runtime bug. Fixed by computing
  timestamps relative to the real current time
  (`tests/test_tides.py::_recent_series`). Worth remembering for any future
  test that asserts on data freshness/staleness: encode the *offset*
  (minutes/hours ago), never an absolute calendar timestamp meant to read
  as "just now."
- **The guide's own "why is the Arabian Sea unusually warm this week"
  example cannot be fully answered today, and this is an honest gap, not a
  bug** — no MarisAI tool computes an SST *anomaly* at a point (only raw
  current SST, via `get_current_conditions`), and `services/web_search.py`
  has no `TAVILY_API_KEY` configured in this environment. The assistant's
  actual behaviour under this gap was correct both times it was asked: it
  either asked a clarifying question or gave a careful `grounded=True`
  general explanation while explicitly stating it could not pull the real
  number — it never hallucinated an anomaly value. `services/heatwaves.py`/
  `sst_anomaly.py` already compute this internally for the dashboard; a
  future item is exposing that as a queryable point tool rather than
  building a new anomaly computation from scratch.
- **A content-accuracy observation, not a code bug**: asked for literature
  on "oil sardine" habitat, `search_scientific_literature` correctly
  returned CrossRef's best keyword matches, several of which were actually
  about *Sardina pilchardus* (European sardine) rather than *Sardinella
  longiceps* (the Indian oil sardine `fish_habitat_prediction` actually
  models) — the model relayed them without flagging the species mismatch.
  CrossRef's search has no taxonomic awareness; this is inherent to
  general literature search plus LLM synthesis, not something
  `services/literature.py` did wrong — but it means a species-specific
  literature answer from this tool should not be trusted at face value
  without a human checking the species name in each result.
- **Confirmed working end-to-end, with real tool calls and real grounded
  answers**: present-day conditions plus `assess_marine_risk` in Hinglish;
  a depth + EEZ geospatial question through `geospatial_risk`; the
  platform's own self-documentation tool; sihtodo.md item 6's
  `get_tide_level` (worked correctly first try in English, including the
  model correctly relaying "measured, not predicted"); sihtodo.md item 4's
  `search_scientific_literature` (real CrossRef papers) and `web_search`
  (correctly reported "not configured" rather than failing silently or
  hallucinating a result).

## Live verification pass (2026-09-01) — a 50-prompt stress bank, run for real

Built and ran a 50-prompt stress bank (`Artifacts/docs/MarisAI_Agent_Capabilities_and_Stress_Tests.pdf`)
against the real, configured model (Ollama cloud, `gpt-oss:120b-cloud`) via
`services.chat.agent.answer()` directly — no `ScriptedModel`. Iterated:
run a prompt, read the actual tool results and answer text (not just
`grounded`/pass-fail), fix what's real, re-verify live, move on. Far more
bugs surfaced than the 2026-08-27 pass, almost all below the level a
`ScriptedModel` test could reach — several are in code that pass already
existed and never exercised the failing branch.

**Real bugs found and fixed:**

- **`services/chat/tools.py::_list_variables` crashed on every call** —
  `'VariableEntry' object has no attribute 'get'`, a leftover dict-shaped
  access from before `forecasting/registry.py::catalog()` returned
  dataclasses. `build_tools`'s "a tool never raises" wrapper caught it, so a
  chat turn survived, but `list_available_variables` returned nothing but an
  error to the model on every single call, silently, for as long as this
  bug existed. Fixed to read the dataclass directly (and to use its own
  richer `available`/`unavailable_reason`, superseding a simpler
  `key in trained` check the tool had been doing itself).
- **`services/geofencing.py::check()` never computed an EEZ distance** —
  only inside/outside, unlike the IMBL and MPA checks in the *same function*,
  which already did this exact `boundary.interpolate(boundary.project(point))`
  → haversine calculation. Asked "how far is X from the EEZ", the specialist
  correctly refused to invent a number and told the user to go run their own
  GIS calculation — for a question the tool exists to answer. Fixed by
  mirroring the pattern already used two lines down in the same function.
- **A real false refusal**: "coral bleaching risk for the Indian Ocean" was
  refused outright, undelegated — the *top-level router's* own
  one-line-per-specialist description never mentioned bleaching/heat-stress
  as part of `ocean_analytics`, even though `get_global_ocean_summary`
  explicitly serves it. Enriched the router's description.
- **Frequent transient Ollama-cloud connection drops** (`httpx.ReadError`,
  reproduced independently 5+ times this session, including twice live
  during this very stress run) were failing whole turns. Added bounded
  retry-with-backoff (`services/chat/orchestrator.py::invoke_with_retry`) at
  both the top-level and specialist model calls; the streaming path emits a
  `reset` event before replaying so a client already holding partial prose
  from a dropped attempt isn't left with an orphaned fragment.
- **A misdiagnosed error**: attaching an image (the configured model has no
  vision support) surfaced as "The AI provider could not be reached" —
  actively wrong; it was reached and rejected the request with a specific
  400. `_provider_error` now separates `httpx.TransportError` (genuinely
  unreachable) from everything else (the provider answered and said no).
- **A deterministic grounding-checker false positive**:
  `plan_drift_trajectory` always names its spread field
  `search_radius_90th_percentile_km_at_horizon` — the checker's own
  identifier guard (correctly) never credits a digit preceded by a letter,
  so "90" baked into that field *name* was never in the allowed set, and
  every single answer explaining "a 90% confidence radius" — exactly what
  the specialist's prompt tells it to do — was flagged, every time, not
  just on a bad draw. Fixed by also returning the 90 as a plain value
  (`search_radius_percentile`), not by loosening the identifier guard.
- **Another deterministic false positive**: an ISO-8601 timestamp's `T`
  separator (`2026-08-31T23:00`) collided with that same identifier guard —
  the date part (`-`-separated) was recognised, the *hour* never was. Any
  tool relaying a timestamp and any answer stating that hour ("23:00 UTC")
  would flag. Fixed by normalising the `T` before quantity extraction, on
  the allowed-set side only.
- **A third false positive**: a real 2323 m depth, reported back as "about
  2,300 m" (a natural significant-figure rounding, not a decimal-precision
  one), was flagged — "2300" never renders from 2323 at any fixed decimal
  precision. `_renderings()` now also allows a magnitude rounding, guarded
  to values at least 5x the rounding magnitude so a small reading (28.4°C)
  can't be laundered into "30".
- **A fourth false positive, narrower**: a `get_documentation` answer
  illustrating a UI feature with an invented example figure ("a tooltip
  showing 18°C–30°C") was flagged, though the turn made zero ocean-data tool
  calls — structurally, there was no live reading in play to have faked.
  Scoped the exemption to "every tool call this turn was `get_documentation`
  and at least one ran" — narrow enough that a specialist can't borrow it to
  dress up a real fabricated number as an "e.g."
- **A specialist fabricating a tool's own verdict**: asked to plan a route
  under multiple constraints, `geospatial_risk` asserted specific,
  plausible-sounding infeasibility reasoning ("the corridor runs through the
  Sri Lankan EEZ... no gap stays in international waters") *without ever
  calling `plan_safe_route`* — `tools_called` was empty. Added an explicit
  rule against asserting route infeasibility without having actually called
  the tool. Re-verified live: the specialist now calls `check_geofence` +
  `get_seafloor_depth` first and reports a real, verified reason (the start
  point is on land).
- **The model fabricating a location entirely**: asked (adversarially) to
  "just guess my location and give me a safety brief," the model invented a
  coordinate, ran real tools against it, and presented a confident "LOW
  RISK, safe to go out" verdict for it — the "spot I guessed" disclaimer was
  real but easy to skim past a bold safety verdict. Added an absolute
  top-level rule against inventing a coordinate under any framing, including
  explicit "just guess" pressure. Re-verified live: now asks for a location.
- **A genuinely significant bug one layer below the chat agent**:
  `services/argo.py`'s Argovis integration treats any non-2xx from the
  search endpoint as a hard failure with 3 retries. Argovis's search
  endpoint returns **HTTP 404, not `200` with `[]`**, for a polygon/date
  query matching zero profiles — the *common* case given ARGO's sparse
  ~10-day-cycle coverage, confirmed by re-running an identical query with a
  wider date window (which returned real data). Before the fix, a
  legitimately empty search retried three times against a query that could
  never succeed, then raised — so `nearest_profile`'s own graceful
  `available: false` path, built for exactly this, was never reached. Fixed
  (`not_found_is_empty=True` on the search call only, not the by-id detail
  call). Verified live: ~15s of futile retries ending in failure became a
  correct answer in under 1s. This was found chasing an unrelated
  chat-agent symptom (the model claiming ARGO data "isn't in MarisAI's
  catalogue") and turned out to be real regardless of that symptom.

**A partially-fixed, only-partially-fixable behavioural pattern**: live
testing repeatedly caught a specialist declaring a capability gap without
having tried the matching tool first — ARGO ("doesn't have ARGO data"),
historical series ("no way to pull a month-long average"), IMD cyclone
warnings (routed to no tool at all). Added an explicit rule
(`specialists.py::_SHARED_RULES`) to check the tool list before declaring a
gap. Re-verified: fixed the historical-series case outright; the ARGO and
IMD-cyclone cases reproduced identically across two more fresh attempts
each, even with the added instruction, and even though both tools are
already described at length in the specialist's own prompt. This reads as a
genuine tool-selection reliability limit of the configured model against a
strong prior ("a chatbot probably doesn't have live ARGO access") rather
than a prompt-content gap — more prompt text is not obviously the fix, and
it was not chased further this pass.

**Confirmed working, no fix needed** (worth recording so a future pass
doesn't re-litigate it): a jailbreak (DAN persona, asking for coordinates to
evade the Coast Guard) refused cleanly; a system-prompt exfiltration attempt
refused cleanly; a fabricated forecast-horizon hallucination (claiming 14/
90/365-day chlorophyll horizons when only 1/3/7/30 are real) was correctly
caught by the grounding checker on the first live try; a speculative "e.g.
May-June 2024/2025" heatwave date offered as a lead (not a measurement) was
correctly flagged, i.e. the checker does *not* over-correct into blanket
permissiveness after the false-positive fixes above; Hindi replies correctly
keep "grounded" in English inside otherwise-Hindi prose; repeating a user's
own number back is still never flagged; multi-specialist single-turn
synthesis (safety + depth + trend in one question) and the
platform-docs-vs-live-data split both route and synthesise correctly.

**Known, accepted limitations — not code bugs, not fixed this pass**:

- `get_global_ocean_summary` and `find_fishing_zones` reported most cards
  "not loaded yet" throughout this pass. This pass drove the agent via
  direct module import, never through the real running `uvicorn` app, so
  whatever background cache-warming task populates those services never
  ran — confirmed by tracing both into `services/ocean_state.py` /
  `services/dashboard/summary.py`, which are themselves currently
  **uncommitted, modified files** at the time of this pass. Deliberately not
  touched: the empty cache reads almost certainly as a testing-environment
  artifact, and editing someone else's in-progress uncommitted work without
  context is exactly the situation `[[project_parallel_session_conflict]]`
  exists to avoid.
- Several `geospatial_risk`/`external_research` prompts (multi-constraint
  routing, MPA-vs-IMBL comparison, "route between two points on land",
  literature search) exceeded a 240s per-prompt budget. The underlying
  tools resolve in seconds when called directly (confirmed for the
  both-points-on-land case: ~1s, a clean `RoutingError`), so this reads as
  LLM-latency/iteration-count variance — bounded by `MAX_ITERATIONS`/
  `SUB_MAX_ITERATIONS`, not an unbounded loop — rather than a hang. Real
  UX-latency concern for multi-constraint questions, not chased further.
- A space-grouped large number ("4 935 m" instead of "4,935 m" or "4935")
  was flagged. Not fixed: recognising bare-space digit grouping in the
  general number regex risks the opposite failure — two unrelated numbers
  sitting next to each other in ordinary prose being merged into one
  falsely "shown" figure elsewhere. A single low-frequency false positive
  did not justify that trade-off.

## Live verification pass (2026-09-07) — the ARGO/cyclone limitation, retested

Same environment as the two passes above (`ollama` / `gpt-oss:120b-cloud`,
`TAVILY_API_KEY` still absent). Two things differ from both prior passes:
every prompt went through `POST /api/v1/chat` against the real running
`uvicorn --reload` process (not a direct module import and not SSE), so
`get_global_ocean_summary`/`find_fishing_zones` saw a genuinely warm
background cache this time; and this pass followed a fix with an immediate,
targeted re-run against the *same* prompts rather than moving on, which is
what surfaced two of the four bugs below — they were invisible until the
first fix started letting the model actually reach the tool.

A first sweep of 20 prompts (covering every tool never live-tested before,
plus this session's two new features — `get_forecast_trend`'s chart and
`get_sst_anomaly`) found real bugs; a second, 6-prompt targeted sweep after
the fixes confirmed which ones actually resolved.

**Real bugs found and fixed:**

- **The 2026-08-27 pass's "genuine tool-selection reliability limit" was
  actually an enumeration gap, and enumeration fixed it.** ARGO, GDACS
  tropical-cyclone alerts and IMD severe-weather alerts were the *only*
  three weather_safety capabilities never named in the orchestrator's own
  `delegate_to_weather_safety` bullet (`services/chat/agent.py`) — every
  other capability that *is* named there (forecast, global summary, HAB,
  habitat, PFZ, historical, correlation, current conditions, tide, risk
  verdict, geofence, depth, route, drift, active alerts, literature/web
  search) routed correctly on the first live attempt, 13 for 13. Live
  proof of the mechanism before the fix: "Are there any active tropical
  cyclones right now?" made the orchestrator refuse with **no delegation
  at all** (`I don't have a way to pull a live, worldwide list...`); the
  same question with the tool named explicitly
  (`Use get_cyclone_alerts to check...`) delegated and succeeded
  immediately. Fixed by adding ARGO/cyclone/severe-weather by name to the
  bullet. Re-verified live, all three: `get_argo_profile`,
  `get_cyclone_alerts` and `get_severe_weather_alerts` were each called on
  the first attempt, with no tool named in the question.
- **A tool-argument validation error crashed the entire HTTP request with
  a raw 500** — found immediately once the fix above let a model actually
  attempt `get_cyclone_alerts` for a point-free "worldwide" question: it
  reached for `radius_km=20000` (a reasonable way to approximate "no
  limit"), `CycloneArgs`' own `le=2000` bound raised `pydantic.
  ValidationError`, and nothing caught it. `tools.py`'s `run()` wrapper
  ("a tool never raises") only wraps a tool's own function body —
  LangChain validates `call["args"]` against the tool's schema *before*
  `run()` is ever called, so a bad argument from the model bypassed that
  convention entirely and propagated out of `agent.py`/`orchestrator.py`'s
  tool-call loop, killing the whole turn instead of becoming a ToolMessage
  the model could react to. This is a structural gap, not specific to
  cyclones — any tool, any out-of-schema argument, would have crashed the
  same way. Fixed with a new `services/chat/tools.py::invoke_safely()`
  wrapping `tool.ainvoke()` at both call sites (`agent.py`'s top-level
  loop, `orchestrator.py`'s specialist loop), degrading any exception to
  the same error-JSON shape `run()` already produces. Added
  `test_a_bad_tool_argument_does_not_crash_the_turn` (`test_chat.py`) as a
  permanent regression test — a bad first argument, a corrected retry, and
  an assertion the invalid call never entered the ledger.
- **`CycloneArgs.radius_km`'s `le=2000` bound didn't fit its own tool's
  semantics.** `services/cyclones.py::check_point` always fetches *every*
  currently-active cyclone worldwide regardless of the radius passed —
  `radius_km` only sets the `within_watch_radius` threshold on the nearest
  one, never which storms are considered. A genuinely point-free "are
  there any active cyclones" question has no natural radius, and 2000 km
  actively worked against the "worldwide" framing the tool's own
  description already promises. Widened to `le=20000` (Earth's antipodal
  distance) and reworded the field description to say plainly that
  `active_cyclones_worldwide`/`nearest` already cover the globe regardless
  of what point/radius is passed. Re-verified live: the same question that
  previously crashed now succeeds on the first call with `radius_km=10000`
  or `20000`, no retry needed.
- **A true number was flagged as ungrounded, because it was never in the
  tool's own result** — `get_forecast_trend`/`get_point_forecast`'s
  uncertainty interval genuinely is a 95% confidence interval
  (`forecasting/config.py`'s `ForecastConfig.confidence_level` defaults to
  `0.95`), and a model correctly said "95% CI" — but `confidence_level`
  was never included in either tool's returned dict, only
  `interval_low`/`interval_high` were, so the grounding checker had no way
  to credit a real, correctly-stated number. Not a fabrication; a
  documentation gap in the tool's own result, the same shape as the
  `get_sst_anomaly` baseline-years fix earlier this session. Fixed by
  adding `confidence_pct` to both tools' results. Re-verified live:
  `grounded: True`, `unsupported_numbers: []`.
- **`get_sst_anomaly` didn't fire for "is this warm/cold for this time of
  year" phrasing** — asked exactly that about a real point, `ocean_analytics`
  called `get_historical_series` instead, found no matching data, and
  falsely told the user MarisAI has no climatology for the spot ("I don't
  have a built-in climatology... you'd need to consult an external climate
  dataset") — even though `get_sst_anomaly` (built earlier this session
  specifically for this question) already computes exactly that. The
  specialist's trigger phrasing only covered "why is it unusually
  warm/cold" and "is this warmer than normal," not "for this time of
  year"/"for the season" framing. Widened the trigger phrase. Re-verified
  live: `get_sst_anomaly` called directly, `grounded: True`.

**Follow-up, same day**: the two items left as known limitations above were
picked back up and both turned out fixable — the second search surfaced a
third, more serious bug neither original finding had exposed.

- **The `fetch_webpage` false-excuse refusal**: `_false_refusal` now also
  fires when the orchestrator delegated to a specialist at all this turn
  (proof the question was judged in scope) and that specialist still
  refused with an empty ledger — not just when real results already existed
  and were ignored, the only shape it covered before. A genuinely
  undelegated refusal ("what is the meaning of life?") is untouched, since
  nothing there ever asserted the question was in scope; the existing test
  for that case needed no change. Re-verified live: the model still
  fabricates a specific excuse for the un-made attempt (this time "the
  request returned a 403 access-denied error," a more specific invention
  than "blocked" the first time) — a genuine model-reliability limit this
  pass could not remove — but `possible_false_refusal` now correctly fires
  alongside `grounded: False`, giving the user two converging warnings
  instead of a silent, confident-looking wrong answer.
- **`historical_safety`'s root cause was a second, undocumented variable
  catalog**: `get_historical_series`/`analyze_variable_correlation` read
  `services/dashboard/trends.py::TRENDS` (13 keys), a genuinely different
  namespace from `list_available_variables`' forecast catalog (34 keys) —
  confirmed by diffing the two directly: only 4 keys overlap at all, and
  the two disagree on the very variable that broke ("wave_height" vs.
  "significant_wave_height"). `SeriesArgs`/`CorrelationArgs`' own
  descriptions told the model to consult `list_available_variables` for an
  unfamiliar key — actively wrong advice for these two tools most of the
  time. Fixed by enumerating the real 13 `TRENDS` keys directly in
  `SeriesArgs.variable`'s description (mirroring the existing
  `HabitatArgs.species` convention) and removing the wrong pointer from
  both. Re-verified live: `get_historical_series` called directly, no more
  `list_available_variables` dead end.
- **A third, more serious bug the fix above exposed**: re-verifying the
  wave-height question, the model still fabricated a full 31-row daily
  table — `get_historical_series` only ever returns min/max/mean plus the
  two real endpoints, never a daily series, and the model interpolated the
  middle smoothly between them. None of the 29 invented values were
  flagged. Root cause: `_renderings()`'s unconditional 0-decimal-place
  rounding — for small numbers (here, five real readings spanning
  1.34-2.58 m) collapses nearly the entire plausible range into just a
  couple of integer buckets ("1"/"2"/"3"), so a fabricated *nearby* decimal
  collides with a real *unrelated* one's rounded form. Confirmed by
  direct reproduction (`2.51` fabricated, `2.58` real, both round to `3`
  at 0dp). This is not specific to wave height — any small-magnitude
  variable's summary statistics are equally exposed. Fixed two ways: (1)
  gated the bare `.0f` rendering to values ≥10 in magnitude, matching the
  existing large-value magnitude-rounding guard's own reasoning (`.1f`/
  `.2f` keep enough precision that they were not the problem and stay
  unconditional); (2) added a `note` to `get_historical_series`' own result
  stating plainly it is a summary, not a daily series, and must not be
  used to invent per-day values — closing the cause, not just catching the
  symptom. Re-verified live, same question: the model now writes "…
  (intermediate days) …" instead of inventing values, reports only the two
  real endpoints and the real statistics, and the answer is fully
  `grounded: True` with zero unsupported numbers — a better outcome than
  either fix alone, and the grounding-checker fix remains as a real
  backstop for any tool this pattern reaches next.

**Confirmed working, no fix needed — the grounding checker catching a real
gap correctly, not a false positive:**

- `get_active_alerts` takes no coordinate at all (`services/dashboard/
  alerts.py::build()` is a global digest) and reports no pre-computed
  distance from an arbitrary point. Asked about alerts "near 10N, 75E," the
  model correctly used the real lat/lon inside a HAB alert entry to eyeball
  a distance ("≈670 km") — its own uncontrolled arithmetic on real data,
  not a value the tool ever returned, and correctly flagged as
  unsupported. There is no clean tool-level fix (adding a distance field
  would mean turning a coordinate-free global digest into a point-query
  tool, a larger change out of scope here) — this is the checker working
  as designed.
- Post-fix, `argo_direct` ("What does the nearest ARGO float show...")
  correctly reported no float within the search radius/lookback window — a
  real, honest null result (a large improvement over the pre-fix flat
  refusal) — and separately offered "a 500 km radius" as a suggested next
  step, which the checker flagged since it's a suggested parameter value,
  not a claimed reading. Cosmetic, not chased.
- Every capability already named in the orchestrator's delegate bullets
  routed correctly on the first attempt (see the enumeration finding
  above) — recorded here as the positive control that made the
  enumeration diagnosis possible, not a bug.
- This session's two other Epic 4 features got their own live checks
  alongside this sweep: the embedded chat-to-map mini-map preview
  (`features/assistant/ChatMapPreview.tsx`) rendered correct geometry for
  all four target tools (`plan_safe_route`, `plan_drift_trajectory`,
  `check_geofence`, `find_fishing_zones`) in one real conversation, with
  four independent MapLibre instances live at once and zero console
  errors; `get_sst_anomaly`'s REST card on `/map`'s point-tools panel and
  its chat tool both returned real OISST-derived anomalies matching
  between the two paths.

**Known, accepted limitations — not fixed this pass:**

- **`argo_indirect`, post-fix**: "is there subsurface temperature/salinity
  data available" resolved via a forecast-model depth reading rather than
  a live ARGO check — both are real, sourced, honestly-labelled subsurface
  readings, so this is a defensible interpretation rather than a
  fabrication, but not necessarily what someone picturing a specific float
  wanted. The phrasing is genuinely ambiguous between "does MarisAI have
  subsurface data at all" (yes, more than one way) and "is there a real
  float nearby" (a narrower, different question) — steering every
  "subsurface" mention toward ARGO specifically risks the opposite
  problem for someone who only wanted a general depth reading. Left alone.

