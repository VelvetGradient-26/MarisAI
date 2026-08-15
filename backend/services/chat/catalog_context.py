"""The dataset catalog, rendered into the assistant's system prompt.

TODO.md §6 settles the design and this module is the whole implementation of
it: the catalog is **~36 variables across 14 datasets**, which fits in a single
prompt. Standing up a vector database to retrieve 36 records is the trap that
section names, and "RAG over ocean data" is a category error besides — you do
not retrieve a grid spacing, you look it up.

So the model is simply *told*, once, what the platform holds. That closes the
gap where "which variables cover 2022 at 0.083 degrees?" was unanswerable: the
facts existed in `download/catalog.py` and were reachable only by the
downloader's size estimator.

Two decisions worth keeping:

* **Static facts here, live facts in the tool.** This block carries what only
  changes when someone edits the registry — dataset, grid spacing, cadence,
  coverage start, licence. It deliberately does *not* say which variables have
  a trained forecast, because that changes when a training run finishes and
  the system prompt is built once at import. `list_available_variables`
  already answers that live, and two answers that can disagree is worse than
  one answer that is always right.
* **Grounding covers this for free, and only because of where it goes.**
  `agent._ungrounded_numbers` permits every figure the model was *shown*,
  which explicitly includes the system prompt — so "0.083 deg" quoted from
  here is grounded, exactly as the horizons quoted from tool descriptions
  already were. Putting the same text anywhere else (a preamble injected per
  turn, say) would make every resolution the assistant states light up as
  unverifiable, which is the cry-wolf failure the checker is written to avoid.
  If this text ever moves, it has to move into `shown` with it.
"""

from __future__ import annotations

from services.download import catalog, registry


def _cadence(steps_per_day: float, *, time_varying: bool) -> str:
    if not time_varying or steps_per_day == 0:
        return "time-invariant"
    if steps_per_day >= 24:
        return "hourly"
    if steps_per_day > 1:
        return f"{round(24 / steps_per_day)}-hourly"
    if steps_per_day == 1:
        return "daily"
    return f"every {round(1 / steps_per_day)} days"


def _licence_short(licence: str) -> str:
    """First clause only — the full citation is for exports, not for a prompt."""
    return licence.split("—")[0].split("(")[0].strip().rstrip(",.")


def build() -> str:
    """The catalog as prompt text."""
    by_provider: dict[str, list[str]] = {}
    for code, info in registry.VARIABLE_REGISTRY.items():
        if info.provider is None or not info.available:
            continue
        by_provider.setdefault(info.provider, []).append(code)

    lines: list[str] = []
    for key, spec in sorted(catalog.PROVIDERS.items()):
        variables = sorted(by_provider.get(key, []))
        if not variables:
            continue
        coverage = (
            f"from {spec.coverage_start.isoformat()}"
            if spec.coverage_start is not None
            else "no time bound"
        )
        # The provider key leads, because `source_label` is the *product* and
        # several datasets share one: the five biogeochemistry datasets are all
        # GLOBAL_ANALYSISFORECAST_BGC_001_028 and the four physics ones all
        # PHY_001_024. They are separate providers precisely because their
        # coverage windows and cadences differ (optics starts two years later),
        # so rendering them under one repeated name makes five correct rows
        # look like one row duplicated five times.
        lines.append(
            f"- {key} ({spec.source_label}): {spec.grid_spacing_deg} deg grid, "
            f"{_cadence(spec.steps_per_day, time_varying=spec.time_varying)}, "
            f"{coverage}. Licence: {_licence_short(spec.licence)}. "
            f"Serves: {', '.join(variables)}."
        )

    unavailable = sorted(
        code for code, info in registry.VARIABLE_REGISTRY.items() if not info.available
    )

    body = "\n".join(lines)
    footer = ""
    if unavailable:
        # Named rather than silently absent: "we do not carry that" is a real
        # answer and a much better one than a failed tool call.
        footer = (
            f"\n\nRequested by the spec but not served, because no global source "
            f"exists: {', '.join(unavailable)}. Say so plainly if asked."
        )

    return (
        "Datasets you draw on. These are the platform's own sources — you may "
        "quote resolutions, cadences, coverage windows and licences from this "
        "list directly, without a tool call, because it is not a measurement. "
        "Whether a variable has a *trained forecast* is a separate question "
        "that changes as models are trained: call list_available_variables for "
        "that, never this list.\n\n" + body + footer
    )


# Built once at import. The inputs are module-level registries that only change
# with a code edit, so rebuilding per turn would burn tokens of work to produce
# an identical string.
CATALOG_PROMPT = build()
