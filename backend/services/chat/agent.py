"""The conversational agent: a bounded tool-calling loop over MarisAI's data.

**Why an explicit loop rather than a prebuilt agent executor.** Two reasons,
both operational. First, the iteration count has to be a hard bound: this runs
inside the API process, and an agent that can decide to keep calling tools is
an availability risk, not just a cost one. Second, the grounding check below
needs the tool results and the final text together, which a framework that
hands back only the answer makes awkward. `langchain-core`'s tool binding gives
the useful half — schema generation, provider-neutral tool-call parsing —
without the loop being opaque.

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
from services.chat import store
from services.chat.tools import Ledger, build_tools

logger = logging.getLogger(__name__)

# Tool calls per turn. Measured against the question types this is built for:
# "forecast X here and compare to last year" is three calls, and nothing
# sensible has needed more than five. A model that has not answered by here is
# looping, and one more pass will not save it.
MAX_ITERATIONS = 6

_SYSTEM_PROMPT = """\
You are Maris, the ocean intelligence assistant for MarisAI. You are warm, \
curious and genuinely enthusiastic about the ocean — you enjoy this. Talk like \
a knowledgeable friend who happens to have live ocean data at hand, not like a \
database that learned English.

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

Where the friendliness stops — these are absolute, and being agreeable never \
overrides them:

1. Never state a number you did not get from a tool. You have no ocean data of \
your own. If a tool fails or returns nothing, say so plainly and say why. Never \
estimate, interpolate, or reach for general knowledge to fill a gap — a warm \
guess about a real ocean measurement is worse than an honest "I could not get \
that", because someone may act on it.
2. Call tools rather than guessing. If you are unsure of a variable's key, call \
list_available_variables first.
3. A forecast is not an observation. Say which one you are giving, and include \
the uncertainty interval when you have one.
4. Alerts here are threshold rules computed over real fields, not issued marine \
warnings. Never imply an official warning exists.
5. Coverage is genuinely uneven. Habitat models cover the North Indian Ocean and \
bloom models the Arabian Sea. Outside those, say so rather than extrapolating.
6. Keep it tight — a few sentences unless more is asked for. Always name units."""


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
    for match in _NUMBER.findall(block):
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
    for match in _NUMBER.findall(text):
        candidates = {match, match.lstrip("-"), match.replace(",", "")}
        try:
            candidates |= _renderings(_numeric(match))
        except ValueError:
            continue
        if not candidates & allowed and match not in unsupported:
            unsupported.append(match)
    return unsupported


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
) -> dict[str, Any]:
    """Run one conversation turn to completion.

    Returns the text alongside the tool calls that produced it, so the caller
    can show provenance rather than asking the user to trust the paragraph.

    When persistence is configured, **the stored transcript is the authority**
    on what was said, not the `history` argument. That is the fix for the chat
    forgetting itself: the browser's copy is lost on reload, and trusting it
    also let a client silently rewrite what the model believed it had said.
    `history` remains the fallback for a deployment with no database.
    """
    question = (question or "").strip()
    if not question:
        raise ChatError("Ask a question about ocean conditions.")

    resolved: uuid.UUID | None = None
    if client_id and store.enabled():
        resolved = await store.ensure_session(session_id, client_id, question)

    prior = await store.history(resolved) if resolved else (history or [])

    ledger = Ledger()
    tools = build_tools(ledger)
    model = _model().bind_tools(tools)
    by_name = {tool.name: tool for tool in tools}

    messages: list[BaseMessage] = [SystemMessage(content=_SYSTEM_PROMPT)]
    messages.extend(_history_messages(prior))
    messages.append(HumanMessage(content=question))

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
    # user: the tool descriptions carry horizons and ranges it will quote back
    # when asked what it can do.
    shown = "\n".join(
        [
            question,
            *(turn.get("content", "") for turn in prior),
            _SYSTEM_PROMPT,
            *(tool.description for tool in tools),
            *(_schema_prose(tool) for tool in tools),
        ]
    )
    unsupported = _ungrounded_numbers(text, ledger, shown)
    if unsupported:
        logger.warning(f"chat answer carried ungrounded numbers: {unsupported}")

    reply = {
        "answer": text,
        "grounded": not unsupported,
        "unsupported_numbers": unsupported,
        "observations": ledger.observations,
        "sources": ledger.sources(),
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

    ledger = Ledger()
    tools = build_tools(ledger)
    model = _model().bind_tools(tools)
    by_name = {tool.name: tool for tool in tools}

    messages: list[BaseMessage] = [SystemMessage(content=_SYSTEM_PROMPT)]
    messages.extend(_history_messages(prior))
    messages.append(HumanMessage(content=question))

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
            if tool is None:
                output = f"No such tool: {call['name']}"
            else:
                output = await tool.ainvoke(call["args"])
            messages.append(ToolMessage(content=output, tool_call_id=call["id"]))
            # Emitted after the call resolves rather than before it, so the
            # client never shows a tool that turned out to fail as though it
            # had produced something.
            yield {
                "type": "tool",
                "tool": call["name"],
                "arguments": call.get("args") or {},
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
        ]
    )
    unsupported = _ungrounded_numbers(text, ledger, shown)
    if unsupported:
        logger.warning(f"chat answer carried ungrounded numbers: {unsupported}")

    reply = {
        "answer": text,
        "grounded": not unsupported,
        "unsupported_numbers": unsupported,
        "observations": ledger.observations,
        "sources": ledger.sources(),
        "truncated": truncated,
        "session_id": str(resolved) if resolved else None,
    }

    # Same ordering rule as `answer()`: persist only once the reply is
    # assembled, so a failed write costs the transcript rather than the answer.
    if resolved:
        await store.record(resolved, question, reply)

    yield {"type": "meta", **reply}
