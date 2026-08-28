"""The catalog in the prompt must be complete, honest, and not trip grounding.

TODO.md §6 chose prompt-stuffing over a vector store for the 36-record data
catalog. Two things then have to hold, and neither is obvious from reading the
prompt text:

* **It must be derived, not transcribed.** A hand-written list of datasets in
  a prompt is a fourth place the truth lives, and it drifts silently — the
  model would state a resolution the downloader no longer uses and sound
  entirely confident. These tests fail if the prompt stops matching the
  registry.
* **It must not make the grounding checker cry wolf.** `_ungrounded_numbers`
  flags figures no tool returned, and the catalog is full of figures. It is
  safe only because the block lives inside `_SYSTEM_PROMPT`, which both
  `shown` assemblies list by name. That is a load-bearing placement, not a
  stylistic one, so it is pinned here.
"""

from __future__ import annotations

from services.chat import agent, catalog_context
from services.chat.tools import Ledger
from services.download import catalog, registry


def test_every_served_dataset_appears():
    prompt = catalog_context.CATALOG_PROMPT

    expected = {
        info.provider
        for info in registry.VARIABLE_REGISTRY.values()
        if info.provider is not None and info.available
    }
    for key in expected:
        assert key in prompt, f"{key} missing from the catalog prompt"


def test_datasets_sharing_a_product_are_distinguishable():
    """Five BGC datasets share one product name and differ in coverage.

    Rendering them under the repeated `source_label` alone made five correct
    rows read as one row duplicated five times.
    """
    prompt = catalog_context.CATALOG_PROMPT

    assert catalog.PROVIDER_COPERNICUS_BGC_OPTICS in prompt
    assert catalog.PROVIDER_COPERNICUS_BGC_NUT in prompt
    # Optics genuinely starts later than the rest of the suite; if the two are
    # not separable the model cannot answer a coverage question correctly.
    optics_line = next(
        line
        for line in prompt.splitlines()
        if catalog.PROVIDER_COPERNICUS_BGC_OPTICS in line
    )
    nut_line = next(
        line
        for line in prompt.splitlines()
        if catalog.PROVIDER_COPERNICUS_BGC_NUT in line
    )
    assert "2023-11-15" in optics_line
    assert "2021-11-01" in nut_line


def test_resolution_and_cadence_come_from_the_catalog():
    prompt = catalog_context.CATALOG_PROMPT

    physics = catalog.PROVIDERS[catalog.PROVIDER_COPERNICUS_PHYSICS]
    line = next(
        line
        for line in prompt.splitlines()
        if catalog.PROVIDER_COPERNICUS_PHYSICS in line
    )
    assert str(physics.grid_spacing_deg) in line
    assert "hourly" in line


def test_waves_are_three_hourly_not_daily():
    """Assuming hourly overstates a wave request threefold; 'daily' understates it."""
    line = next(
        line
        for line in catalog_context.CATALOG_PROMPT.splitlines()
        if catalog.PROVIDER_COPERNICUS_WAVES in line
    )
    assert "3-hourly" in line


def test_unserved_variables_are_named_rather_than_absent():
    """'We do not carry that' beats a failed tool call."""
    prompt = catalog_context.CATALOG_PROMPT
    assert "tidal_height" in prompt
    assert "ammonium" in prompt


def test_the_prompt_defers_trained_forecasts_to_the_live_tool():
    """Static text must not answer a question that changes when training runs."""
    assert "list_available_variables" in catalog_context.CATALOG_PROMPT


def test_catalog_is_inside_the_system_prompt():
    """The placement the grounding checker depends on."""
    assert catalog_context.CATALOG_PROMPT in agent._SYSTEM_PROMPT


def test_quoting_a_catalog_resolution_is_not_flagged_as_ungrounded():
    """The whole reason placement matters.

    A user asking "what resolution is your SST?" gets an answer containing
    0.083 — a figure no tool returned. Before the catalog was in the prompt
    the model had no way to answer at all; the failure mode being pinned here
    is the *next* one, where someone moves this text out of `_SYSTEM_PROMPT`
    and every resolution the assistant states starts lighting up the banner.
    """
    ledger = Ledger()
    # A coverage year rather than a resolution: `_renderings` maps 0.083 onto
    # "0", which `_IGNORED` already admits, so a resolution would pass this
    # test for the wrong reason and prove nothing.
    answer = "The sea-level product covers from 2024 onward."

    # `shown` as the agent assembles it: the system prompt is part of what the
    # model was legitimately given.
    assert agent._ungrounded_numbers(answer, ledger, agent._SYSTEM_PROMPT) == []

    # And without it, the same sentence is correctly unverifiable — proving the
    # assertion above is actually testing something.
    assert agent._ungrounded_numbers(answer, ledger, "") != []


def test_a_product_id_does_not_launder_numbers_into_the_allowed_set():
    """The regression adding the catalog introduced, now pinned.

    `GLOBAL_ANALYSISFORECAST_BGC_001_028` read naively contributes "28" to the
    permitted set, which let a fabricated "the water is 28.4 C" trace back to a
    product code. The banner kept working and simply stopped firing — the
    worst way for a safety check to fail.
    """
    ledger = Ledger()
    shown = "Datasets: GLOBAL_ANALYSISFORECAST_BGC_001_028, WIND_GLO_PHY_L4_NRT_012_004"

    assert agent._ungrounded_numbers("The water is 28.4 C.", ledger, shown) == ["28.4"]
    # Whole-number form too: "28" must not be admitted by "_028".
    assert agent._ungrounded_numbers("It is 28 C.", ledger, shown) == ["28"]


def test_quoting_a_dataset_id_is_not_called_a_fabrication():
    """The other side of the same fix.

    A model naming the product it drew on is being *more* transparent, not
    less, and must not be accused of inventing "028".
    """
    ledger = Ledger()
    answer = "That comes from GLOBAL_ANALYSISFORECAST_BGC_001_028."
    assert agent._ungrounded_numbers(answer, ledger, agent._SYSTEM_PROMPT) == []
