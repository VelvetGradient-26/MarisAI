"""The orchestrator loop, its bounds, and the grounding check.

No provider is contacted. The model is a scripted stand-in that emits the
tool-call shape `bind_tools` produces, which is what lets the loop's control
flow be tested at all — against a real provider these paths are nondeterministic
and only reachable by luck.

**Two loop levels since the multi-agent split**, and `_model()` is called
once per level: once for the top-level orchestrator, once more inside
`services.chat.orchestrator.run_specialist` for whichever specialist gets
delegated to. `patched` therefore takes a model *per `_model()` call, in
order* — a test that never delegates only needs one, a test that exercises a
real tool needs two (the top-level model that emits the delegate call, and
the specialist's own model that emits the tool call).
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
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


def _delegate_call(specialist: str, question: str, call_id: str = "d1") -> AIMessage:
    return _tool_call(f"delegate_to_{specialist}", {"question": question}, call_id)


@pytest.fixture
def patched(monkeypatch):
    """Install one model per `_model()` call, in order.

    Once the queue is exhausted, further calls (typically a specialist's sub-
    loop when a test only cares about the top level) get a trivial stand-in
    that answers "done" with no tool calls, so a delegate call that a test
    doesn't script for still terminates instead of hanging the sub-loop.
    """

    def install(*models: "ScriptedModel"):
        queue = list(models)

        def factory():
            return queue.pop(0) if queue else ScriptedModel([AIMessage(content="done")])

        monkeypatch.setattr(agent, "_model", factory)
        return models[0] if models else None

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
    """The whole point of the loop: a specialist's tool output reaches its own
    answer, and the orchestrator's final answer carries that figure through."""
    depth({"elevation_m": -1234.5, "source": "GEBCO_2021 via Ifremer ERDDAP"})

    top = ScriptedModel(
        [
            _delegate_call("geospatial_risk", "How deep is it at 10N 72E?"),
            AIMessage(content="The seafloor there is about 1234.5 m deep."),
        ]
    )
    specialist = ScriptedModel(
        [
            _tool_call("get_seafloor_depth", {"latitude": 10.0, "longitude": 72.0}),
            AIMessage(content="It's about 1234.5 m deep."),
        ]
    )
    patched(top, specialist)

    result = await agent.answer("How deep is it at 10N 72E?")

    assert "1234.5" in result["answer"]
    assert result["grounded"] is True
    assert result["observations"][0]["tool"] == "get_seafloor_depth"
    assert result["observations"][0]["agent"] == "geospatial_risk"
    assert "GEBCO_2021 via Ifremer ERDDAP" in result["sources"]
    # The tool result must actually have been fed back to the specialist that
    # called it, not merely recorded.
    assert any("1234.5" in str(m.content) for m in specialist.seen[-1])


@pytest.mark.asyncio
async def test_an_invented_number_is_reported_not_hidden(patched, depth):
    """A figure traceable to no tool result is the failure mode that matters.

    Not discarded — a conversation has no template to fall back to — but the
    caller is told, so a UI can mark it and a demo can be honest.
    """

    depth({"elevation_m": -1234.5, "source": "GEBCO"})

    top = ScriptedModel(
        [
            _delegate_call("geospatial_risk", "How deep is it?"),
            AIMessage(content="It is 1234.5 m deep and the water is 28.4 C."),
        ]
    )
    specialist = ScriptedModel(
        [
            _tool_call("get_seafloor_depth", {"latitude": 10.0, "longitude": 72.0}),
            AIMessage(content="It is 1234.5 m deep and the water is 28.4 C."),
        ]
    )
    patched(top, specialist)

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
async def test_numbers_from_tool_descriptions_are_not_flagged(patched):
    """Describing capabilities is not reporting a measurement.

    Found live (pre-multi-agent): "ranges of 24 h, 7 d, 30 d" flagged 30,
    which appears verbatim in a tool's own argument description. That tool
    now lives inside a specialist rather than on the top-level orchestrator,
    so this also pins that the permitted set still reaches every specialist
    tool's description, not just the three delegate tools the orchestrator
    calls directly — see `agent._all_specialist_tool_texts`.
    """
    patched(ScriptedModel([AIMessage(content="I can serve ranges like 7 d and 30 d.")]))

    result = await agent.answer("what ranges do you support?")

    assert result["grounded"] is True, result["unsupported_numbers"]


