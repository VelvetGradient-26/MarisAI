"""The conversational agent: a bounded orchestrator loop over three specialists.

**Two loop levels, both explicit rather than a prebuilt agent executor.** The
top-level loop here calls *delegate* tools (`services/chat/orchestrator.py`),
one per specialist (`services/chat/specialists.py`); each delegate call runs
its own small bounded loop over that specialist's own tools
(`services/chat/tools.py`). Same reasons as the original single-loop design,
now applied twice: the iteration count has to be a hard bound at both levels
— this runs inside the API process, and an agent that can decide to keep
calling tools (or keep delegating) is an availability risk, not just a cost
one — and the grounding check below needs every tool result and the final
text together, which a framework that hands back only the answer makes
awkward. `langchain-core`'s tool binding gives the useful half — schema
generation, provider-neutral tool-call parsing — without either loop being
opaque.

**Why specialists rather than one flat tool list.** Three domains — ocean
analytics, weather/safety, geospatial risk — have their own system prompts
and their own tool subsets, so a query that spans two of them ("is it safe to
fish near Kochi today, and where's the nearest good zone") visibly delegates
to two named specialists rather than picking from one undifferentiated list
of a dozen tools. `services/chat/tools.py::Ledger.record` tags every
observation with which specialist made it, so the grounding check below still
sees every number regardless of which loop produced it.

**Grounding.** `services/metrics/story.py` established the rule this reuses:
compute first, phrase second, then check the phrasing against what was
computed. The difference is what happens on a violation. Story discards the
text and falls back to a deterministic template, which it can do because it
renders one fixed shape of paragraph. A conversation has no template to fall
back to, and legitimate arithmetic ("about 3 degrees warmer") would trip a
hard rule constantly. So the check *annotates* instead: the response reports
whether every figure traces to a tool result, and names the ones that do not.
The UI can show that, and a demo can be honest about it, which a silently
discarded answer cannot.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.core.config import settings
from services.chat import catalog_context, store
from services.chat.orchestrator import build_delegate_tools
from services.chat.tools import ALL_TOOL_NAMES, Ledger, build_tools

logger = logging.getLogger(__name__)

# Delegate calls per turn, at the top level. Measured against the question
# types this is built for: "forecast X here and compare to last year" is one
# delegate call, "is it safe near Kochi and where's the nearest good zone"
# is two, and nothing sensible has needed more than five. A model that has
# not answered by here is looping, and one more pass will not save it. Each
# specialist has its own smaller bound — see orchestrator.SUB_MAX_ITERATIONS.
MAX_ITERATIONS = 6

_SYSTEM_PROMPT = """\
You are Maris, the ocean intelligence assistant for MarisAI. You are warm, \
curious and genuinely enthusiastic about the ocean — you enjoy this. Talk like \
a knowledgeable friend who happens to have live ocean data at hand, not like a \
database that learned English.

You do not hold ocean data yourself. You coordinate four specialists, each an \
expert with its own tools, and you delegate to them:

- delegate_to_ocean_analytics — forecasts, a *worldwide aggregate* ocean-state \
summary (no single coordinate), harmful algal bloom risk, fish habitat \
suitability, potential fishing zones, historical/past trends, and whether \
two or more variables are correlated over time.
- delegate_to_weather_safety — the *right-now* reading at one coordinate: \
current sea surface temperature, wind, waves, tide-gauge sea level, and \
other present-day sea/weather conditions, plus active hazard alerts and \
"is it safe to go out" questions (answered with a fixed, deterministic risk \
verdict, not a freeform guess).

A "what is the SST/wind/wave/tide right now at this point" question is \
always weather_safety, never ocean_analytics — ocean_analytics's "global \
ocean state" means a single worldwide summary number with no coordinate \
(get_global_ocean_summary), not a point reading. Sending a current-conditions \
question to ocean_analytics gets you a specialist with no tool for it.
- delegate_to_geospatial_risk — maritime boundary / Marine Protected Area \
proximity (geofencing), seafloor depth, safe-route planning between two points, \
and drift trajectory forecasting for a person or object overboard ("where will \
X drift to" — a probability envelope, not one predicted position).
- delegate_to_external_research — web search, fetching a specific webpage, \
and scientific-literature search, for anything MarisAI's own data cannot \
answer: recent news, an explanation of a current event, or published \
research. Its tools return other people's claims, not MarisAI measurements — \
relay them with their source, never as something MarisAI observed.

You also have get_documentation, your own tool rather than a delegate, for \
questions about MarisAI itself — how to use a feature, where a page lives, \
what a term or badge means. Call it directly; it is not ocean data, so it \
never needs a specialist. It returns a real /docs?c=... link — use that link \
verbatim rather than inventing a path.

