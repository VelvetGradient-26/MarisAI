"""services/chat/orchestrator.py: the specialist sub-loop in isolation.

`tests/test_chat.py` already exercises delegation end-to-end through
`agent.answer`/`agent.answer_stream`; this file tests `run_specialist` and
`build_delegate_tools` directly, without going through the top-level loop.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from services.chat.orchestrator import SUB_MAX_ITERATIONS, build_delegate_tools, run_specialist
from services.chat.tools import Ledger


class ScriptedModel:
    def __init__(self, replies: list[AIMessage]) -> None:
        self.replies = list(replies)
        self.seen: list[list] = []

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.seen.append(list(messages))
        return self.replies.pop(0) if self.replies else AIMessage(content="done")


def _tool_call(name: str, args: dict, call_id: str = "c1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


@pytest.mark.asyncio
async def test_a_specialist_calls_only_its_own_tools_and_reports_the_result(monkeypatch):
    async def fake_elevation(*, latitude: float, longitude: float):
        return {"elevation_m": -500.0, "source": "test"}

    monkeypatch.setattr("services.bathymetry.get_elevation", fake_elevation)

    model = ScriptedModel(
        [
            _tool_call("get_seafloor_depth", {"latitude": 1.0, "longitude": 1.0}),
            AIMessage(content="The seafloor is 500.0 m deep."),
        ]
    )
    ledger = Ledger()

    result = await run_specialist(
        "geospatial_risk", "how deep is it?", ledger, [], lambda: model
    )

    assert "500.0" in result.text
    assert result.truncated is False
    assert ledger.observations[0]["tool"] == "get_seafloor_depth"
    assert ledger.observations[0]["agent"] == "geospatial_risk"


@pytest.mark.asyncio
async def test_a_specialist_cannot_reach_another_specialists_tool():
    """`weather_safety` has no seafloor-depth tool — a model hallucinating
    that name must get "no such tool", not a real call."""
    model = ScriptedModel(
        [
            _tool_call("get_seafloor_depth", {"latitude": 1.0, "longitude": 1.0}),
            AIMessage(content="I can't check that."),
        ]
    )
    ledger = Ledger()

    result = await run_specialist("weather_safety", "how deep?", ledger, [], lambda: model)

    assert ledger.observations == []
    assert "No such tool" in str(model.seen[-1][-1].content)


@pytest.mark.asyncio
async def test_external_research_specialist_calls_web_search(monkeypatch):
    async def fake_search(query: str, max_results: int):
        return {
            "query": query,
            "results": [
                {
                    "title": "Arabian Sea marine heatwave",
                    "url": "https://example.org/article",
                    "snippet": "Unusually warm water this week.",
                    "published_date": "2026-08-20",
                }
            ],
            "result_count": 1,
            "source": "Tavily web search",
        }

    monkeypatch.setattr("services.web_search.search", fake_search)

    model = ScriptedModel(
        [
            _tool_call("web_search", {"query": "arabian sea warming", "max_results": 5}),
            AIMessage(
                content="Per example.org, the Arabian Sea has seen unusually warm water this week."
            ),
        ]
    )
    ledger = Ledger()

    result = await run_specialist(
        "external_research", "why is the water warm", ledger, [], lambda: model
    )

    assert "example.org" in result.text
    assert ledger.observations[0]["tool"] == "web_search"
    assert ledger.observations[0]["agent"] == "external_research"
    assert ledger.observations[0]["result"]["results"][0]["url"] == "https://example.org/article"


@pytest.mark.asyncio
async def test_external_research_specialist_has_no_ocean_data_tools():
    """`external_research` must not be able to call an ocean-data tool even
    if the model hallucinates the name — its tool set is web-only."""
    model = ScriptedModel(
        [
            _tool_call("get_current_conditions", {"latitude": 1.0, "longitude": 1.0}),
            AIMessage(content="I can't check live conditions myself."),
        ]
    )
    ledger = Ledger()

    await run_specialist("external_research", "is it warm there", ledger, [], lambda: model)

    assert ledger.observations == []
    assert "No such tool" in str(model.seen[-1][-1].content)


@pytest.mark.asyncio
async def test_a_specialist_loop_is_bounded():
    model = ScriptedModel(
        [
            _tool_call("get_current_conditions", {"latitude": 1.0, "longitude": 1.0}, f"c{i}")
            for i in range(SUB_MAX_ITERATIONS + 5)
        ]
    )
    ledger = Ledger()

    result = await run_specialist("weather_safety", "loop", ledger, [], lambda: model)

    assert len(model.seen) == SUB_MAX_ITERATIONS
    assert result.truncated is True


@pytest.mark.asyncio
async def test_delegate_tools_are_one_per_specialist():
    ledger = Ledger()
    delegates = build_delegate_tools(ledger, [], lambda: ScriptedModel([AIMessage(content="done")]))

    names = {tool.name for tool in delegates}
    assert names == {
        "delegate_to_ocean_analytics",
        "delegate_to_weather_safety",
        "delegate_to_geospatial_risk",
        "delegate_to_external_research",
    }
    for tool in delegates:
        assert tool.description