@pytest.mark.asyncio
async def test_schema_bounds_do_not_launder_a_fabricated_reading(patched):
    """The allowance stops at prose — validation bounds must stay out.

    Latitude is bounded at 90 and horizons at 365. Admitting the raw JSON
    schema would let "the water is 90 °C" pass as though a provider had
    reported it, which is the exact failure this check exists to catch.
    """
    patched(ScriptedModel([AIMessage(content="The water is 90 degrees and rising.")]))

    result = await agent.answer("how warm is it?")

    assert result["grounded"] is False
    assert "90" in result["unsupported_numbers"]


@pytest.mark.asyncio
async def test_the_loop_is_bounded(patched):
    """A model that keeps delegating must not run forever.

    This is an availability property, not a cost one: the loop runs inside the
    API process, so an unbounded orchestrator is a way for one request to
    occupy a worker indefinitely. Each delegate call still runs a full
    specialist sub-loop, which terminates immediately here (the default
    trivial stand-in `patched` installs once the queue is empty) — what's
    bounded is the *top-level* model's own call count.
    """

    top = ScriptedModel(
        [
            _delegate_call("geospatial_risk", "loop forever", f"c{i}")
            for i in range(agent.MAX_ITERATIONS + 5)
        ]
    )
    patched(top)

    result = await agent.answer("loop forever")

    assert len(top.seen) == agent.MAX_ITERATIONS
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_a_failing_tool_does_not_end_the_turn(patched, depth):
    """A raise inside a tool would kill the conversation; it must become text.

    The message also has to reach the specialist that called it, because the
    recovery we want is "say it is unavailable" — which it can only do if it
    knows.
    """

    depth(RuntimeError("provider exploded"))

    top = ScriptedModel(
        [
            _delegate_call("geospatial_risk", "depth?"),
            AIMessage(content="That depth data is unavailable right now."),
        ]
    )
    specialist = ScriptedModel(
        [
            _tool_call("get_seafloor_depth", {"latitude": 1.0, "longitude": 1.0}),
            AIMessage(content="That depth data is unavailable right now."),
        ]
    )
    patched(top, specialist)

    result = await agent.answer("depth?")

    assert "unavailable" in result["answer"].lower()
    assert result["observations"] == [], "a failed tool must not enter the ledger"
    assert any("provider exploded" in str(m.content) for m in specialist.seen[-1])


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


def test_the_ledger_tags_specialist_observations():
    """A delegated call's observation must say which specialist made it, so
    the streaming trace can group tool calls by agent."""
    ledger = Ledger()
    ledger.record("get_current_conditions", {}, {"ok": True}, agent="weather_safety")
    ledger.record("get_seafloor_depth", {}, {"ok": True})

    assert ledger.observations[0]["agent"] == "weather_safety"
    assert "agent" not in ledger.observations[1]


@pytest.mark.asyncio
async def test_get_documentation_is_called_directly_not_delegated(patched, monkeypatch):
    """get_documentation is bound at the top level alongside the delegate
    tools (see `agent.answer`), not behind a specialist — it is static
    platform self-knowledge, not a live measurement, the same reasoning that
    keeps the dataset catalog out of a tenth specialist tool. A single
    top-level model is therefore enough to exercise it; there is no
    specialist sub-loop to script a second model for."""
    from services import docs

    monkeypatch.setattr(
        docs,
        "search",
        lambda query, limit=3: [
            {
                "chapter": "Reading the map",
                "group": "Using the platform",
                "url": "/docs?c=map-reading",
                "snippet": "The map is a stack of layers...",
            }
        ],
    )

    top = ScriptedModel(
        [
            _tool_call("get_documentation", {"query": "how do I read the map"}),
            AIMessage(content="See /docs?c=map-reading for how the map's layers work."),
        ]
    )
    patched(top)

    result = await agent.answer("How do I read the map?")

    assert result["observations"][0]["tool"] == "get_documentation"
    # Only a specialist's own calls carry an `agent` tag (Ledger.record) —
    # this one is top-level, so it must not.
    assert "agent" not in result["observations"][0]
    assert "/docs?c=map-reading" in result["answer"]


