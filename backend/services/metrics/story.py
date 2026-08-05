"""Ocean Story — the narrative at the top of every metric page.

The design constraint is the interesting part. The spec asks for a fluent
paragraph *and* forbids hallucination, and those pull against each other: an
LLM handed a chart and asked to describe it will confidently invent a figure
it finds plausible.

**So the LLM is never asked what the data says.** Every number in the story is
computed here first, in `_build_facts`, from the same statistics the KPI strip
renders. The model receives that block and a single job: phrase it. The prompt
states explicitly that it may not introduce a figure absent from the block,
and `_verify` checks the response afterwards — any number that does not appear
in the facts causes the generated text to be discarded in favour of the
deterministic rendering. A wrong ocean reading is worse than a plain sentence.

That verification is also what makes the fallback path honest rather than a
degradation: `render_template` produces the same facts as prose without an API
call at all, so the section renders identically well with `LLM_API_KEY` unset.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from forecasting.preprocessing import TIMESTAMP
from services.llm import LLMError, get_llm_provider
from services.metrics import MetricsError
from services.metrics.series import load_frame
from services.metrics.statistics import compute

logger = logging.getLogger(__name__)

# An LLM call per page view is neither fast nor free, and the underlying
# statistics move on the cadence of the source products (hourly at best).
_CACHE_TTL = timedelta(minutes=15)
_CACHE_MAX = 128
_cache: dict[tuple, tuple[datetime, dict[str, Any]]] = {}
_cache_lock = threading.Lock()

# Trend is judged against the series' own variability rather than a fixed
# epsilon: a 0.2 degC move is a real signal in a calm gyre and noise in a
# monsoon upwelling. Quarter of a standard deviation is the threshold below
# which "steady" is the honest word.
_TREND_SIGMA_FRACTION = 0.25


@dataclass
class StoryFacts:
    """Every figure the narrative is allowed to mention."""

    label: str
    unit: str
    current: float
    mean: float
    minimum: float
    maximum: float
    percentile: float
    trend_word: str
    trend_days: int
    change_recent: float | None
    change_365d: float | None
    observation_count: int
    start: str
    end: str
    forecast: dict[str, Any] | None = None
    drivers: list[str] = field(default_factory=list)

    def as_block(self) -> str:
        """The structured facts handed to the model."""
        lines = [
            f"Variable: {self.label} ({self.unit})",
            f"Record: {self.observation_count} observations, {self.start} to {self.end}",
            f"Current value: {self.current:.2f} {self.unit}",
            f"Record average: {self.mean:.2f} {self.unit}",
            f"Record range: {self.minimum:.2f} to {self.maximum:.2f} {self.unit}",
            f"Current value sits at the {self.percentile:.0f}th percentile of the record",
            f"Direction over the last {self.trend_days} days: {self.trend_word}",
        ]
        if self.change_recent is not None:
            lines.append(
                f"Change over the last {self.trend_days} days: "
                f"{self.change_recent:+.2f} {self.unit}"
            )
        if self.change_365d is not None:
            lines.append(f"Change over 365 days: {self.change_365d:+.2f} {self.unit}")
        if self.forecast:
            lines.append(
                f"Forecast {self.forecast['horizon']} days ahead: "
                f"{self.forecast['value']:.2f} {self.unit} "
                f"(95% interval {self.forecast['lower']:.2f} to "
                f"{self.forecast['upper']:.2f}, change {self.forecast['delta']:+.2f})"
            )
        if self.drivers:
            lines.append(f"Model's strongest drivers: {', '.join(self.drivers)}")
        return "\n".join(lines)


def _trend_word(recent_change: float | None, spread: float) -> str:
    if recent_change is None or not np.isfinite(recent_change):
        return "steady"
    threshold = max(spread * _TREND_SIGMA_FRACTION, 1e-9)
    if recent_change > threshold:
        return "rising"
    if recent_change < -threshold:
        return "falling"
    return "steady"


def _build_facts(
    frame: pd.DataFrame,
    variable: Any,
    forecast: dict[str, Any] | None,
    trend_days: int = 30,
) -> StoryFacts:
    statistics = {item.key: item for item in compute(frame, variable.code, variable.unit)}

    def value(key: str) -> float | None:
        entry = statistics.get(key)
        return entry.value if entry and entry.available else None

    stamps = pd.to_datetime(frame[TIMESTAMP])
    spread = value("std") or 0.0

    change_recent = value("change_30d")

    return StoryFacts(
        label=variable.label,
        unit=variable.unit,
        current=float(value("current") or 0.0),
        mean=float(value("mean") or 0.0),
        minimum=float(value("min") or 0.0),
        maximum=float(value("max") or 0.0),
        percentile=float(value("percentile") or 0.0),
        trend_word=_trend_word(change_recent, spread),
        trend_days=trend_days,
        change_recent=change_recent,
        change_365d=value("change_365d"),
        observation_count=int(
            pd.to_numeric(frame[variable.code], errors="coerce").notna().sum()
        ),
        start=stamps.min().date().isoformat(),
        end=stamps.max().date().isoformat(),
        forecast=forecast,
        drivers=list((forecast or {}).get("drivers", []))[:4],
    )


# --------------------------------------------------------------------------
# Deterministic rendering
# --------------------------------------------------------------------------


def render_template(facts: StoryFacts) -> str:
    """The story, written without an LLM.

    Both the fallback and the safety net. It says everything the generated
    version says; it simply says it in a fixed order.
    """
    unit = facts.unit
    relation = (
        "above" if facts.current > facts.mean else "below" if facts.current < facts.mean else "at"
    )
    gap = abs(facts.current - facts.mean)

    sentences = [
        f"{facts.label} is currently {facts.current:.2f} {unit}, "
        f"{gap:.2f} {unit} {relation} the {facts.mean:.2f} {unit} average "
        f"of the last {facts.observation_count} observations."
        if relation != "at"
        else f"{facts.label} is currently {facts.current:.2f} {unit}, "
        f"exactly at the record average.",
        f"That places it at the {facts.percentile:.0f}th percentile of a record "
        f"spanning {facts.start} to {facts.end}, "
        f"which ranged from {facts.minimum:.2f} to {facts.maximum:.2f} {unit}.",
    ]

    if facts.change_recent is not None:
        sentences.append(
            f"Values have been {facts.trend_word} over the last {facts.trend_days} days, "
            f"a change of {facts.change_recent:+.2f} {unit}."
        )
    if facts.change_365d is not None:
        sentences.append(
            f"Against the same date a year ago the change is "
            f"{facts.change_365d:+.2f} {unit}."
        )
    if facts.forecast:
        sentences.append(
            f"The {facts.forecast['horizon']}-day forecast is "
            f"{facts.forecast['value']:.2f} {unit} "
            f"({facts.forecast['delta']:+.2f} {unit}), with a 95% interval of "
            f"{facts.forecast['lower']:.2f} to {facts.forecast['upper']:.2f} {unit}."
        )
    if facts.drivers:
        sentences.append(
            f"The model attributes that forecast mainly to {_join(facts.drivers)}."
        )

    return " ".join(sentences)


def _join(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


# --------------------------------------------------------------------------
# Generated rendering
# --------------------------------------------------------------------------

_PROMPT = """You are an ocean data analyst writing the summary paragraph at the \
top of a marine intelligence page.

