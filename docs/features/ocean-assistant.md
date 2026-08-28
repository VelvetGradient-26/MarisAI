# MarisAI — Ocean Assistant (chat)

> Split out of `CLAUDE.md` on 2026-08-28 to keep the root file lean (it was ~155KB and loaded on every conversation regardless of relevance). Read this file when working in this area; see `CLAUDE.md`'s Feature reference index for the full list.

- Ocean Assistant (`services/chat/`, `routers/chat.py`,
  `features/assistant/`) at `/assistant`. A bounded tool-calling loop over the
  platform's own services, served two ways.
  - **Two endpoints, and the JSON one is not legacy.** `POST /api/v1/chat`
    returns the whole turn at once; `POST /api/v1/chat/stream` is SSE. They
    share the loop, the `Ledger` and the grounding check — `answer_stream()`
    sits beside `answer()` in `agent.py` rather than replacing it, and the
    non-streaming path stays the fallback.
  - **`grounded` cannot be streamed, and this constrains the UI.** It is
    computed by checking the *finished* text against everything the tools
    returned, so it is only knowable after the last token and rides the
    terminal `meta` event. The UI must render streaming text as *unverified*
    and resolve on `meta`; a "traced" badge shown earlier asserts a check that
    has not run. `tests/test_chat.py` pins the ordering (`tool` before any
    `delta`, `meta` last, deltas reassembling exactly into `meta.answer`).
  - **`reset` exists because a turn's kind is not knowable in advance.**
    Whether a model turn is the final answer or another round of tool calls is
    only known once its stream ends, so text is emitted optimistically; on the
    rare turn that emits prose *then* calls a tool, `reset` tells the client to
    drop it. Buffering instead would defeat the point of streaming.
  - **The grounding number regex handles thousands separators.** Without the
    grouped branch, "2,048 m" split into "2" and "048", neither of which
    appears in any tool result — so a correct answer was flagged as carrying
    two untraceable figures, on any depth over a thousand metres. That is the
    cry-wolf failure `_ungrounded_numbers` documents at length; a banner that
    fires on correct answers trains people to ignore the one that matters.
    A model's own unit conversion ("roughly 6,700 ft") is still flagged, and
    that is correct — no tool reported it.
  - **assistant-ui owns the thread; MarisAI owns everything under the answer.**
    The library supplies message list, run status, cancellation, composer and
    viewport. The grounding banner, tool-observation disclosure, sources and
    the session sidebar are ported, not reimplemented — including the
    sidebar's three-way `sessionsStatus` (`loading`/`ready`/`error`), which
    exists because "we don't know yet" and "we couldn't load them" are
    different answers from "you have none", the same rule as the dashboard's
    `unavailable_reason`.
  - `pages/ChatPage.legacy.tsx` is the previous hand-rolled non-streaming page,
    kept as a reference until the streaming one has run in anger. It still
    works against the unchanged JSON endpoint.
  - **Two loop levels: a top-level orchestrator delegates to three named
    specialists, each its own smaller bounded loop.** `agent.py`'s
    `MAX_ITERATIONS = 6` bounds the top level; each specialist gets its own
    `orchestrator.SUB_MAX_ITERATIONS = 5` (measured too tight at 4 for
    `geospatial_risk` specifically — a route-plus-depth question exhausted the
    cap mid-tool-call with nothing left to synthesize an answer). A specialist
    is a name/description/system-prompt/tool-allowlist record
    (`services/chat/specialists.py::Specialist`), drawn from the same
    `services/chat/tools.py` implementations the pre-multi-agent single loop
    used, just partitioned. `orchestrator.build_delegate_tools` wraps each as
    a `delegate_to_<name>` tool for the top level; `run_specialist` is the
    inner loop. `Ledger.record` tags every observation with which specialist
    made it, so the grounding check reads correctly regardless of which loop
    produced a number — the multi-agent split does not weaken grounding.
  - **The three specialists are `ocean_analytics`, `weather_safety`,
    `geospatial_risk` — split by domain, not by function, and that was a
    deliberate decision (sihtodo.md item 2, closed 2026-08-26) against the
    guide's suggested planning/risk-assessment/visualization/reporting
    framing.** None of the four functional labels maps cleanly onto one
    specialist, and renaming to fit them would have been cosmetic rather than
    accurate:
    - *Planning* is split, not owned: `plan_safe_route` lives in
      `geospatial_risk`, `find_fishing_zones` lives in `ocean_analytics`.
    - *Risk assessment* is likewise split, and more usefully so: weather risk
      (`weather_safety` — alerts, cyclones, "is it safe to go out") and
      geospatial risk (`geospatial_risk` — boundary/MPA proximity) are
      different tool sets and different failure modes. Collapsing them into
      one "risk" specialist would lose that.
    - *Visualization* maps onto nothing that exists — confirmed by
      sihtodo.md item 1's own finding that the chat response schema carries
      no `map_layers`/`markers`/`polygons` field at all. A specialist named
      "visualization" would draw nothing; that gap is real and belongs to
      item 1's still-open half (a structured-geometry field on the chat
      response, or the REST endpoints from item 1 driving map layers
      independently of chat), not to a rename here.
    - *Reporting* also maps onto nothing wired into chat. The platform's only
      reporting capability is the point brief / comparison feature
      (`services/brief.py`, `services/brief_pdf.py`, `/compare`) described
      below, and it is a separate REST feature with no chat tool calling it —
      renaming a specialist "reporting" would not make it generate a report.
    The three names stay as-is; this analysis is the documentation this item
    asked for, so the next session does not re-litigate it.
  - **Delegation reasoning is traced for PS2's "demonstrable autonomous
    planning" ask, without a separate reasoning call.** `agent.py`'s
    `_record_delegation` reads the `question` argument each `delegate_to_*`
    call already carries — the orchestrator's own restatement of the
    sub-task, in its own words, before the specialist ever runs — and records
    it alongside which specialist was chosen. That is the cheap, honest
    version of "why did it delegate here": no extra model call, just
    surfacing an argument the model already produces.
  - **"What is the SST/tide right now at this point" reliably misrouted to
    `ocean_analytics` instead of `weather_safety`, found and fixed during
    sihtodo.md item 13's live verification pass (2026-08-27).** `ocean_analytics`
    has no tool for a point-in-time current reading — its "global ocean
    state" tool (`get_global_ocean_summary`) is one worldwide summary number,
    no coordinate — but the top-level prompt's own specialist descriptions
    were genuinely ambiguous between that and `weather_safety`'s
    `get_current_conditions`/`get_tide_level`, and a real Gemini call (not
    the `ScriptedModel` test harness) reliably chose wrong: 0/2 for an
    English "current SST" phrasing, 0/2 for a Devanagari "tide right now"
    phrasing. `_SYSTEM_PROMPT` now states the boundary explicitly ("a
    'what is the SST/wind/wave/tide right now at this point' question is
    always weather_safety, never ocean_analytics"). Re-measured after the
    fix: 4/4 and 3/4 respectively — the residual miss is ordinary LLM
    non-determinism at temperature 0, not a further code defect, and is
    recorded as such rather than claimed fully solved. This is the kind of
    bug the `ScriptedModel` unit-test harness structurally cannot catch,
    since it scripts the model's tool choice rather than letting a real
    model make one — a reminder that "tests pass" and "the real model
    routes correctly" are different claims, and only a live pass checks
    the second one.
  - **Regional Indian-language support was already prompt-level before
    sihtodo.md item 3 was written, and its "confirmed absent" claim was
    stale** (closed 2026-08-26) — `_SYSTEM_PROMPT`'s "How to be good
    company" list already instructed the model to detect the question's
    language and answer in kind, naming ten Indian languages by name; the
    grep that produced item 3 evidently searched for "language"/"Hindi" as
    identifiers and missed prose inside the prompt string. What genuinely was
    missing, and is what item 3 actually added, is the glossary half: a fixed
    set of terms — SST, chlorophyll, wave height, wind speed, cyclone, PFZ,
    marine advisory, exactly the seven the item names — that must stay in
    English even inside a non-English answer, because a translated or
    transliterated version is ambiguous or misleading to someone who needs to
    act on it.
    - **The glossary is enforced twice, the same relationship
      `_ungrounded_numbers` has to its own prompt rule.** The primary defence
      is the added `_SYSTEM_PROMPT` bullet instructing the model to keep the
      seven terms in English; `_untranslated_glossary_terms()` is the
      secondary, informational backstop — same file, same shape as
      `_false_refusal`, and it **never blocks or rewrites the answer**, only
      annotates it via a new `glossary_gaps` field on both `answer()` and
      `answer_stream()`'s reply dicts (and a fourth banner tier in
      `AssistantThread.tsx`'s `Provenance()`, between the false-refusal and
      traced-success tiers, reusing the existing `chat-flag` class — no new
      CSS). A checker that cries wolf on a correct answer teaches people to
      ignore the one that matters, so this inherits `_ungrounded_numbers`'s
      own stated discipline rather than inventing a stricter one.
    - **The check is script-gated, not language-gated, and cannot fire on an
      English answer.** `_INDIC_SCRIPT` matches the Unicode blocks for
      Devanagari, Bengali, Gurmukhi, Gujarati, Oriya, Tamil, Telugu, Kannada
      and Malayalam; the per-term loop never runs unless the answer contains
      at least one such character. Latin-script code-mixed Hindi
      ("Hinglish") is therefore not caught — a known, stated limitation, not
      a solved one; catching it needs real language-ID, out of scope for a
      glossary guardrail.
    - **Each glossary term's alias tuple is used on both sides of the
      check**, which is what keeps it from crying wolf on a faithful
      translation: found in `ledger.as_text()` an alias means "this turn's
      tool data touched the concept" (drawn from actually reading the tool
      result shapes — `sea_surface_temperature`/`wave_height`/`wind_speed`
      keys, `chlorophyll_mg_m3`/`sst_c` and `pfz.py`'s prose `reasons`,
      `cyclones.py`'s `active_cyclones_worldwide`); found in the answer, the
      same alias means "kept in English" — so "sea surface temperature"
      satisfies the SST term exactly as the bare abbreviation would. PFZ and
      "marine advisory" are coarser proxies than the other five — keyed off
      the `find_fishing_zones` tool name and the alert tools' own vocabulary
      respectively, since neither literal phrase reliably appears in a tool
      result. One consequence worth knowing before reading a live turn: a
      cyclone-alert turn touches *both* the "cyclone" and "marine advisory"
      terms, because the tool is literally named `get_cyclone_alerts` and its
      own name satisfies "marine advisory"'s `alert` alias — both concepts
      are genuinely present, so seeing both flagged together is correct, not
      a duplicate.
    - **Verified only against the `ScriptedModel` unit-test harness
      `test_chat.py` already uses for grounding/false-refusal, not a live
      Gemini call.** No real multilingual smoke test has been run against the
      configured `LLM_PROVIDER=gemini` provider — worth doing when a human is
      available to judge real Hindi/Tamil/etc. output, the same caveat this
      codebase states everywhere else about a docstring finding dating
      quickly.
    - **Deliberately does not attempt full frontend i18n.** The UI chrome
      (`AssistantThread.tsx`'s tool-observation disclosure panel, sidebar
      strings) stays hardcoded English — item 3 is about the assistant's own
      conversational language, not localizing MarisAI's UI, and that is a
      separately-scoped effort this work did not take on.
  - **`get_documentation` is a top-level tool, not a fourth specialist.**
    Self-knowledge about the platform ("how do I read the map colours",
    "what does grounded mean") is static, not a live measurement — the same
    reasoning `agent.py` already used to keep the dataset catalog out of a
    tenth specialist tool — so it is bound directly on the top-level model
    alongside the three `delegate_to_*` tools rather than routed through
    `orchestrator.run_specialist`. `services/docs.py` word-overlap-searches
    `data/docs_index.json`, a plain-text export of every chapter under
    `frontend/src/pages/docs/chapters/` produced by
    `frontend/scripts/export-docs-index.ts` (`npm run export-docs`) — the
    backend has no JS runtime to render TSX, and the chapters are already the
    single source of truth for the in-app docs search
    (`chapters/searchIndex.tsx`), so this reuses that content rather than a
    hand-maintained second copy that would drift. The exporter renders with
    `react-dom/server`, not a hand-rolled tree walk, because several chapters
    use `<Link>`, which calls a hook (`useAppRouter()`) that needs a real
    render pass to resolve. Regenerate the export after editing a chapter —
    nothing does it automatically, and a stale export degrades to "no
    chapters matched" rather than failing chat startup.

