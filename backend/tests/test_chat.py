"""The agent loop, its bounds, and the grounding check.

No provider is contacted. The model is a scripted stand-in that emits the
tool-call shape `bind_tools` produces, which is what lets the loop's control
flow be tested at all — against a real provider these paths are nondeterministic
and only reachable by luck.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from services.chat import agent
from services.chat.tools import Ledger, build_tools


class ScriptedModel:
    """Returns a queued reply per call, recording what it was sent.

    Mimics the two halves of the contract the loop depends on: `bind_tools`
    returns something invokable, and a reply carries `tool_calls` when the model
    wants a tool run.
    """

    def __init__(self, replies: list[AIMessage]) -> None:
        self.replies = list(replies)
        self.seen: list[list] = []
        self.tools: list = []

    def bind_tools(self, tools):
        self.tools = tools
        return self

    async def ainvoke(self, messages):
        self.seen.append(list(messages))
        if not self.replies:
            return AIMessage(content="done")
        return self.replies.pop(0)


def _tool_call(name: str, args: dict, call_id: str = "c1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


@pytest.fixture
def patched(monkeypatch):
    def install(model: ScriptedModel):
        monkeypatch.setattr(agent, "_model", lambda: model)
        return model

    return install


@pytest.fixture
def depth(monkeypatch):
    """Stand in for the bathymetry provider.

    Patched at the *service* rather than at `tools._seafloor_depth`, because
    the tool imports it lazily inside the call — so this exercises the real
    wiring, and a patch at the tool level would silently miss (the spec table
    captures function references at import time and would still call out to
    Ifremer).
    """

    def install(result: dict | Exception):
        async def fake(*, latitude: float, longitude: float):
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr("services.bathymetry.get_elevation", fake)

    return install


@pytest.mark.asyncio
async def test_a_tool_result_reaches_the_answer(patched, depth):
    """The whole point of the loop: the model's second turn can see tool output."""
    depth({"elevation_m": -1234.5, "source": "GEBCO_2021 via Ifremer ERDDAP"})

    model = patched(
        ScriptedModel(
            [
                _tool_call("get_seafloor_depth", {"latitude": 10.0, "longitude": 72.0}),
                AIMessage(content="The seafloor there is about 1234.5 m deep."),
            ]
        )
    )

    result = await agent.answer("How deep is it at 10N 72E?")

    assert "1234.5" in result["answer"]
    assert result["grounded"] is True
    assert result["observations"][0]["tool"] == "get_seafloor_depth"
    assert "GEBCO_2021 via Ifremer ERDDAP" in result["sources"]
    # The tool result must actually have been fed back, not merely recorded.
    assert any("1234.5" in str(m.content) for m in model.seen[-1])


@pytest.mark.asyncio
async def test_an_invented_number_is_reported_not_hidden(patched, depth):
    """A figure traceable to no tool result is the failure mode that matters.

    Not discarded — a conversation has no template to fall back to — but the
    caller is told, so a UI can mark it and a demo can be honest.
    """

    depth({"elevation_m": -1234.5, "source": "GEBCO"})

    patched(
        ScriptedModel(
            [
                _tool_call("get_seafloor_depth", {"latitude": 10.0, "longitude": 72.0}),
                AIMessage(content="It is 1234.5 m deep and the water is 28.4 C."),
            ]
        )
    )

    result = await agent.answer("How deep is it?")

    assert result["grounded"] is False
    assert "28.4" in result["unsupported_numbers"]
    assert "1234.5" not in result["unsupported_numbers"]


@pytest.mark.asyncio
async def test_the_users_own_numbers_are_not_flagged(patched):
    """Repeating a number back to the person who supplied it is not a
    fabrication, and treating it as one is worse than useless.

    Found live: asking about "10N 72E" produced "You just gave me 10°N, 72°E",
    which lit up as unverifiable because no tool had returned 72. A banner that
    fires on the user's own coordinates trains people to ignore the one that
    means something.
    """
    patched(ScriptedModel([AIMessage(content="You just gave me 10 N and 72 E.")]))

    result = await agent.answer("My spot is 10N 72E, remember it")

    assert result["grounded"] is True, result["unsupported_numbers"]


