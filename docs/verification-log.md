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

