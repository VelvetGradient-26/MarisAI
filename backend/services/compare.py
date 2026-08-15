"""Two coordinates, side by side.

The dashboard answers "what is happening globally" and the brief answers "what
is happening here". Neither answers "how does here differ from there", which is
the question research use actually starts from — is this bay warmer than that
one, does the forecast diverge, is habitat suitability higher at the shelf break
than over the basin.

**It is a view over `services/brief.py`, not a second assembly of the same
facts.** Every number in a comparison already has a brief row; building a
parallel pipeline would let the two disagree about the same coordinate, which is
the worst possible outcome for a feature whose entire output is a difference.
Both briefs are built concurrently and then aligned.

Three rules the alignment follows, each of which was a decision rather than an
obvious default:

* **A row present at only one place is kept, not dropped.** The asymmetry is
  frequently the most informative thing in the comparison — "habitat
  suitability: 0.71 here, outside the model's region there" is a real answer,
  and an aligner that silently dropped unmatched rows would report two points as
  more alike than they are.
* **A delta is computed only when both sides parse as numbers in the same
  unit.** Brief rows are formatted for reading ("1,204 m", "0.31 m/s toward
  NE"), so the leading quantity is recoverable but the rest is prose. When the
  units differ, or either side is not numeric, `delta` is null and the two
  values still stand side by side. A subtraction across mismatched units is the
  one output here that would be confidently wrong.
* **Deltas are `b - a`**, stated in the payload, because a signed number with an
  undeclared direction is a coin flip.

What this deliberately does not do is rank. There is no "better" point without a
purpose, and a composite score over temperature, waves and habitat would be the
same unvalidatable index TODO.md already records rejecting.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from services.brief import BriefError, build_brief

# A leading quantity and, optionally, what follows it. Thousands separators are
# handled, for the same reason the assistant's grounding checker learned to:
# "1,204 m" otherwise parses as 1 and the comparison silently reports a
# thousand-metre depth difference as one metre.
_QUANTITY = re.compile(r"^\s*(-?\d[\d,]*\.?\d*)\s*(.*)$")

# Forecast rows carry their horizons as keys rather than as a formatted value.
_HORIZON_KEYS = ("h1", "h3", "h7", "h30")

# Rows that are the *inputs* to the comparison rather than results of it. The
# parser handles them perfectly and the answer is still nonsense: "latitude
# +3.0°, +30.3%" is a restatement of what the user typed, dressed as a finding,
# and a percent change in a coordinate is not a quantity at all. The separation
# a reader actually wants is a distance, which is a different row and is not
# claimed here.
_NOT_COMPARABLE = frozenset({"Latitude", "Longitude"})


def _parse_quantity(value: Any) -> tuple[float | None, str]:
    """The leading number and the trailing text of a formatted brief value.

    Returns `(None, "")` for anything that does not begin with a number, which
    includes every deliberate sentinel a brief uses ("unavailable", "no data
    (land or outside coverage)") — so a sentinel can never be mistaken for a
    measurement.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value), ""
    if not isinstance(value, str):
        return None, ""
    match = _QUANTITY.match(value)
    if match is None:
        return None, ""
    try:
        number = float(match.group(1).replace(",", ""))
    except ValueError:
        return None, ""
    return number, match.group(2).strip()


def _delta(a: Any, b: Any) -> dict[str, Any] | None:
    """The difference between two brief values, or None if one is not defined.

    The unit check is not decoration. `_flow_section` formats a row as
    "0.31 m/s toward NE" and a location row as "1,204 m"; comparing across two
    points always pairs like with like, but a *future* row whose text differs
    between the two points is exactly the case where subtracting would produce a
    plausible number about nothing.
    """
    value_a, unit_a = _parse_quantity(a)
    value_b, unit_b = _parse_quantity(b)
    if value_a is None or value_b is None:
        return None
    if unit_a != unit_b:
        return None
    return {
        "value": round(value_b - value_a, 4),
        "unit": unit_a,
        "percent": round((value_b - value_a) / abs(value_a) * 100, 1) if value_a else None,
    }


def _row_key(row: dict[str, Any]) -> str:
    return str(row.get("label", ""))