@pytest.mark.asyncio
async def test_an_empty_question_is_rejected(patched):
    patched(ScriptedModel([AIMessage(content="hi")]))
    with pytest.raises(agent.ChatError):
        await agent.answer("   ")


@pytest.mark.asyncio
async def test_a_thousands_separator_does_not_fake_an_ungrounded_number(patched, depth):
    """"2,048 m" is one figure, not a "2" and an "048".

    Found live: the seafloor at 10N 72E is 2048 m, the model reported it as
    "about 2,048 m deep (roughly 6,700 ft)", and the checker split both grouped
    numbers into fragments that appear in no tool result — flagging a perfectly
    grounded answer. Any depth over a thousand metres reproduces it, which is
    most of the ocean.
    """
    depth({"elevation_m": -2048.0, "source": "GEBCO_2021 via Ifremer ERDDAP"})

    top = ScriptedModel(
        [
            _delegate_call("geospatial_risk", "How deep is it at 10N 72E?"),
            AIMessage(content="The seafloor there sits about 2,048 m deep."),
        ]
    )
    specialist = ScriptedModel(
        [
            _tool_call("get_seafloor_depth", {"latitude": 10.0, "longitude": 72.0}),
            AIMessage(content="About 2,048 m deep."),
        ]
    )
    patched(top, specialist)

    result = await agent.answer("How deep is it at 10N 72E?")

    assert result["unsupported_numbers"] == []
    assert result["grounded"] is True


@pytest.mark.asyncio
async def test_a_grouped_number_is_still_checked(patched, depth):
    """The fix must not become a way to launder an invented figure.

    Admitting the ungrouped spelling of every number is only safe if a grouped
    number that matches *nothing* still fails.
    """
    depth({"elevation_m": -2048.0, "source": "GEBCO_2021 via Ifremer ERDDAP"})

    top = ScriptedModel(
        [
            _delegate_call("geospatial_risk", "How deep is it at 10N 72E?"),
            AIMessage(content="The seafloor there sits about 9,876 m deep."),
        ]
    )
    specialist = ScriptedModel(
        [
            _tool_call("get_seafloor_depth", {"latitude": 10.0, "longitude": 72.0}),
            AIMessage(content="About 2,048 m deep."),
        ]
    )
    patched(top, specialist)

    result = await agent.answer("How deep is it at 10N 72E?")

    assert result["grounded"] is False
    assert "9,876" in result["unsupported_numbers"]


@pytest.mark.asyncio
async def test_a_refusal_despite_real_data_is_flagged(patched, depth):
    """The gap `_ungrounded_numbers` cannot cover: a live run (2026-08-24) had
    the orchestrator claim it "couldn't pull" a route after the specialist's
    tools had already succeeded. `grounded` stays true — a refusal states no
    numbers — so this needs its own check."""
    depth({"elevation_m": -1234.5, "source": "GEBCO_2021 via Ifremer ERDDAP"})

    top = ScriptedModel(
        [
            _delegate_call("geospatial_risk", "How deep is it at 10N 72E?"),
            AIMessage(
                content=(
                    "I'm sorry, but I couldn't pull the depth data for that "
                    "location right now."
                )
            ),
        ]
    )
    specialist = ScriptedModel(
        [
            _tool_call("get_seafloor_depth", {"latitude": 10.0, "longitude": 72.0}),
            AIMessage(content="About 1234.5 m deep."),
        ]
    )
    patched(top, specialist)

    result = await agent.answer("How deep is it at 10N 72E?")

    assert result["grounded"] is True, "a refusal states no numbers, so this stays true"
    assert result["possible_false_refusal"] is True


