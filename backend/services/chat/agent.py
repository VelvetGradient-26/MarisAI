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
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.core.config import settings
from services.chat.tools import Ledger, build_tools

logger = logging.getLogger(__name__)

# Tool calls per turn. Measured against the question types this is built for:
# "forecast X here and compare to last year" is three calls, and nothing
# sensible has needed more than five. A model that has not answered by here is
# looping, and one more pass will not save it.
MAX_ITERATIONS = 6

_SYSTEM_PROMPT = """\
You are MarisAI's ocean intelligence assistant. You answer questions about \
ocean and atmospheric conditions using the tools provided.

Rules you must follow:

1. Never state a number you did not get from a tool. You have no ocean data of \
your own. If a tool fails or returns nothing, say the data is unavailable and \
say why — never estimate, interpolate, or fall back on general knowledge for a \
measurement.
2. Call tools rather than guessing. If you do not know a variable's key, call \
list_available_variables first.
3. A forecast is not an observation. Say which one you are reporting, and give \
the uncertainty interval when you have one.
4. Alerts are threshold rules computed over real fields, not issued marine \
warnings. Never imply an official warning exists.
5. Coverage is real and uneven. Habitat models cover the North Indian Ocean and \
bloom models the Arabian Sea; outside those, say so rather than extrapolating.
6. Be concise. Two or three sentences unless asked for more. Name the units.

If a question is not about ocean data, answer briefly and steer back."""


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


_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")

# Numbers that carry no factual claim about the ocean: list markers, a horizon
# the user themselves named, ordinary prose quantities. Checking these produces
# noise, not signal.
_IGNORED = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "12", "24", "100"}


def _renderings(value: float) -> set[str]:
    return {
        f"{value:.0f}", f"{value:.1f}", f"{value:.2f}",
        f"{abs(value):.0f}", f"{abs(value):.1f}", f"{abs(value):.2f}",
    }


def _ungrounded_numbers(text: str, ledger: Ledger) -> list[str]:
    """Figures in the answer that appear in no tool result.

    The permitted set is derived from the recorded results themselves rather
    than a hand-listed set of fields — the same reasoning as `story._verify`,
    where a maintained list kept rejecting faithful sentences for quoting
    numbers that appeared in the block's own labels.

    Matching is done at several roundings because the model is asked to report
    these values in prose, and "18.7" for 18.7043 is a rendering, not an
    invention.
    """
    block = ledger.as_text()
    allowed: set[str] = set(_IGNORED)
    for match in _NUMBER.findall(block):
        allowed.add(match)
        allowed.add(match.lstrip("-"))
        try:
            allowed |= _renderings(float(match))
        except ValueError:
            continue

    unsupported: list[str] = []
    for match in _NUMBER.findall(text):
        candidates = {match, match.lstrip("-")}
        try:
            candidates |= _renderings(float(match))
        except ValueError:
            continue
        if not candidates & allowed and match not in unsupported:
            unsupported.append(match)
    return unsupported


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


async def answer(question: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Run one conversation turn to completion.

    Returns the text alongside the tool calls that produced it, so the caller
    can show provenance rather than asking the user to trust the paragraph.
    """
    question = (question or "").strip()
    if not question:
        raise ChatError("Ask a question about ocean conditions.")

    ledger = Ledger()
    tools = build_tools(ledger)
    model = _model().bind_tools(tools)
    by_name = {tool.name: tool for tool in tools}

    messages: list[BaseMessage] = [SystemMessage(content=_SYSTEM_PROMPT)]
    messages.extend(_history_messages(history or []))
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

    unsupported = _ungrounded_numbers(text, ledger)
    if unsupported:
        logger.warning(f"chat answer carried ungrounded numbers: {unsupported}")

    return {
        "answer": text,
        "grounded": not unsupported,
        "unsupported_numbers": unsupported,
        "observations": ledger.observations,
        "sources": ledger.sources(),
        "truncated": truncated,
    }