- Controlled internet tools — a fourth specialist, `external_research`
  (`services/chat/specialists.py`), for sihtodo.md item 4: web search, one-URL
  fetch, and scientific-literature search, wired the same way items 7/10 were
  (a chat tool plus a matching REST endpoint on `routers/tools.py`, never a
  chat-only addition) — closed 2026-08-27.
  - **No genuinely keyless full web search API exists, and that was checked
    before picking a provider** — `services/web_search.py`'s own docstring
    records why DuckDuckGo's only unauthenticated endpoint (Instant Answer)
    returns one abstract, not a ranked result list, and its HTML results page
    is a scrape target, the same "HTML only, not a machine-readable feed"
    disqualifier this file's Indian-sources survey already applies to
    INCOIS/MOSDAC. `web_search` uses **Tavily** (`TAVILY_API_KEY`, empty
    default) instead, chosen because it hands back clean `{title, url,
    content}` records with no HTML to strip — the same "structured data over
    a page to parse" preference already reflected in CrossRef, GDACS and
    IMD's CAP feed elsewhere in this file. Follows `services/gfw.py`'s own
    precedent for a missing credential: raises rather than degrading to an
    empty result set, because a search that always returns nothing is
    indistinguishable from a broken feature.
  - **Not verified against a live Tavily response** — no key is provisioned
    in this environment. Verified instead: the request/response shape against
    Tavily's documented contract, and every code path via
    `tests/test_web_search.py`'s mocked-transport harness. Same caveat this
    file already states for the glossary guardrail's untested-against-live-
    Gemini gap — confirm with a real key before relying on this live.
  - **`search_scientific_literature` (`services/literature.py`) uses
    CrossRef, and this one *is* verified live** (2026-08-27): a real
    `type:journal-article` query against `api.crossref.org` returned genuine
    records (DOI 10.1029/2018gl081631, Geophysical Research Letters, 2019).
    Genuinely keyless — `CROSSREF_MAILTO` only opts into the documented
    "polite pool" rate limit, it is not a credential and its absence never
    blocks a request. The same class of source this file's fisheries-data
    survey already vetted as a real, structured, drop-in API (its Tier 1
    table), applied here to literature instead of occurrences.
  - **`fetch_webpage` (`services/webpage.py`) is the one tool here whose
    input is a caller-supplied URL, which makes it an SSRF vector** — a model
    asked to fetch a cloud metadata address would otherwise have this server
    make that request as a trusted insider. `_guard()` resolves the hostname
    itself and rejects any address that is not global-unicast (loopback,
    link-local — which is where every cloud metadata endpoint lives —,
    private, multicast/reserved), and redirects are followed one hop at a
    time with the same guard re-run on every hop, because a public URL that
    redirects to an internal address after passing the first check is exactly
    the attack this exists to stop. Verified live 2026-08-27 both ways: a
    real fetch of `incois.gov.in` (which, discovered in the process, serves a
    bare `<meta http-equiv="refresh">` redirect with no HTTP-level redirect at
    all — now followed explicitly, since an unhandled one silently "succeeds"
    with an empty page) and a rejected loopback fetch. No HTML-parsing
    dependency was added; extraction is a small `html.parser.HTMLParser`
    subclass, the same "stdlib over a new package" choice
    `services/severe_weather.py` already made for CAP XML.
  - **`external_research`'s tool results are other people's claims, not
    MarisAI measurements, and every prompt layer says so** — its own system
    prompt, the top-level orchestrator's system prompt (a new absolute rule,
    `agent.py`'s rule 6), and its tool descriptions all require naming the
    source rather than stating a web/literature result as something MarisAI
    observed. This is the same grounding discipline every other tool already
    gets (a number must trace to a tool result) plus one addition specific to
    this specialist: *whose* claim it is must also survive into the answer.
  - **A "why is \[place\] unusually warm" question needs two delegates in
    sequence, and the top-level prompt says so explicitly** — `external_research`
    has no ocean data of its own, so asked to explain an anomaly it was never
    told about, it can only guess. The prompt instructs measuring first
    (`ocean_analytics`/`weather_safety`) and researching the explanation
    second, feeding the measurement into the research question.
  - Pushes the tool count in `test_chat.py::test_every_tool_declares_a_
    description_and_schema` from 17 to 20.