@pytest.mark.asyncio
async def test_a_curly_apostrophe_refusal_is_still_caught(patched, depth):
    """A live re-run of the exact case above wrote "couldn't" with a curly
    Unicode apostrophe (U+2019, what "I’m sorry, but I couldn’t retrieve..."
    actually contains) rather than a straight one — every provider does this
    routinely, and a straight-quote-only pattern missed it outright."""
    depth({"elevation_m": -1234.5, "source": "GEBCO_2021 via Ifremer ERDDAP"})

    top = ScriptedModel(
        [
            _delegate_call("geospatial_risk", "How deep is it at 10N 72E?"),
            AIMessage(content="I’m sorry, but I couldn’t retrieve the depth data."),
        ]
    )
    specialist = ScriptedModel(
        [
            _tool_call("get_seafloor_depth", {"latitude": 10.0, "longitude": 72.0}),
            AIMessage(content="About 1234.5 m deep."),
        ]
    )
    patched(top, specialist)

    result = await agent.answer("How deep is it at 10N 72E?")

    assert result["possible_false_refusal"] is True


@pytest.mark.asyncio
async def test_a_genuine_refusal_with_no_data_is_not_flagged(patched):
    """An empty ledger means there was nothing to ignore — this is an honest
    "I don't have that", not the failure the check exists to catch."""
    top = ScriptedModel([AIMessage(content="I'm sorry, I couldn't find that information.")])
    patched(top)

    result = await agent.answer("What is the meaning of life?")

    assert result["possible_false_refusal"] is False


@pytest.mark.asyncio
async def test_a_partial_failure_that_still_reports_a_figure_is_not_flagged(patched, depth):
    """An answer that honestly reports one real number is not the shape of
    the observed bug, even if it also apologises for a different failure."""
    depth({"elevation_m": -1234.5, "source": "GEBCO_2021 via Ifremer ERDDAP"})

    top = ScriptedModel(
        [
            _delegate_call("geospatial_risk", "How deep is it at 10N 72E?"),
            AIMessage(
                content=(
                    "The seafloor there is about 1234.5 m deep. I couldn't "
                    "get the boundary proximity for that point, though."
                )
            ),
        ]
    )
    specialist = ScriptedModel(
        [
            _tool_call("get_seafloor_depth", {"latitude": 10.0, "longitude": 72.0}),
            AIMessage(content="About 1234.5 m deep."),
        ]
    )
    patched(top, specialist)

    result = await agent.answer("How deep is it at 10N 72E?")

    assert result["possible_false_refusal"] is False


@pytest.fixture
def conditions(monkeypatch):
    """Stand in for the Open-Meteo realtime-conditions provider `_current_
    conditions` calls, the same lazy-import-patch shape `depth` above uses."""

    def install(result: dict) -> None:
        async def fake(*, latitude: float, longitude: float):
            return result

        monkeypatch.setattr("services.openmeteo.get_realtime_ocean_conditions", fake)

    return install


@pytest.fixture
def cyclones(monkeypatch):
    """Stand in for the GDACS cyclone-check provider `_cyclone_alerts` calls."""

    def install(result: dict) -> None:
        async def fake(latitude: float, longitude: float, radius_km: float):
            return result

        monkeypatch.setattr("services.cyclones.check_point", fake)

    return install


@pytest.fixture
def web_search_result(monkeypatch):
    """Stand in for the Tavily-backed web_search tool."""

    def install(result: dict) -> None:
        async def fake(query: str, max_results: int = 5):
            return result

        monkeypatch.setattr("services.web_search.search", fake)

    return install


