"""PDF export for the Universal Ocean Data Downloader — the spec's full
report: title, metadata, summary statistics, variable descriptions, and a
line chart + histogram per numeric variable, with a sources/licence footer.
"""

from __future__ import annotations

import io
from typing import Any

import matplotlib

matplotlib.use("Agg")  # no display in a server process

import matplotlib.pyplot as plt
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from services.download.registry import VariableInfo

_STYLES = getSampleStyleSheet()
_CELL_STYLE = ParagraphStyle("cell", parent=_STYLES["Normal"], fontSize=8.5, leading=11)


def _table_style() -> TableStyle:
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
        ]
    )


def _format_area(area: dict[str, Any]) -> str:
    if area.get("type") == "point":
        return f"Point ({area['lat']}, {area['lon']})"
    return f"Bounding box — W{area['west']} S{area['south']} E{area['east']} N{area['north']}"


def _metadata_table(metadata: dict[str, Any]) -> Table:
    rows = [
        ["Area", Paragraph(_format_area(metadata["area"]), _CELL_STYLE)],
        [
            "Date range",
            Paragraph(f"{metadata['start_date']} to {metadata['end_date']}", _CELL_STYLE),
        ],
        ["Resolution", Paragraph(metadata["resolution"], _CELL_STYLE)],
        ["Variables", Paragraph(", ".join(metadata["variables"]), _CELL_STYLE)],
        ["Sources", Paragraph("; ".join(metadata["sources"]), _CELL_STYLE)],
        ["Generated at", Paragraph(metadata["generated_at"], _CELL_STYLE)],
    ]
    table = Table(rows, hAlign="LEFT", colWidths=[100, 380])
    table.setStyle(_table_style())
    return table


def _variables_table(variables: dict[str, VariableInfo]) -> Table:
    rows = [["Code", "Label", "Category", "Unit"]]
    for code, info in variables.items():
        rows.append([code, info.label, info.category, info.unit])
    table = Table(rows, hAlign="LEFT")
    table.setStyle(_table_style())
    return table


def _stats_table(df: pd.DataFrame, variables: dict[str, VariableInfo]) -> Table:
    rows = [["Variable", "Min", "Max", "Mean", "Median", "Std Dev"]]
    for code, info in variables.items():
        if code not in df.columns:
            continue
        series = df[code].dropna()
        if series.empty:
            rows.append([info.label, "—", "—", "—", "—", "—"])
            continue
        rows.append(
            [
                info.label,
                f"{series.min():.3f}",
                f"{series.max():.3f}",
                f"{series.mean():.3f}",
                f"{series.median():.3f}",
                f"{series.std():.3f}" if len(series) > 1 else "—",
            ]
        )
    table = Table(rows, hAlign="LEFT")
    table.setStyle(_table_style())
    return table


def _chart_image(fig: "plt.Figure") -> Image:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return Image(buf, width=6.2 * inch, height=2.6 * inch)


def _line_chart(df: pd.DataFrame, code: str, label: str, unit: str) -> Image:
    # A bbox can return many grid cells per timestamp — plotting every cell
    # as its own line would be an unreadable tangle, so this averages across
    # space per timestamp, keeping one clean line per variable while still
    # showing the real temporal trend.
    series = df.groupby("timestamp")[code].mean()
    fig, ax = plt.subplots(figsize=(7, 3))
    ax.plot(series.index, series.values, color="#1f6feb", linewidth=1.4)
    ax.set_title(f"{label} — spatial mean over time")
    ax.set_ylabel(unit)
    ax.grid(alpha=0.25)
    fig.autofmt_xdate()
    return _chart_image(fig)


def _histogram(df: pd.DataFrame, code: str, label: str, unit: str) -> Image:
    fig, ax = plt.subplots(figsize=(7, 3))
    values = df[code].dropna()
    ax.hist(values, bins=min(30, max(5, values.nunique())), color="#1f6feb", alpha=0.85)
    ax.set_title(f"{label} — distribution of all values")
    ax.set_xlabel(unit)
    ax.set_ylabel("count")
    ax.grid(alpha=0.25)
    return _chart_image(fig)


def to_pdf_bytes(
    df: pd.DataFrame, metadata: dict[str, Any], variables: dict[str, VariableInfo]
) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, title="Ocean Dataset Export")
    story: list[Any] = []

    story.append(Paragraph("Ocean Dataset Export", _STYLES["Title"]))
    story.append(Paragraph("MarisAI Universal Ocean Data Downloader", _STYLES["Normal"]))
    story.append(Spacer(1, 0.3 * inch))

    story.append(Paragraph("Metadata", _STYLES["Heading2"]))
    story.append(_metadata_table(metadata))
    story.append(Spacer(1, 0.25 * inch))

    story.append(Paragraph("Summary Statistics", _STYLES["Heading2"]))
    story.append(_stats_table(df, variables))
    story.append(Spacer(1, 0.25 * inch))

    story.append(Paragraph("Variable Descriptions", _STYLES["Heading2"]))
    story.append(_variables_table(variables))

    numeric_codes = [
        code
        for code in variables
        if code in df.columns and pd.api.types.is_numeric_dtype(df[code])
    ]
    if numeric_codes:
        story.append(PageBreak())
        story.append(Paragraph("Charts", _STYLES["Heading2"]))
        for code in numeric_codes:
            info = variables[code]
            story.append(Paragraph(info.label, _STYLES["Heading3"]))
            story.append(_line_chart(df, code, info.label, info.unit))
            story.append(Spacer(1, 0.15 * inch))
            story.append(_histogram(df, code, info.label, info.unit))
            story.append(Spacer(1, 0.3 * inch))

    story.append(PageBreak())
    story.append(Paragraph("Sources & Licensing", _STYLES["Heading2"]))
    for source in metadata["sources"]:
        story.append(Paragraph(f"• {source}", _STYLES["Normal"]))
    story.append(Spacer(1, 0.15 * inch))
    story.append(
        Paragraph(
            "Data provided by Copernicus Marine Service under the Copernicus Marine "
            "licence (free, open, and full access — see "
            "https://marine.copernicus.eu/user-corner-service/general-conditions-use). "
            "Generated by MarisAI.",
            _STYLES["Normal"],
        )
    )

    doc.build(story)
    return buf.getvalue()
