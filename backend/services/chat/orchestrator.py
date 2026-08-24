"""Specialist sub-agents the top-level loop in `agent.py` delegates to.

**Why a second, smaller loop rather than a flat tool call.** A delegate tool
must itself decide which of its specialist's tools to call and in what order
— "plan a safe route from A to B" needs `plan_safe_route`, but a first
question like "is it safe to fish near Kochi" needs `get_current_conditions`
*then* possibly `get_active_alerts`. That is a bounded agent loop in its own
right, just scoped to one specialist's tools and system prompt, and it is the
same explicit-loop-over-prebuilt-executor shape `agent.py`'s own loop already
uses, for the same reasons.

**Why sub-agent tool calls land in the same `Ledger` as the top level.**
`services/chat/tools.py::build_tools` already threads an `agent` tag through
to `Ledger.record`; `agent.py`'s grounding check reads the whole ledger
regardless of which loop populated it, so a number a specialist reported is
exactly as verifiable as one the old single loop reported — the multi-agent
split does not weaken grounding.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from services.chat.specialists import SPECIALISTS
from services.chat.tools import Ledger, build_tools

# Smaller than the top-level loop's MAX_ITERATIONS: a specialist answers one
# narrow, delegated sub-task, not a whole multi-domain conversation turn.
#
# 4 was measured too tight for `geospatial_risk` specifically: asked to plan a
# route *and* describe depth along it, the model (correctly, per its prompt's
# "never state a figure without calling the tool first") called
# `plan_safe_route` then `get_seafloor_depth` up to the iteration cap with no
# turn left to synthesize an answer — the specialist returned its truncated-
# fallback text, and the top-level orchestrator then improvised an apology
# around it. 5 leaves one call of headroom for a route (1) plus the prompt's
# own "two or three depth calls" bound (up to 3) plus a final answer (1).
SUB_MAX_ITERATIONS = 5


class SpecialistResult:
    __slots__ = ("text", "truncated")

    def __init__(self, text: str, truncated: bool) -> None:
        self.text = text
        self.truncated = truncated


async def run_specialist(
    name: str,
    question: str,
    ledger: Ledger,
    history: list[BaseMessage],
    model_factory: Callable[[], Any],
) -> SpecialistResult:
    spec = SPECIALISTS[name]
    tools = build_tools(ledger, list(spec.tool_names), agent=name)
    model = model_factory().bind_tools(tools)
    by_name = {tool.name: tool for tool in tools}

    messages: list[BaseMessage] = [
        SystemMessage(content=spec.system_prompt),
        *history,
        HumanMessage(content=question),
    ]

    truncated = False
    for _ in range(SUB_MAX_ITERATIONS):
        reply = await model.ainvoke(messages)
        messages.append(reply)
        calls = getattr(reply, "tool_calls", None) or []
        if not calls:
            break
        for call in calls:
            tool = by_name.get(call["name"])
            output = (
                f"No such tool: {call['name']}"
                if tool is None
                else await tool.ainvoke(call["args"])
            )
            messages.append(ToolMessage(content=output, tool_call_id=call["id"]))
    else:
        truncated = True

    text = ""
    for message in reversed(messages):
        if isinstance(message, AIMessage) and isinstance(message.content, str) and message.content.strip():
            text = message.content.strip()
            break
    if not text:
        text = "This specialist could not produce an answer from the available data."

    return SpecialistResult(text=text, truncated=truncated)


class DelegateArgs(BaseModel):
    question: str = Field(
        ...,
        description=(
            "The question or sub-task to hand to this specialist, in the "
            "specialist's own words. Include any coordinates, dates or other "
            "detail it needs — it does not see the rest of the conversation "
            "beyond recent history."
        ),
    )


def build_delegate_tools(
    ledger: Ledger, history: list[BaseMessage], model_factory: Callable[[], Any]
) -> list[StructuredTool]:
    """One delegate tool per specialist, for the top-level orchestrator to call.

    `history` is the same recent-turn window the top-level loop already
    assembled, passed straight through so a specialist answering "and what
    about tomorrow" understands what "tomorrow" refers to without the
    orchestrator having to restate it in `question`.
    """
    tools: list[StructuredTool] = []
    for name, spec in SPECIALISTS.items():

        def make(name: str) -> Any:
            async def run(question: str) -> str:
                result = await run_specialist(name, question, ledger, history, model_factory)
                return result.text

            return run

        tools.append(
            StructuredTool.from_function(
                coroutine=make(name),
                name=f"delegate_to_{name}",
                description=spec.description,
                args_schema=DelegateArgs,
            )
        )
    return tools