@pytest.mark.asyncio
async def test_external_research_is_a_real_delegate_and_feeds_grounding(patched, web_search_result):
    """The fourth specialist: a figure from a web search result reaches the
    final answer and is recognised as grounded, exactly as a live-data figure
    from any other specialist is — sihtodo.md item 4's own requirement that
    these tools feed the existing grounding mechanism rather than bypass it.
    """
    web_search_result(
        {
            "query": "why is the arabian sea warm this week",
            "results": [
                {
                    "title": "Arabian Sea sees unusual warmth",
                    "url": "https://news.example.com/arabian-sea",
                    "snippet": "Sea surface temperatures are running 1.8 C above average.",
                    "published_date": "2026-08-20",
                    "source": "news.example.com",
                }
            ],
            "result_count": 1,
            "source": "Tavily web search",
        }
    )

    top = ScriptedModel(
        [
            _delegate_call("external_research", "Why is the Arabian Sea unusually warm this week?"),
            AIMessage(
                content=(
                    "According to news.example.com (2026-08-20), SST there is "
                    "running 1.8 C above average this week."
                )
            ),
        ]
    )
    specialist = ScriptedModel(
        [
            _tool_call("web_search", {"query": "why is the arabian sea warm this week"}),
            AIMessage(content="It's running 1.8 C above average per news.example.com."),
        ]
    )
    patched(top, specialist)

    result = await agent.answer("Why is the Arabian Sea unusually warm this week?")

    assert result["grounded"] is True, result["unsupported_numbers"]
    assert result["observations"][0]["tool"] == "web_search"
    assert result["observations"][0]["agent"] == "external_research"
    assert "news.example.com" in result["sources"]


@pytest.mark.asyncio
async def test_a_glossary_term_kept_in_english_is_not_flagged(patched, conditions):
    """A Hindi answer that keeps "SST" in English, exactly as the prompt asks,
    is not a gap — the check must not cry wolf on compliant behaviour."""
    conditions({"current": {"sea_surface_temperature": 28.4}, "units": {"sea_surface_temperature": "C"}})

    top = ScriptedModel(
        [
            _delegate_call("weather_safety", "Kochi ke paas SST kya hai?"),
            AIMessage(content="Kochi ke pass samudra ka SST 28.4°C hai."),
        ]
    )
    specialist = ScriptedModel(
        [
            _tool_call("get_current_conditions", {"latitude": 10.0, "longitude": 76.0}),
            AIMessage(content="SST 28.4°C hai."),
        ]
    )
    patched(top, specialist)

    result = await agent.answer("Kochi ke paas SST kya hai?")

    assert result["glossary_gaps"] == []


@pytest.mark.asyncio
async def test_a_dropped_glossary_term_is_flagged(patched, conditions):
    """The same SST data, but the top-level answer never writes "SST" (or
    "sea surface temperature") in English anywhere — only a vernacular
    paraphrase. That is exactly the mistranslation risk the glossary guards
    against, and it must be reported, not hidden."""
    conditions({"current": {"sea_surface_temperature": 28.4}, "units": {"sea_surface_temperature": "C"}})

    top = ScriptedModel(
        [
            _delegate_call("weather_safety", "Kochi ke paas SST kya hai?"),
            AIMessage(content="कोच्चि के पास समुद्र का तापमान 28.4 डिग्री है।"),
        ]
    )
    specialist = ScriptedModel(
        [
            _tool_call("get_current_conditions", {"latitude": 10.0, "longitude": 76.0}),
            AIMessage(content="28.4°C hai."),
        ]
    )
    patched(top, specialist)

    result = await agent.answer("Kochi ke paas SST kya hai?")

    assert result["glossary_gaps"] == ["SST"]


@pytest.mark.asyncio
async def test_an_english_answer_is_never_flagged_for_glossary(patched, conditions):
    """The script gate, not term presence, is what does the work: an English
    answer that never once writes "SST" is still not a glossary gap, because
    there was no non-English translation to check fidelity on."""
    conditions({"current": {"sea_surface_temperature": 28.4}, "units": {"sea_surface_temperature": "C"}})

    top = ScriptedModel(
        [
            _delegate_call("weather_safety", "What's the water temperature near Kochi?"),
            AIMessage(content="The water temperature near Kochi is 28.4°C."),
        ]
    )
    specialist = ScriptedModel(
        [
            _tool_call("get_current_conditions", {"latitude": 10.0, "longitude": 76.0}),
            AIMessage(content="28.4°C."),
        ]
    )
    patched(top, specialist)

    result = await agent.answer("What's the water temperature near Kochi?")

    assert result["glossary_gaps"] == []