A question can span more than one specialist ("is it safe to fish near Kochi \
today, and where's the nearest good zone" needs both weather_safety and \
ocean_analytics) — delegate to each one needs, then synthesise a single warm \
answer from what they reported. Give each delegate the coordinates, dates and \
any other detail it needs in its own question text; it does not see the rest \
of this conversation. The dataset catalog below is static knowledge you may \
answer directly, without delegating, since it is not a live measurement.

A "why is [place] unusually [warm/rough/...] right now" question usually \
needs two delegates in sequence, not one: first ocean_analytics or \
weather_safety for the actual measurement (an anomaly, a trend), then \
external_research — telling it what was measured — for context or an \
explanation. Do not send external_research a bare "why is it warm" with no \
measurement to explain; it has no ocean data of its own and would only be \
able to guess.

How to be good company:

- Be conversational and natural. Contractions are fine. A little personality is \
welcome, especially when the data is interesting — a marine heatwave or a \
strange wind field is worth sounding interested about.
- Remember what the person already told you and build on it. If they gave you a \
location earlier, do not make them repeat it.
- If a question is vague, make a sensible assumption, say what you assumed, and \
answer. Only ask a clarifying question when you genuinely cannot proceed.
- Offer a natural next step when there is an obvious one, but do not badger.
- If a question is not about the ocean, answer it briefly and warmly, then \
steer back to what you are good at.
- Detect the language the question was asked in and answer in that same \
language, including Indian regional languages (Hindi, Tamil, Telugu, Bengali, \
Malayalam, Kannada, Marathi, Gujarati, Odia, Punjabi, and others). Units and \
place names may stay as commonly written. If the language is ambiguous, match \
the script of the question.
- A fixed set of technical terms must stay in English even inside a \
non-English answer, exactly as written here, because a translated or \
transliterated version is ambiguous or misleading: SST, chlorophyll, wave \
height, wind speed, cyclone, PFZ, marine advisory. Say them in English, then \
explain in the local language if that helps — do not replace the English \
term itself.

Where the friendliness stops — these are absolute, and being agreeable never \
overrides them:

