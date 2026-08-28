"""A point brief as a PDF.

Rendering only — `services/brief.py` decides what a brief contains. The split is
the same one `services/download/export/pdf.py` keeps: a document that computed
its own numbers would be a second source of truth for them, and the first thing
to drift.

The layout rule worth stating, because it is the reason this is not a plain
table dump: **an unavailable section is printed, not omitted.** A brief with the
habitat block missing looks like a brief where habitat did not apply; a brief
that says "outside the habitat model's region (northern Indian Ocean, 55–95°E)"
tells the reader something true. That is the same rule the dashboard holds on
screen, and it matters more here — a PDF is read away from the app, where nobody
can hover over a blank panel to find out why.
"""

from __future__ import annotations

import io
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_STYLES = getSampleStyleSheet()

_TITLE = ParagraphStyle(
    "briefTitle", parent=_STYLES["Title"], fontSize=18, leading=22, alignment=TA_LEFT
)
_SUBTITLE = ParagraphStyle(
    "briefSubtitle", parent=_STYLES["Normal"], fontSize=9.5, textColor=colors.HexColor("#4b5563")
)
_HEADING = ParagraphStyle(
    "briefHeading", parent=_STYLES["Heading2"], fontSize=12, spaceBefore=14, spaceAfter=4
)
_NOTE = ParagraphStyle(
    "briefNote",
    parent=_STYLES["Normal"],
    fontSize=8,
    leading=10.5,
    textColor=colors.HexColor("#4b5563"),
    spaceBefore=4,
)
_UNAVAILABLE = ParagraphStyle(
    "briefUnavailable",
    parent=_STYLES["Normal"],
    fontSize=9,
    leading=12,
    textColor=colors.HexColor("#92400e"),
)


def _table(rows: list[list[str]], widths: list[float]) -> Table:
    table = Table(rows, colWidths=widths, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
            ]
        )
    )
    return table


def _format_number(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, (int, float)):
        return f"{value:g}"
    return str(value)


def _forecast_table(rows: list[dict[str, Any]]) -> Table:
    """The forecast block is the one section with a real matrix shape, so it gets
    a proper header row rather than the label/value pairs everything else uses."""
    horizons = [key for key in ("h1", "h3", "h7") if any(key in row for row in rows)]
    header = ["Variable", "Unit", "Latest observed"] + [f"+{key[1:]}d" for key in horizons]
    body = [
        [
            str(row.get("label", "")),
            str(row.get("unit", "")),
            _format_number(row.get("last_observed")),
            *[_format_number(row.get(key)) for key in horizons],
        ]
        for row in rows
    ]
    widths = [45 * mm, 18 * mm, 28 * mm] + [22 * mm] * len(horizons)
    return _table([header, *body], widths)


def render(brief: dict[str, Any]) -> bytes:
    """One brief, as PDF bytes."""
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"MarisAI point brief {brief['latitude']:.3f}, {brief['longitude']:.3f}",
        author="MarisAI",
    )

    story: list[Any] = [
        Paragraph("Ocean point brief", _TITLE),
        Paragraph(
            f"{brief['latitude']:.4f}°, {brief['longitude']:.4f}° &nbsp;·&nbsp; "
            f"generated {brief['generated_at'][:19].replace('T', ' ')} UTC",
            _SUBTITLE,
        ),
        Spacer(1, 4),
        HRFlowable(width="100%", color=colors.HexColor("#d1d5db"), thickness=0.6),
    ]

    for section in brief["sections"]:
        story.append(Paragraph(str(section["title"]), _HEADING))

        if not section["available"]:
            # Printed, not skipped. See the module docstring.
            story.append(
                Paragraph(
                    f"Not available — {section.get('unavailable_reason', 'no reason given')}.",
                    _UNAVAILABLE,
                )
            )
            continue

        rows = section["rows"]
        if section["key"] == "forecast":
            story.append(_forecast_table(rows))
        else:
            story.append(
                _table(
                    [
                        ["Measure", "Value"],
                        *[[str(row.get("label", "")), str(row.get("value", ""))] for row in rows],
                    ],
                    [60 * mm, 100 * mm],
                )
            )

        if section.get("note"):
            story.append(Paragraph(str(section["note"]), _NOTE))

    story.extend(
        [
            Spacer(1, 10),
            HRFlowable(width="100%", color=colors.HexColor("#d1d5db"), thickness=0.6),
            Paragraph(
                "Sources: Copernicus Marine Service, NOAA Coral Reef Watch, GEBCO, Open-Meteo, "
                "OBIS. Sections marked MODEL OUTPUT are predictions from models trained and "
                "cross-validated offline, not measurements. MarisAI is not a marine warning "
                "service and this document is not a navigational aid.",
                _NOTE,
            ),
        ]
    )

    document.build(story)
    return buffer.getvalue()