@pytest.mark.asyncio
async def test_a_second_glossary_term_is_flagged(patched, cyclones):
    """The alias table beyond SST: a cyclone-touching turn answered entirely
    in Tamil, with no English "cyclone" anywhere, flags "cyclone". It also
    flags "marine advisory" — the tool is literally named
    `get_cyclone_alerts`, so its own name touches that concept's "alert"
    alias too, and the Tamil answer never writes "alert" either. That is the
    coarser-proxy trade-off the glossary table's own comment documents, not a
    bug: both concepts genuinely were touched and neither was kept in
    English."""
    cyclones(
        {
            "active_cyclones_worldwide": 2,
            "nearest": None,
            "within_watch_radius": False,
            "watch_radius_km": 300,
        }
    )

    top = ScriptedModel(
        [
            _delegate_call("weather_safety", "Any storms near Chennai?"),
            AIMessage(content="சென்னைக்கு அருகில் இப்போது எந்த புயலும் இல்லை."),
        ]
    )
    specialist = ScriptedModel(
        [
            _tool_call("get_cyclone_alerts", {"latitude": 13.0, "longitude": 80.0, "radius_km": 500}),
            AIMessage(content="No active storms nearby."),
        ]
    )
    patched(top, specialist)

    result = await agent.answer("Any storms near Chennai?")

    assert result["glossary_gaps"] == ["cyclone", "marine advisory"]


class ScriptedStreamModel(ScriptedModel):
    """`ScriptedModel` that also answers `astream`.

    Each queued reply is emitted as one chunk per whitespace-delimited word, so
    a test can assert on ordering and on reassembly rather than on a single
    all-at-once yield — which would pass even if the endpoint had quietly
    stopped streaming.
    """

    async def astream(self, messages):
        self.seen.append(list(messages))
        reply = self.replies.pop(0) if self.replies else AIMessage(content="done")

        if getattr(reply, "tool_calls", None):
            # A tool-calling turn carries no text, matching real providers.
            yield AIMessageChunk(content="", tool_calls=reply.tool_calls)
            return

        words = str(reply.content).split(" ")
        for index, word in enumerate(words):
            yield AIMessageChunk(content=word if index == 0 else f" {word}")


async def _collect(question: str) -> list[dict]:
    return [event async for event in agent.answer_stream(question)]


@pytest.mark.asyncio
async def test_the_stream_reports_tools_before_the_answer(patched, depth):
    """The reason the streaming endpoint exists.

    A turn that fetches ocean data takes tens of seconds, and the point of
    streaming it is that the user sees *what is being fetched* while they
    wait — now labelled with which specialist is doing the fetching. If a
    `tool` event could arrive after the prose it justifies, the feature would
    be pointless — so the ordering is asserted, not assumed. Only the
    top-level orchestrator streams tokens (`astream`); a specialist's own
    sub-loop always uses `ainvoke`, so only the top model needs to be a
    `ScriptedStreamModel`.
    """
    depth({"elevation_m": -1234.5, "source": "GEBCO_2021 via Ifremer ERDDAP"})
    top = ScriptedStreamModel(
        [
            _delegate_call("geospatial_risk", "How deep is it at 10N 72E?"),
            AIMessage(content="The seafloor there is about 1234.5 m deep."),
        ]
    )
    specialist = ScriptedModel(
        [
            _tool_call("get_seafloor_depth", {"latitude": 10.0, "longitude": 72.0}),
            AIMessage(content="About 1234.5 m deep."),
        ]
    )
    patched(top, specialist)

    events = await _collect("How deep is it at 10N 72E?")
    kinds = [event["type"] for event in events]

    assert kinds[0] == "delegate", "the delegation decision precedes the specialist running"
    assert events[0]["agent"] == "geospatial_risk"
    assert kinds[1] == "tool"
    assert events[1]["agent"] == "geospatial_risk"
    assert kinds.index("delegate") < kinds.index("tool") < kinds.index("delta")
    assert kinds[-1] == "meta", "meta must be terminal — it carries the grounding verdict"
    assert kinds.count("meta") == 1