def _compare_forecast_row(a: dict[str, Any] | None, b: dict[str, Any] | None) -> dict[str, Any]:
    """One forecast variable across both points, horizon by horizon.

    Forecast rows are the one shape where the numbers arrive unformatted, so
    this path never goes near `_parse_quantity` — the horizons are floats
    already and the unit is a field of its own.
    """
    source = a or b or {}
    horizons: dict[str, Any] = {}
    for key in _HORIZON_KEYS:
        left = (a or {}).get(key)
        right = (b or {}).get(key)
        if left is None and right is None:
            continue
        entry: dict[str, Any] = {"a": left, "b": right, "delta": None}
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            entry["delta"] = round(float(right) - float(left), 4)
        horizons[key] = entry

    return {
        "label": source.get("label"),
        "unit": source.get("unit", ""),
        "a_last_observed": (a or {}).get("last_observed"),
        "b_last_observed": (b or {}).get("last_observed"),
        "horizons": horizons,
        "only_at": None if (a and b) else ("a" if a else "b"),
    }


def _compare_section(section_a: dict[str, Any], section_b: dict[str, Any]) -> dict[str, Any]:
    """One section of both briefs, aligned on row label.

    Row order follows point A and then appends any rows only point B has, so the
    common case — two points with the same rows — reads in the brief's own
    order rather than in an arbitrary one.
    """
    rows_a = {_row_key(row): row for row in section_a.get("rows", [])}
    rows_b = {_row_key(row): row for row in section_b.get("rows", [])}
    ordered = list(rows_a) + [key for key in rows_b if key not in rows_a]

    is_forecast = section_a.get("key") == "forecast"
    rows: list[dict[str, Any]] = []
    for key in ordered:
        left, right = rows_a.get(key), rows_b.get(key)
        if is_forecast:
            rows.append(_compare_forecast_row(left, right))
            continue
        value_a = left.get("value") if left else None
        value_b = right.get("value") if right else None
        rows.append(
            {
                "label": key,
                "a": value_a,
                "b": value_b,
                "delta": None if key in _NOT_COMPARABLE else _delta(value_a, value_b),
                "only_at": None if (left and right) else ("a" if left else "b"),
            }
        )

    return {
        "key": section_a.get("key"),
        "title": section_a.get("title"),
        # Available where *either* point has it. A section unavailable at one
        # point and populated at the other is a comparison, not a gap — the row
        # level carries `only_at` to say which side is which.
        "available": bool(section_a.get("available") or section_b.get("available")),
        "a_available": bool(section_a.get("available")),
        "b_available": bool(section_b.get("available")),
        "a_unavailable_reason": section_a.get("unavailable_reason"),
        "b_unavailable_reason": section_b.get("unavailable_reason"),
        # The brief's notes carry the "this is model output" and operating-point
        # caveats. They are per-section and identical for both points, so one
        # copy travels — dropping them would strip the disclaimers off the two
        # sections that most need them.
        "note": section_a.get("note") or section_b.get("note"),
        "rows": rows,
    }


async def compare_points(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> dict[str, Any]:
    """Two coordinates as one aligned document.

    The two briefs are gathered rather than awaited in sequence: each is already
    a fan-out over several providers, and running them one after the other would
    double the slowest path for no reason.
    """
    brief_a, brief_b = await asyncio.gather(
        build_brief(latitude_a, longitude_a),
        build_brief(latitude_b, longitude_b),
    )

    sections_a = {section["key"]: section for section in brief_a["sections"]}
    sections_b = {section["key"]: section for section in brief_b["sections"]}

    sections = [
        _compare_section(section, sections_b.get(section["key"], {"rows": []}))
        for section in brief_a["sections"]
        if section["key"] in sections_a
    ]

    return {
        "a": {"latitude": latitude_a, "longitude": longitude_a},
        "b": {"latitude": latitude_b, "longitude": longitude_b},
        "generated_at": brief_a["generated_at"],
        "delta_direction": "b - a",
        "sections": sections,
        "note": (
            "Deltas are point B minus point A, and are computed only where both sides are "
            "numeric in the same unit. No ranking is offered: which point is 'better' "
            "depends on what you are doing there."
        ),
    }


__all__ = ["BriefError", "compare_points"]