@pytest.mark.asyncio
async def test_numbers_from_earlier_turns_are_not_flagged(patched):
    """The allowance has to cover the whole conversation, not just this turn —
    a coordinate given three messages ago is still the user's own."""
    patched(ScriptedModel([AIMessage(content="Back at 10 N, 72 E as you asked.")]))

    result = await agent.answer(
        "and there?",
        [{"role": "user", "content": "look at 10N 72E"}],
    )

    assert result["grounded"] is True, result["unsupported_numbers"]


@pytest.mark.asyncio
async def test_the_loop_is_bounded(patched, depth):
    """A model that keeps requesting tools must not run forever.

    This is an availability property, not a cost one: the loop runs inside the
    API process, so an unbounded agent is a way for one request to occupy a
    worker indefinitely.
    """

    depth({"elevation_m": -10.0})

    model = patched(
        ScriptedModel(
            [
                _tool_call("get_seafloor_depth", {"latitude": 1.0, "longitude": 1.0}, f"c{i}")
                for i in range(agent.MAX_ITERATIONS + 5)
            ]
        )
    )

    result = await agent.answer("loop forever")

    assert len(model.seen) == agent.MAX_ITERATIONS
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_a_failing_tool_does_not_end_the_turn(patched, depth):
    """A raise inside a tool would kill the conversation; it must become text.

    The message also has to reach the model, because the recovery we want is
    "say it is unavailable" — which it can only do if it knows.
    """

    depth(RuntimeError("provider exploded"))

    model = patched(
        ScriptedModel(
            [
                _tool_call("get_seafloor_depth", {"latitude": 1.0, "longitude": 1.0}),
                AIMessage(content="That depth data is unavailable right now."),
            ]
        )
    )

    result = await agent.answer("depth?")

    assert "unavailable" in result["answer"].lower()
    assert result["observations"] == [], "a failed tool must not enter the ledger"
    assert any("provider exploded" in str(m.content) for m in model.seen[-1])


@pytest.mark.asyncio
async def test_tool_arguments_are_validated_before_a_provider_is_touched(monkeypatch):
    """The schema bounds are a guard, not documentation.

    A hallucinated longitude of 400 must fail in the tool layer rather than
    reaching a provider and being answered with something.
    """
    called = False

    async def fake(*, latitude: float, longitude: float):
        nonlocal called
        called = True
        return {"elevation_m": -1.0}

    monkeypatch.setattr("services.bathymetry.get_elevation", fake)

    ledger = Ledger()
    tool = {t.name: t for t in build_tools(ledger)}["get_seafloor_depth"]

    with pytest.raises(ValidationError):
        await tool.ainvoke({"latitude": 10.0, "longitude": 400.0})
    assert called is False


@pytest.mark.asyncio
async def test_history_is_replayed_and_bounded(patched):
    """Prior turns must reach the model, but only the recent ones."""
    model = patched(ScriptedModel([AIMessage(content="ok")]))

    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"}
        for i in range(30)
    ]
    await agent.answer("and now?", history)

    contents = [str(m.content) for m in model.seen[0]]
    assert "turn 29" in contents
    assert "turn 0" not in contents


def test_the_ledger_separates_conversations():
    """Two chats must not be able to launder each other's numbers."""
    first, second = Ledger(), Ledger()
    first.record("t", {}, {"value": 42.0})
    assert second.observations == []
    assert "42.0" in first.as_text()


@pytest.mark.asyncio
async def test_an_empty_question_is_rejected(patched):
    patched(ScriptedModel([AIMessage(content="hi")]))
    with pytest.raises(agent.ChatError):
        await agent.answer("   ")


def test_every_tool_declares_a_description_and_schema():
    """The description is the only thing the model reads to choose a tool.

    An undescribed tool is invisible in practice, and the failure is silent —
    the model simply never calls it.
    """
    tools = build_tools(Ledger())
    assert len(tools) == 9
    for tool in tools:
        assert tool.description and len(tool.description) > 30, tool.name
        assert tool.args_schema is not None, tool.name