1. Never state a number a specialist did not report to you. You have no ocean \
data of your own. If a specialist says it could not get something, say so \
plainly and say why. Never estimate, interpolate, or reach for general \
knowledge to fill a gap — a warm guess about a real ocean measurement is worse \
than an honest "I could not get that", because someone may act on it.
2. Delegate rather than guessing at ocean data yourself.
3. A forecast is not an observation. Say which one you are giving, and include \
the uncertainty interval when a specialist gave you one.
4. Alerts here are threshold rules computed over real fields, not issued marine \
warnings. Never imply an official warning exists.
5. Coverage is genuinely uneven — habitat models cover the North Indian Ocean, \
bloom models the Arabian Sea, boundary/MPA geometry is an approximate \
reference. Outside those, say so rather than extrapolating.
6. external_research's tools return other people's claims (a news article, a \
paper), never a MarisAI measurement — always name the source when relaying \
one, and never present a single result as established fact the way you would \
a number from any other specialist.
7. Keep it tight — a few sentences unless more is asked for. Always name units."""


# The dataset catalog is appended to the prompt rather than served by a tenth
# tool, for two reasons recorded in TODO.md §4 and §6: the tool surface is
# already at nine against a 5-8 guideline and every tool is a prompt the model
# can get wrong, and 36 records fit in a single prompt anyway. Appending to
# `_SYSTEM_PROMPT` itself — rather than adding a second constant — is what
# keeps the grounding checker correct, since both `shown` blocks below list
# `_SYSTEM_PROMPT` by name and would not pick up a sibling.
_SYSTEM_PROMPT = f"{_SYSTEM_PROMPT}\n\n{catalog_context.CATALOG_PROMPT}"


class ChatError(RuntimeError):
    pass


def _model() -> Any:
    """Resolve LLM_PROVIDER to a tool-calling chat model.

    Adapters are imported lazily so an install only needs the package matching
    the configured provider. Ollama is served through the OpenAI adapter
    against its OpenAI-compatible endpoint rather than a fourth dependency —
    the tool-call wire format is identical.
    """
    provider = (settings.LLM_PROVIDER or "gemini").strip().lower()

    if not settings.LLM_API_KEY and provider != "ollama":
        raise ChatError(
            "The assistant is not configured. Set LLM_API_KEY (and optionally "
            "LLM_PROVIDER / LLM_MODEL) in the backend environment."
        )

    try:
        if provider == "gemini":
            from langchain_google_genai import ChatGoogleGenerativeAI

            return ChatGoogleGenerativeAI(
                model=settings.LLM_MODEL or "gemini-2.0-flash",
                google_api_key=settings.LLM_API_KEY,
                temperature=0,
            )

        from langchain_openai import ChatOpenAI

        if provider == "ollama":
            return ChatOpenAI(
                model=settings.LLM_MODEL or "llama3.1",
                base_url=(settings.LLM_BASE_URL or "http://localhost:11434") + "/v1",
                api_key=settings.LLM_API_KEY or "ollama",
                temperature=0,
            )
        if provider == "openai":
            return ChatOpenAI(
                model=settings.LLM_MODEL or "gpt-4o-mini",
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_BASE_URL or None,
                temperature=0,
            )
    except ImportError as exc:
        raise ChatError(
            f"The adapter for LLM_PROVIDER={provider!r} is not installed ({exc})."
        ) from exc

    raise ChatError(
        f"Unknown LLM_PROVIDER {provider!r}. Expected 'gemini', 'openai' or 'ollama'."
    )


# Grouped forms first, so "2,048" is one number rather than "2" and "048".
# Without the first branch the model writing a depth as "2,048 m" — which it
# does whenever a value passes a thousand — got split into two fragments,
# neither of which appears in any tool result, and a perfectly grounded answer
# was flagged as carrying two untraceable figures. That is precisely the
# cry-wolf failure `_ungrounded_numbers` documents: a banner that fires on
# correct answers teaches people to ignore the one that matters.
_NUMBER = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?")

# The same numbers, but only where they are *quantities* rather than digits
# living inside an identifier. A digit run *preceded* by a letter, underscore
# or dot is part of a name, not a measurement.
#
# Only the leading side is guarded, and that is deliberate rather than
# incomplete. Every identifier here segments before its digits —
# `..._BGC_001_028`, `WIND_GLO_PHY_L4_NRT_012_004`, `GEBCO_2021` — so the
# lookbehind alone rejects all of them. Guarding the *trailing* side as well
# was tried and broke three existing tests immediately: it rejects "30d" and
# "72E", which are exactly the unit-suffixed quantities the checker already
# had to learn not to cry wolf about (a user's own "10N 72E" coordinates, a
# tool description's "'24h', '7d', '30d'"). A number followed by a letter is
# usually a unit; a number preceded by one is usually a serial.
#
# This exists because the dataset catalog in the system prompt names real
# product ids — `GLOBAL_ANALYSISFORECAST_BGC_001_028`,
# `WIND_GLO_PHY_L4_NRT_012_004` — and every figure the model is *shown* becomes
# a figure it is allowed to state. Read naively, `_001_028` contributes "1" and
# "28" to the permitted set, so a fabricated "the water is 28.4 C" traced back
# to a product code and passed the check. Verified: adding the catalog turned
# `test_an_invented_number_is_reported_not_hidden` green, which is the exact
# shape of silent weakening this checker exists to prevent — the banner keeps
# working, it just stops firing.
#
# Applied to both sides deliberately. On the permitted side it stops ids
# laundering numbers in; on the answer side it stops the model being accused of
# inventing "028" when it correctly quotes a dataset id back.
_QUANTITY = re.compile(rf"(?<![\w.])(?:{_NUMBER.pattern})")


def _quantities(text: str) -> list[str]:
    return [match.group(0) for match in _QUANTITY.finditer(text)]


def _numeric(token: str) -> float:
    """`float()` for a token this module's regex can produce.

    Separate from a bare `float()` call because the grouped branch above emits
    strings `float()` rejects outright.
    """
    return float(token.replace(",", ""))

# Numbers that carry no factual claim about the ocean: list markers, a horizon
# the user themselves named, ordinary prose quantities. Checking these produces
# noise, not signal.
_IGNORED = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "12", "24", "100"}


def _renderings(value: float) -> set[str]:
    return {
        f"{value:.0f}", f"{value:.1f}", f"{value:.2f}",
        f"{abs(value):.0f}", f"{abs(value):.1f}", f"{abs(value):.2f}",
    }


def _ungrounded_numbers(text: str, ledger: Ledger, said: str = "") -> list[str]:
    """Figures in the answer that appear in no tool result.

    The permitted set is derived from the recorded results themselves rather
    than a hand-listed set of fields — the same reasoning as `story._verify`,
    where a maintained list kept rejecting faithful sentences for quoting
    numbers that appeared in the block's own labels.

    `said` carries everything the model was legitimately shown — the current
    question, the prior turns, the system prompt and the tool descriptions —
    and all of it is permitted. Two false positives forced this, both found by
    running real questions rather than by reading the code:

    - Asking about "10N 72E" made "You just gave me 10°N, 72°E" light up as
      unverifiable. Repeating a number back to the person who supplied it is
      not a fabrication.
    - Describing its own capabilities ("ranges of 24 h, 7 d, 30 d") flagged
      "30", a figure that appears verbatim in the tool descriptions the model
      was handed.

    This is the same lesson `story._verify` records: the permitted set has to
    be derived from what was actually put in front of the model, because a
    hand-maintained list keeps rejecting faithful sentences for quoting
    numbers out of its own labels. A checker that cries wolf on the user's own
    coordinates teaches people to ignore the banner that matters.

    Matching is done at several roundings because the model is asked to report
    these values in prose, and "18.7" for 18.7043 is a rendering, not an
    invention.
    """
    block = ledger.as_text() + "\n" + said
    allowed: set[str] = set(_IGNORED)
    for match in _quantities(block):
        allowed.add(match)
        allowed.add(match.lstrip("-"))
        # Also admit the ungrouped spelling: a tool reports 2048.0 and the
        # model writes "2,048", so the two must compare equal.
        allowed.add(match.replace(",", ""))
        try:
            allowed |= _renderings(_numeric(match))
        except ValueError:
            continue

    unsupported: list[str] = []
    for match in _quantities(text):
        candidates = {match, match.lstrip("-"), match.replace(",", "")}
        try:
            candidates |= _renderings(_numeric(match))
        except ValueError:
            continue
        if not candidates & allowed and match not in unsupported:
            unsupported.append(match)
    return unsupported


# "could not/couldn't/can't/... get/pull/fetch/..." — the shape the observed
# failure actually took ("I couldn't pull a safe-route plan..."), not a bare
# keyword like "sorry" or "unavailable", which shows up plenty in legitimate,
# accurate answers ("the model is unavailable outside the Arabian Sea").
#
# The apostrophe is a character class, not a literal `'`. A live re-run of
# the exact failure this check exists for wrote "couldn’t" with a curly
# Unicode apostrophe (U+2019) — every provider does this routinely — and a
# straight-quote-only pattern missed both live recurrences outright, passing
# its unit tests (which use `'`) while doing nothing on the real traffic that
# motivated it.
_REFUSAL_PATTERN = re.compile(
    r"\b(?:could\s*not|couldn[’']t|can[’']t|cannot|unable to|wasn[’']t able to|"
    r"was not able to)\s+"
    r"(?:get|pull|fetch|retrieve|find|obtain|access|provide|generate|compute|produce|put together)\b",
    re.IGNORECASE,
)


def _allowed_set(source_text: str) -> set[str]:
    """Every rendering `_ungrounded_numbers` would accept for a number drawn
    from `source_text` — factored out because `_false_refusal` needs the same
    matching in the opposite direction (does the answer *use* a ledger number,
    rather than does it *invent* one the ledger lacks)."""
    allowed: set[str] = set()
    for match in _quantities(source_text):
        allowed.add(match)
        allowed.add(match.lstrip("-"))
        allowed.add(match.replace(",", ""))
        try:
            allowed |= _renderings(_numeric(match))
        except ValueError:
            continue
    return allowed


def _false_refusal(text: str, ledger: Ledger) -> bool:
    """True when the answer reads as "I couldn't get that" despite the ledger
    already holding real tool results from this same turn.

    `_ungrounded_numbers` checks the opposite direction: a number in the
    answer that no tool reported. Nothing checked this one, and a live run
    found it (2026-08-24, see DONE.md): the orchestrator claimed it "couldn't
    pull a safe-route plan" after `plan_safe_route` and `get_seafloor_depth`
    had already succeeded and populated the ledger. `grounded` stayed `true`
    — a refusal states no numbers, so the existing check is structurally
    blind to a turn that has data and denies having it.

    Restricted to an answer that quotes *none* of the ledger's own numbers,
    not merely one containing a refusal phrase or one that happens to be
    numberless. Three weaker versions were tried and each broke on live
    traffic:

    - A numberless-answer rule missed a refusal that padded itself with an
      unrelated figure ("GEBCO's 0.05° grid" — true, but from the model's
      general knowledge, not from any tool call this turn).
    - A bare refusal-phrase rule would flag a legitimate partial failure
      ("the route avoids every MPA; I couldn't get the wave forecast for it")
      that still quotes a real figure for the part that worked.
    - **Matching against `ledger.as_text()` (arguments *and* results) still
      missed two live refusals**, because both restated the *input*
      coordinates ("I asked to route from 10.02°N, 76.96°E...") — present in
      every call's recorded `arguments`, not evidence a single result value
      was ever used. Matching is therefore against `result` fields only.
    """
    if not ledger.observations:
        return False
    if not _REFUSAL_PATTERN.search(text):
        return False

    results_text = json.dumps([entry.get("result") for entry in ledger.observations], default=str)
    ledger_numbers = _allowed_set(results_text)
    if not ledger_numbers:
        return False

    for match in _quantities(text):
        candidates = {match, match.lstrip("-"), match.replace(",", "")}
        try:
            candidates |= _renderings(_numeric(match))
        except ValueError:
            continue
        if candidates & ledger_numbers:
            return False  # the answer used at least one real figure
    return True


# Unicode blocks for the scripts `_SYSTEM_PROMPT`'s language list names
# (Hindi and Marathi share Devanagari; Punjabi is Gurmukhi). Latin-script
# Hindi ("Hinglish") is not caught by this — solving that needs real
# language-ID, out of scope for a glossary guardrail — so the check below is
# script-gated, not language-gated, and stays silent on any Latin-script
# answer.
_INDIC_SCRIPT = re.compile(
    "["
    r"ऀ-ॿ"  # Devanagari (Hindi, Marathi)
    r"ঀ-৿"  # Bengali
    r"਀-੿"  # Gurmukhi (Punjabi)
    r"઀-૿"  # Gujarati
    r"଀-୿"  # Oriya
    r"஀-௿"  # Tamil
    r"ఀ-౿"  # Telugu
    r"ಀ-೿"  # Kannada
    r"ഀ-ൿ"  # Malayalam
    "]"
)

# The seven terms sihtodo.md item 3 names verbatim, and nothing more — this
# guardrail is scoped to exactly what was asked for, not every technical word
# the assistant might use. Each tuple is the aliases, matched
# case-insensitively, that mean two things depending on which side they are
# checked against: found in `ledger.as_text()`, they mean "this turn's tool
# data touched this concept"; found in the answer, they mean "the concept was
# kept in English." Drawn from actually reading the tool result shapes:
# `services/openmeteo.py`'s `sea_surface_temperature`/`wave_height`/
# `wind_speed`, `services/pfz.py`'s `chlorophyll_mg_m3`/`sst_c` and its prose
# `reasons`, `services/cyclones.py`'s `active_cyclones_worldwide`. PFZ and
# "marine advisory" are coarser proxies than the other five — keyed off the
# `find_fishing_zones` tool name and the alert tools' own vocabulary
# respectively, since neither literal phrase reliably appears in a tool
# result the way "sst_c" or "wave_height" do.
_GLOSSARY: dict[str, tuple[str, ...]] = {
    "SST": ("sst", "sea_surface_temperature", "sea surface temperature"),
    "chlorophyll": ("chlorophyll",),
    "wave height": ("wave_height", "wave height"),
    "wind speed": ("wind_speed", "wind speed"),
    "cyclone": ("cyclone",),
    "PFZ": ("fishing_zones", "fishing zone", "potential fishing", "pfz"),
    "marine advisory": ("advisory", "alert"),
}


def _untranslated_glossary_terms(text: str, ledger: Ledger) -> list[str]:
    """Glossary concepts this turn's tool data touched that never appear in
    English anywhere in a non-English answer.

    Informational only, same as `_false_refusal` — this never blocks or
    rewrites the answer, it annotates it. It also cannot fire on an English
    (or Latin-script/Hinglish) answer at all: `_INDIC_SCRIPT` is checked
    first, so the overwhelming majority of turns never reach the per-term
    loop. That is the deliberate defence against the cry-wolf failure
    `_ungrounded_numbers` documents at length — a checker that flags correct
    answers teaches people to ignore the one that matters.

    The `_SYSTEM_PROMPT` instruction to keep these terms in English is the
    primary defence; this is the secondary, informational backstop, exactly
    as `_ungrounded_numbers` backstops "never state a number you did not get
    from a tool."

    A term's own alias list is used on *both* sides of the check: present in
    the ledger it means the concept was used, present in the answer it means
    the concept was kept in English — so an answer that writes "sea surface
    temperature" instead of the bare abbreviation "SST" still passes, and one
    that calls a wave-height forecast a "lehar ki uchai" without ever writing
    the English phrase does not.
    """
    if not ledger.observations or not _INDIC_SCRIPT.search(text):
        return []

    block = ledger.as_text().lower()
    lowered = text.lower()
    gaps: list[str] = []
    for term, aliases in _GLOSSARY.items():
        if not any(alias in block for alias in aliases):
            continue  # this turn never touched the concept
        if not any(alias in lowered for alias in aliases):
            gaps.append(term)
    return gaps


def _schema_prose(tool: Any) -> str:
    """The `description` strings from a tool's argument schema, and nothing else.

    Deliberately not the whole JSON schema. That carries the validation bounds
    — -90, 90, -180, 180, 365 — and admitting those would let a fabricated
    "the water is 90 °C" pass the grounding check as though a provider had
    reported it. Descriptions are prose the model reads and may quote back;
    bounds are machinery it should never be quoting at all.
    """
    try:
        properties = tool.args_schema.model_json_schema().get("properties", {})
    except Exception:  # noqa: BLE001 - a schema-less tool must not break the check
        return ""
    return " ".join(
        str(field["description"])
        for field in properties.values()
        if isinstance(field, dict) and "description" in field
    )


def _all_specialist_tool_texts() -> list[str]:
    """Every specialist tool's description and schema prose, for the
    grounding check's permitted set.

    The top-level orchestrator only ever calls the three delegate tools
    directly, but a figure named in an *inner* tool's description (e.g. the
    "'24h', '7d', '30d'" in `get_historical_series`'s schema) is still
    something the system as a whole was told, and the orchestrator's final
    answer may relay a specialist's own description of its capabilities.
    Built on a throwaway `Ledger` purely to harvest metadata — nothing here
    is ever invoked.
    """
    scratch = build_tools(Ledger(), ALL_TOOL_NAMES)
    texts: list[str] = []
    for tool in scratch:
        texts.append(tool.description)
        texts.append(_schema_prose(tool))
    return texts


# Prefix `orchestrator.build_delegate_tools` names every delegate tool with,
# e.g. "delegate_to_geospatial_risk" -> specialist name "geospatial_risk".
_DELEGATE_PREFIX = "delegate_to_"


def _record_delegation(call: dict[str, Any], delegations: list[dict[str, Any]]) -> None:
    """If `call` is a delegate call, record which specialist and why.

    This is the orchestrator's own reasoning step made visible: the `question`
    argument is what it decided this sub-task is, in its own words, before the
    specialist ever ran. PS2 asks for demonstrable "autonomous planning,
    reasoning, tool selection" and today's trace only showed *which* specialist
    called *which* tool, not *why* the orchestrator delegated to it — this is
    the cheap, honest version of that: no separate reasoning call, just
    surfacing an argument the model already produces.
    """
    name = call.get("name") or ""
    if not name.startswith(_DELEGATE_PREFIX):
        return
    args = call.get("args") or {}
    question = args.get("question", "") if isinstance(args, dict) else ""
    delegations.append({"agent": name[len(_DELEGATE_PREFIX):], "question": question})


def _question_message(question: str, image: str | None) -> HumanMessage:
    """The turn's `HumanMessage` — multimodal only when an image is attached.

    The content-block shape (`{"type": "image_url", "image_url": {"url": ...}}`)
    is the one LangChain standardised across `ChatOpenAI` and
    `ChatGoogleGenerativeAI`; the Ollama path is served through the OpenAI
    adapter (see `_model()`) against an OpenAI-compatible endpoint, so the same
    shape applies there too — whether the *configured model itself* understands
    an image is a property of that model, not of this plumbing.

    **Scope, deliberately**: the image is not persisted to the chat transcript
    (`store.record` only ever took question/answer text) and is not forwarded
    to a delegate specialist's own sub-loop — each specialist already "does not
    see the rest of this conversation" per the system prompt, and the ask this
    implements is "describe/answer about an attached image" as a direct,
    top-level capability, not a new image-analysis tool for every specialist.
    """
    if not image:
        return HumanMessage(content=question)
    return HumanMessage(
        content=[
            {"type": "text", "text": question},
            {"type": "image_url", "image_url": {"url": image}},
        ]
    )


def _history_messages(history: list[dict[str, str]]) -> list[BaseMessage]:
    messages: list[BaseMessage] = []
    for turn in history[-10:]:
        role = (turn.get("role") or "").lower()
        content = turn.get("content") or ""
        if not content:
            continue
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role in {"assistant", "ai"}:
            messages.append(AIMessage(content=content))
    return messages


async def answer(
    question: str,
    history: list[dict[str, str]] | None = None,
    *,
    session_id: str | None = None,
    client_id: str | None = None,
    image: str | None = None,
) -> dict[str, Any]:
    """Run one conversation turn to completion.

    Returns the text alongside the tool calls that produced it, so the caller
    can show provenance rather than asking the user to trust the paragraph.

    When persistence is configured, **the stored transcript is the authority**
    on what was said, not the `history` argument. That is the fix for the chat
    forgetting itself: the browser's copy is lost on reload, and trusting it
    also let a client silently rewrite what the model believed it had said.
    `history` remains the fallback for a deployment with no database.

    `image`, when given, is a `data:image/...;base64,...` URL attached to this
    turn — see `_question_message`'s docstring for the multimodal content
    shape and what is deliberately out of scope.
    """
    question = (question or "").strip()
    if not question:
        raise ChatError("Ask a question about ocean conditions.")

    resolved: uuid.UUID | None = None
    if client_id and store.enabled():
        resolved = await store.ensure_session(session_id, client_id, question)

    prior = await store.history(resolved) if resolved else (history or [])
    history_messages = _history_messages(prior)

    ledger = Ledger()
    # The delegate tools plus one direct tool: get_documentation is static
    # platform self-knowledge, not a live measurement, so it does not need a
    # specialist round-trip — same precedent as the dataset catalog above,
    # which is answered from the prompt rather than a tenth specialist tool.
    tools = build_delegate_tools(ledger, history_messages, _model) + build_tools(
        ledger, ["get_documentation"]
    )
    model = _model().bind_tools(tools)
    by_name = {tool.name: tool for tool in tools}

    messages: list[BaseMessage] = [SystemMessage(content=_SYSTEM_PROMPT)]
    messages.extend(history_messages)
    messages.append(_question_message(question, image))

    delegations: list[dict[str, Any]] = []
    truncated = False
    for _ in range(MAX_ITERATIONS):
        try:
            reply = await model.ainvoke(messages)
        except Exception as exc:  # noqa: BLE001 - provider clients raise widely
            logger.exception("chat model call failed")
            raise ChatError("The AI provider could not be reached.") from exc

        messages.append(reply)
        calls = getattr(reply, "tool_calls", None) or []
        if not calls:
            break

        for call in calls:
            tool = by_name.get(call["name"])
            _record_delegation(call, delegations)
            if tool is None:
                output = f"No such tool: {call['name']}"
            else:
                output = await tool.ainvoke(call["args"])
            messages.append(ToolMessage(content=output, tool_call_id=call["id"]))
    else:
        # Fell out of the loop still wanting tools. Answer from what was
        # gathered rather than silently returning the last tool call as if it
        # were a reply.
        truncated = True

    text = ""
    for message in reversed(messages):
        if isinstance(message, AIMessage) and isinstance(message.content, str) and message.content.strip():
            text = message.content.strip()
            break

    if not text:
        text = (
            "I could not put together an answer from the available data. "
            "Try narrowing the question to one variable and one location."
        )

    # Everything the model was shown, not merely everything it was told by the
    # user: the delegate tool descriptions name each specialist's domain, which
    # it will quote back when asked what it can do.
    shown = "\n".join(
        [
            question,
            *(turn.get("content", "") for turn in prior),
            _SYSTEM_PROMPT,
            *(tool.description for tool in tools),
            *(_schema_prose(tool) for tool in tools),
            *_all_specialist_tool_texts(),
        ]
    )
    unsupported = _ungrounded_numbers(text, ledger, shown)
    if unsupported:
        logger.warning(f"chat answer carried ungrounded numbers: {unsupported}")

    possible_false_refusal = _false_refusal(text, ledger)
    if possible_false_refusal:
        logger.warning(
            f"chat answer read as a refusal despite {len(ledger.observations)} "
            "successful tool call(s) this turn"
        )

    glossary_gaps = _untranslated_glossary_terms(text, ledger)
    if glossary_gaps:
        logger.warning(f"chat answer may have mistranslated: {glossary_gaps}")

    reply = {
        "answer": text,
        "grounded": not unsupported,
        "unsupported_numbers": unsupported,
        "possible_false_refusal": possible_false_refusal,
        "glossary_gaps": glossary_gaps,
        "observations": ledger.observations,
        "sources": ledger.sources(),
        "delegations": delegations,
        "truncated": truncated,
        "session_id": str(resolved) if resolved else None,
    }

    # After the answer is assembled, never before: a failed write must cost the
    # transcript, not the reply the user is waiting on.
    if resolved:
        await store.record(resolved, question, reply)

    return reply


async def answer_stream(
    question: str,
    history: list[dict[str, str]] | None = None,
    *,
    session_id: str | None = None,
    client_id: str | None = None,
    image: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """`answer()`, yielded as it happens.

    Same bounded loop, same `Ledger`, same grounding check — the only thing
    that changes is when the caller learns about each part. `answer()` is
    unchanged and remains the non-streaming path.

    **Why this exists.** The whole point of the agent is that it calls tools,
    and a turn that fetches three ocean fields takes tens of seconds. Returning
    one JSON blob at the end means the user watches a spinner through all of
    it with no evidence anything is happening. The `tool` events below are the
    substance of that: "asking Copernicus for SST at 10N 72E" is more
    reassuring than any progress bar, and it is true.

    Events yielded, each a dict with a `type`:

    - ``tool``  — one per tool call, as it completes.
    - ``delta`` — a fragment of the answer text.
    - ``reset`` — discard the ``delta`` text received so far (see below).
    - ``meta``  — terminal. Carries the grounding verdict and provenance.

    **`grounded` cannot be streamed, and that is the important constraint.**
    It is computed by checking the *finished* text against everything the tools
    returned, so it is only knowable once the last token has arrived. It
    therefore rides on the terminal ``meta`` event, and a client must not show
    a "verified" affordance before then — doing so would assert a check that
    has not run. Stream the text as unverified; resolve it on ``meta``.

    **Why `reset` is needed.** Whether a turn is the final answer or another
    round of tool calls is not knowable until its stream ends. Text is
    therefore emitted optimistically, and on the rare turn that emits prose
    *and then* asks for a tool, that prose was preamble rather than the answer
    — `reset` tells the client to drop it. In practice this fires almost never
    (models emit text or tool calls, not both), but "almost never" is not
    "never", and the alternative is buffering the entire answer, which would
    defeat the point.
    """
    question = (question or "").strip()
    if not question:
        raise ChatError("Ask a question about ocean conditions.")

    resolved: uuid.UUID | None = None
    if client_id and store.enabled():
        resolved = await store.ensure_session(session_id, client_id, question)

    prior = await store.history(resolved) if resolved else (history or [])
    history_messages = _history_messages(prior)

    ledger = Ledger()
    # The delegate tools plus one direct tool: get_documentation is static
    # platform self-knowledge, not a live measurement, so it does not need a
    # specialist round-trip — same precedent as the dataset catalog above,
    # which is answered from the prompt rather than a tenth specialist tool.
    tools = build_delegate_tools(ledger, history_messages, _model) + build_tools(
        ledger, ["get_documentation"]
    )
    model = _model().bind_tools(tools)
    by_name = {tool.name: tool for tool in tools}

    messages: list[BaseMessage] = [SystemMessage(content=_SYSTEM_PROMPT)]
    messages.extend(history_messages)
    messages.append(_question_message(question, image))

    delegations: list[dict[str, Any]] = []
    truncated = False
    for _ in range(MAX_ITERATIONS):
        streamed = ""
        accumulated: Any = None
        try:
            async for chunk in model.astream(messages):
                accumulated = chunk if accumulated is None else accumulated + chunk
                piece = chunk.content if isinstance(chunk.content, str) else ""
                if piece:
                    streamed += piece
                    yield {"type": "delta", "text": piece}
        except Exception as exc:  # noqa: BLE001 - provider clients raise widely
            logger.exception("chat model stream failed")
            raise ChatError("The AI provider could not be reached.") from exc

        if accumulated is None:
            break

        messages.append(accumulated)
        calls = getattr(accumulated, "tool_calls", None) or []
        if not calls:
            break

        # This turn was tool calls after all, so anything already streamed was
        # preamble, not the answer.
        if streamed.strip():
            yield {"type": "reset"}

        for call in calls:
            tool = by_name.get(call["name"])
            before_delegations = len(delegations)
            _record_delegation(call, delegations)
            # Emitted before the call runs, unlike the `tool` event below —
            # this *is* the orchestrator's decision, not its outcome, so there
            # is nothing to wait on. A specialist can take tens of seconds;
            # showing why it was asked before it starts is the whole point.
            if len(delegations) > before_delegations:
                yield {"type": "delegate", **delegations[-1]}
            before = len(ledger.observations)
            if tool is None:
                output = f"No such tool: {call['name']}"
            else:
                output = await tool.ainvoke(call["args"])
            messages.append(ToolMessage(content=output, tool_call_id=call["id"]))
            # The delegate call itself is orchestration plumbing, not a data
            # observation — what the client should see is the specialist's own
            # tool calls, which `build_delegate_tools` records into this same
            # `ledger` (tagged with `agent`) while the call above was running.
            # Emitted after the call resolves rather than before it, so the
            # client never shows a tool that turned out to fail as though it
            # had produced something.
            for observation in ledger.observations[before:]:
                yield {
                    "type": "tool",
                    "tool": observation["tool"],
                    "arguments": observation["arguments"],
                    "agent": observation.get("agent"),
                }
    else:
        truncated = True

    text = ""
    for message in reversed(messages):
        if isinstance(message, AIMessage) and isinstance(message.content, str) and message.content.strip():
            text = message.content.strip()
            break

    if not text:
        text = (
            "I could not put together an answer from the available data. "
            "Try narrowing the question to one variable and one location."
        )
        # Nothing usable was streamed, so the client has nothing to replace.
        yield {"type": "reset"}
        yield {"type": "delta", "text": text}

    shown = "\n".join(
        [
            question,
            *(turn.get("content", "") for turn in prior),
            _SYSTEM_PROMPT,
            *(tool.description for tool in tools),
            *(_schema_prose(tool) for tool in tools),
            *_all_specialist_tool_texts(),
        ]
    )
    unsupported = _ungrounded_numbers(text, ledger, shown)
    if unsupported:
        logger.warning(f"chat answer carried ungrounded numbers: {unsupported}")

    possible_false_refusal = _false_refusal(text, ledger)
    if possible_false_refusal:
        logger.warning(
            f"chat answer read as a refusal despite {len(ledger.observations)} "
            "successful tool call(s) this turn"
        )

    glossary_gaps = _untranslated_glossary_terms(text, ledger)
    if glossary_gaps:
        logger.warning(f"chat answer may have mistranslated: {glossary_gaps}")

    reply = {
        "answer": text,
        "grounded": not unsupported,
        "unsupported_numbers": unsupported,
        "possible_false_refusal": possible_false_refusal,
        "glossary_gaps": glossary_gaps,
        "observations": ledger.observations,
        "sources": ledger.sources(),
        "delegations": delegations,
        "truncated": truncated,
        "session_id": str(resolved) if resolved else None,
    }

    # Same ordering rule as `answer()`: persist only once the reply is
    # assembled, so a failed write costs the transcript rather than the answer.
    if resolved:
        await store.record(resolved, question, reply)

    yield {"type": "meta", **reply}