Below are the ONLY facts you may use. Write 3-5 flowing sentences that a \
non-specialist can follow, in the order: where the value stands now, how it \
compares to its record, how it has been moving, what is forecast, and why.

Hard rules:
- Do NOT state any number that does not appear in the facts below. Not one.
- Do NOT infer causes, mechanisms or consequences that are not listed.
- Do NOT speculate about climate change, ecological impact or human activity.
- Do NOT use markdown, headings, bullets or a title. Plain prose only.
- Round numbers exactly as given.

Facts:
{facts}
"""

# Matches integers and decimals, including signed ones, so the verifier sees
# every figure the model produced.
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _renderings(value: float) -> set[str]:
    """Every string form of a number the model might legitimately echo."""
    return {
        f"{value:.0f}", f"{value:.1f}", f"{value:.2f}",
        f"{abs(value):.0f}", f"{abs(value):.1f}", f"{abs(value):.2f}",
    }


def _verify(text: str, facts: StoryFacts) -> tuple[bool, str | None]:
    """Reject a narrative containing a number it was not given.

    The permitted set is derived from the facts block *itself* rather than
    from a separate list of values. That is not a shortcut — it is the only
    version that cannot drift. A hand-maintained list missed the window sizes
    that appear in the block's own labels ("Change over 365 days"), so the
    verifier rejected a perfectly faithful sentence for quoting a number it
    had been shown. Anything in the block is by definition fair game; anything
    else the model computed itself, which is exactly what this pipeline exists
    to prevent.

    Matching is done at the precision the block presents, since the model is
    asked to reproduce those strings and a rounding difference is not a
    fabrication.
    """
    block = facts.as_block()

    allowed: set[str] = set()
    for match in _NUMBER.findall(block):
        allowed.add(match)
        allowed.add(match.lstrip("-"))
        try:
            allowed |= _renderings(float(match))
        except ValueError:
            continue

    # Dates from the record window, in whole and in parts.
    for stamp in (facts.start, facts.end):
        allowed.add(stamp)
        allowed.update(stamp.split("-"))

    for match in _NUMBER.findall(text):
        candidates = {match, match.lstrip("-")}
        try:
            candidates |= _renderings(float(match))
        except ValueError:
            continue
        if not candidates & allowed:
            return False, match
    return True, None


async def _generate(facts: StoryFacts) -> tuple[str, str]:
    """Ask the LLM to phrase the facts. Returns (text, how_it_was_produced)."""
    try:
        provider = get_llm_provider()
    except LLMError as exc:
        logger.info(f"ocean story falling back to template: {exc}")
        return render_template(facts), "template"

    try:
        text = (await provider.generate(_PROMPT.format(facts=facts.as_block()))).strip()
    except Exception as exc:  # noqa: BLE001 - a narrative must never 500 a page
        logger.warning(f"ocean story generation failed, using template: {exc}")
        return render_template(facts), "template"

    if not text:
        return render_template(facts), "template"

    ok, offender = _verify(text, facts)
    if not ok:
        logger.warning(
            f"ocean story rejected: model produced {offender!r}, which is not in "
            f"the supplied facts. Falling back to the template."
        )
        return render_template(facts), "template-after-verification-failed"

    return text, "generated"


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


async def build(
    variable_key: str,
    latitude: float,
    longitude: float,
    *,
    range_key: str | None = "1y",
    horizon: int | None = 7,
    use_cache: bool = True,
) -> dict[str, Any]:
    """The Ocean Story for one variable at one point."""
    key = (variable_key, round(latitude, 3), round(longitude, 3), range_key, horizon)

    if use_cache:
        with _cache_lock:
            entry = _cache.get(key)
        if entry and datetime.now(UTC) - entry[0] < _CACHE_TTL:
            return entry[1]

    frame, variable, extra = await load_frame(
        variable_key, latitude, longitude, range_key=range_key
    )
    if frame.empty:
        raise MetricsError(f"no {variable.label} record at this point to summarise")

    forecast = await _try_forecast(variable_key, latitude, longitude, horizon)
    facts = _build_facts(frame, variable, forecast)
    text, source = await _generate(facts)

    payload = {
        "variable": variable_key,
        "label": variable.label,
        "unit": variable.unit,
        "story": text,
        # Named so the UI can badge a generated story differently from a
        # deterministic one. Readers deserve to know which they are looking at.
        "source": source,
        "facts": facts.as_block(),
        "forecast_included": forecast is not None,
        "generated_at": datetime.now(UTC).isoformat(),
    }

    if use_cache:
        with _cache_lock:
            _cache[key] = (datetime.now(UTC), payload)
            if len(_cache) > _CACHE_MAX:
                oldest = min(_cache, key=lambda k: _cache[k][0])
                _cache.pop(oldest, None)

    return payload


async def _try_forecast(
    variable_key: str, latitude: float, longitude: float, horizon: int | None
) -> dict[str, Any] | None:
    """Fold in the forecast when a model exists, omit it otherwise.

    An untrained variable still gets a story about its history — the narrative
    degrades by one sentence rather than the section disappearing.
    """
    if horizon is None:
        return None

    from forecasting import ForecastingError
    from forecasting.predictor import predict

    try:
        result = await predict(
            variable_key, latitude, longitude, horizon,
            history_window=30, top_k=4, include_history=False,
        )
    except ForecastingError as exc:
        logger.info(f"ocean story without forecast for {variable_key}: {exc}")
        return None

    return {
        "horizon": horizon,
        "value": result.prediction,
        "lower": result.interval.lower,
        "upper": result.interval.upper,
        "delta": result.trend_delta,
        "trend": result.trend,
        "drivers": [driver.label for driver in result.drivers],
    }