@pytest.mark.asyncio
async def test_the_delegate_event_carries_the_orchestrators_own_question(patched, depth):
    """The visible 'why' behind a delegation.

    The orchestrator's reasoning for choosing a specialist is not a separate
    reasoning step — it is the `question` argument it hands to the delegate
    tool, produced before the specialist ever runs. Surfacing it is what turns
    "geospatial_risk called get_seafloor_depth" into "asked geospatial_risk:
    how deep is it at 10N 72E, which then called get_seafloor_depth".
    """
    depth({"elevation_m": -1234.5, "source": "GEBCO_2021 via Ifremer ERDDAP"})
    top = ScriptedStreamModel(
        [
            _delegate_call("geospatial_risk", "How deep is it at 10N 72E?"),
            AIMessage(content="The seafloor there is about 1234.5 m deep."),
        ]
    )
    specialist = ScriptedModel(
        [
            _tool_call("get_seafloor_depth", {"latitude": 10.0, "longitude": 72.0}),
            AIMessage(content="About 1234.5 m deep."),
        ]
    )
    patched(top, specialist)

    events = await _collect("How deep is it at 10N 72E?")
    delegate_events = [event for event in events if event["type"] == "delegate"]

    assert delegate_events == [
        {"type": "delegate", "agent": "geospatial_risk", "question": "How deep is it at 10N 72E?"}
    ]
    assert events[-1]["delegations"] == [
        {"agent": "geospatial_risk", "question": "How deep is it at 10N 72E?"}
    ]


@pytest.mark.asyncio
async def test_the_streamed_text_reassembles_into_the_final_answer(patched, depth):
    """The deltas and `meta.answer` must not be able to disagree.

    They are produced by different code paths — one accumulates provider chunks,
    the other re-reads the message list — so a change to either could leave the
    text a user watched arrive differing from the text that was graded for
    grounding and written to the transcript.
    """
    depth({"elevation_m": -1234.5, "source": "GEBCO_2021 via Ifremer ERDDAP"})
    top = ScriptedStreamModel(
        [
            _delegate_call("geospatial_risk", "How deep is it at 10N 72E?"),
            AIMessage(content="The seafloor there is about 1234.5 m deep."),
        ]
    )
    specialist = ScriptedModel(
        [
            _tool_call("get_seafloor_depth", {"latitude": 10.0, "longitude": 72.0}),
            AIMessage(content="About 1234.5 m deep."),
        ]
    )
    patched(top, specialist)

    events = await _collect("How deep is it at 10N 72E?")
    streamed = "".join(e["text"] for e in events if e["type"] == "delta")
    meta = events[-1]

    assert streamed.strip() == meta["answer"].strip()
    assert meta["grounded"] is True
    assert meta["observations"][0]["tool"] == "get_seafloor_depth"
    assert meta["observations"][0]["agent"] == "geospatial_risk"


@pytest.mark.asyncio
async def test_grounding_is_only_reported_at_the_end(patched, depth):
    """`grounded` is computed from the finished text, so it cannot ride a delta.

    A client that showed a "verified" badge mid-stream would be asserting a
    check that had not run. Keeping the verdict exclusively on the terminal
    event is what makes that impossible rather than merely discouraged.
    """
    depth({"elevation_m": -1234.5, "source": "GEBCO_2021 via Ifremer ERDDAP"})
    top = ScriptedStreamModel(
        [
            _delegate_call("geospatial_risk", "How deep is it at 10N 72E?"),
            # 4321.0 appears in no tool result.
            AIMessage(content="It is 4321.0 m deep."),
        ]
    )
    specialist = ScriptedModel(
        [
            _tool_call("get_seafloor_depth", {"latitude": 10.0, "longitude": 72.0}),
            AIMessage(content="About 1234.5 m deep."),
        ]
    )
    patched(top, specialist)

    events = await _collect("How deep is it at 10N 72E?")

    for event in events[:-1]:
        assert "grounded" not in event
    assert events[-1]["grounded"] is False
    assert "4321.0" in events[-1]["unsupported_numbers"]


def test_every_tool_declares_a_description_and_schema():
    """The description is the only thing the model reads to choose a tool.

    An undescribed tool is invisible in practice, and the failure is silent —
    the model simply never calls it. 23 = the original 9, the three PS2
    additions (find_fishing_zones, check_geofence, plan_safe_route), the
    two cyclone/severe-weather additions (get_cyclone_alerts,
    get_severe_weather_alerts), get_documentation (platform self-knowledge,
    called directly rather than through a specialist), the sihtodo.md
    items 7/10 additions (analyze_variable_correlation, assess_marine_risk),
    the sihtodo.md item 4 controlled-internet additions (web_search,
    fetch_webpage, search_scientific_literature), the sihtodo.md item 6
    addition (get_tide_level), the ARGO float profile addition
    (get_argo_profile), and the drift trajectory addition
    (plan_drift_trajectory).
    """
    tools = build_tools(Ledger())
    assert len(tools) == 23
    for tool in tools:
        assert tool.description and len(tool.description) > 30, tool.name
        assert tool.args_schema is not None, tool.name


def test_every_specialist_tool_name_is_real():
    """`services.chat.specialists.SPECIALISTS` names tools by string — a typo
    there would silently vanish a tool from every specialist rather than
    raising, since `build_tools` only looks up what it's given."""
    from services.chat.specialists import SPECIALISTS
    from services.chat.tools import ALL_TOOL_NAMES

    for specialist in SPECIALISTS.values():
        for name in specialist.tool_names:
            assert name in ALL_TOOL_NAMES, f"{specialist.name} references unknown tool {name}"


@pytest.mark.asyncio
async def test_an_attached_image_reaches_the_model_as_a_multimodal_message(patched):
    """`image` becomes a multimodal `HumanMessage` content list — the shape
    LangChain standardised across `ChatOpenAI`/`ChatGoogleGenerativeAI` (and
    thus the OpenAI-compatible Ollama path too, see `agent._model`) — rather
    than being silently dropped or concatenated into the text."""
    model = ScriptedModel([AIMessage(content="That looks like a bloom patch.")])
    patched(model)

    data_url = "data:image/png;base64,aGVsbG8="
    reply = await agent.answer("what is this?", image=data_url)

    assert reply["answer"] == "That looks like a bloom patch."
    last_message = model.seen[0][-1]
    assert last_message.content == [
        {"type": "text", "text": "what is this?"},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]


@pytest.mark.asyncio
async def test_no_image_stays_a_plain_text_message(patched):
    """The common case is unchanged: no image means the existing plain-string
    `HumanMessage`, not a single-element multimodal list."""
    model = ScriptedModel([AIMessage(content="It's warm today.")])
    patched(model)

    await agent.answer("how warm is it?")

    last_message = model.seen[0][-1]
    assert last_message.content == "how warm is it?"


def test_a_malformed_image_data_url_is_rejected_at_the_request_boundary():
    """The router validates the `data:` URL shape (and a size cap) before the
    model is ever touched — see `routers/chat.py::ChatRequest._validate_image`."""
    from routers.chat import ChatRequest

    with pytest.raises(ValidationError):
        ChatRequest(
            message="hi",
            client_id="test-client-00000000",
            image="not-a-data-url",
        )

    with pytest.raises(ValidationError):
        ChatRequest(
            message="hi",
            client_id="test-client-00000000",
            image="data:image/gif;base64,aGVsbG8=",
        )

    # A well-formed one passes straight through.
    request = ChatRequest(
        message="hi",
        client_id="test-client-00000000",
        image="data:image/png;base64,aGVsbG8=",
    )
    assert request.image == "data:image/png;base64,aGVsbG8="
