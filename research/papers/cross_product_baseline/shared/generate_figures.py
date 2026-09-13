"""Generates the one figure shared/body.tex references: a two-panel dumbbell
plot (weak tier, strong tier) across Fix A, Fix B, and Control C.

Run with the machine_learning venv (has matplotlib; the backend one may not):
    /Users/deepak/Desktop/MarisAI/machine_learning/.venv/bin/python \
        research/papers/cross_product_baseline/shared/generate_figures.py

Values are hand-transcribed from shared/generated/macros.tex, which documents
each one's source (backend/services/sst_anomaly.py's module docstring and
DONE.md's "A rolling wind history" entry) -- this script only draws them.
Re-verify against macros.tex before regenerating if those values change.

Control C is drawn with a visual break (extra vertical gap, a dividing rule,
and a distinct marker/colour) from Fix A and Fix B -- it is a control that
rules out an alternative explanation, not a third fix attempt, and the figure
must not visually assert otherwise (see body.tex's Discussion section).
"""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parent / "generated"
OUT.mkdir(parents=True, exist_ok=True)

MATCHED = "#2f7d5a"     # matched / production-configuration arm
CANDIDATE = "#d1611f"   # the arm that actually varies in each row
CONTROL = "#6b8390"     # Control C's own two arms -- neither is "the fix"
INK = "#10202a"
MUTED = "#6b8390"
RULE = "#d8e2e6"

# (row label, matched-arm label, matched value, candidate-arm label,
#  candidate value, is_control)
WEAK_ROWS = [
    ("Fix A: swap product\n(2026-08-17)", "OISST", 0.026, "Live physics", 0.022, False),
    ("Fix B: matched climatology\n(2026-08-25)", "OISST", 0.027, "GLORYS-fitted", 0.021, False),
    ("Control C: wind aggregation\n(2026-08-28)", "Instantaneous", 0.0234, "1.2-day mean", 0.0182, True),
]
STRONG_ROWS = [
    ("Fix A: swap product\n(2026-08-17)", "OISST", 0.002, "Live physics", -0.149, False),
    ("Fix B: matched climatology\n(2026-08-25)", "OISST", -0.001, "GLORYS-fitted", -0.051, False),
    ("Control C: wind aggregation\n(2026-08-28)", "Instantaneous", -0.0061, "1.2-day mean", -0.0049, True),
]


def setup() -> None:
    mpl.rcParams.update(
        {
            "figure.dpi": 140,
            "savefig.dpi": 300,
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.03,
            "savefig.facecolor": "white",
            "figure.facecolor": "white",
            "font.family": "serif",
            "font.serif": ["DejaVu Serif"],
            "font.size": 10,
            "axes.titlesize": 10.5,
            "axes.labelsize": 9,
            "xtick.labelsize": 8.5,
            "ytick.labelsize": 8.5,
            "legend.fontsize": 8.5,
            "axes.titlelocation": "left",
            "axes.titlepad": 8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.spines.left": False,
            "axes.edgecolor": "#5a6b73",
            "axes.linewidth": 0.8,
            "text.color": INK,
            "axes.labelcolor": INK,
            "legend.frameon": False,
        }
    )


def _panel(ax, rows, title, xlabel, show_row_labels=True, xticks=None) -> None:
    # Extra gap before the control row so it reads as visually separated,
    # not a third row of the same kind.
    ys = [2.3, 1.15, -0.4]

    for (label, m_label, m_val, c_label, c_val, is_control), y in zip(rows, ys):
        line_color = CONTROL if is_control else MUTED
        m_color = CONTROL if is_control else MATCHED
        c_color = CONTROL if is_control else CANDIDATE
        m_marker = "s" if is_control else "o"
        c_marker = "s" if is_control else "D"

        ax.plot([m_val, c_val], [y, y], color=line_color, lw=1.3, zorder=1)
        ax.scatter([m_val], [y], s=64, color=m_color, marker=m_marker, zorder=3,
                   edgecolor="white", linewidth=0.7)
        ax.scatter([c_val], [y], s=64, color=c_color, marker=c_marker, zorder=3,
                   edgecolor="white", linewidth=0.7)

        above = m_val >= c_val
        ax.annotate(f"{m_label} {m_val:g}", xy=(m_val, y), xytext=(0, 8 if above else -8),
                    textcoords="offset points", ha="center",
                    va="bottom" if above else "top", fontsize=7.2, color=m_color)
        ax.annotate(f"{c_label} {c_val:g}", xy=(c_val, y), xytext=(0, 8 if not above else -8),
                    textcoords="offset points", ha="center",
                    va="bottom" if not above else "top", fontsize=7.2, color=c_color)

        if show_row_labels:
            ax.text(-0.02, y, label, transform=ax.get_yaxis_transform(), ha="right",
                    va="center", fontsize=7.4, color=INK, linespacing=1.3)

    # Dividing rule between the two fix attempts and the control row.
    ax.axhline(0.4, color=RULE, lw=0.9, linestyle=(0, (3, 2)), zorder=0)
    ax.axvline(0, color=RULE, lw=0.8, zorder=0)
    ax.set_ylim(-1.1, 3.0)
    ax.set_yticks([])
    if xticks is not None:
        ax.set_xticks(xticks)
    ax.set_xlabel(xlabel)
    ax.set_title(title)


def fig_fix_attempts() -> Path:
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 4.4), gridspec_kw={"wspace": 0.3})

    _panel(axes[0], WEAK_ROWS, "Weak tier (mean-based,\nfixed 0.5\N{DEGREE SIGN}C threshold)",
           "cool-anomaly contrast")
    _panel(axes[1], STRONG_ROWS, "Strong tier (percentile,\nbelow seasonal p10)",
           "below-p10 contrast", show_row_labels=False,
           xticks=[-0.15, -0.10, -0.05, 0.00])

    handles = [
        plt.Line2D([0], [0], marker="o", color="none", markerfacecolor=MATCHED,
                   markeredgecolor="white", markersize=7, label="Matched-product arm (Fix A/B)"),
        plt.Line2D([0], [0], marker="D", color="none", markerfacecolor=CANDIDATE,
                   markeredgecolor="white", markersize=7, label="Substituted-product arm (Fix A/B)"),
        plt.Line2D([0], [0], marker="s", color="none", markerfacecolor=CONTROL,
                   markeredgecolor="white", markersize=7, label="Control C (product matched throughout)"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=1, bbox_to_anchor=(0.5, -0.13),
               frameon=False, fontsize=8.5)
    fig.suptitle(
        "Two cross-product fix attempts invert the strong tier; a control that varies\n"
        "only wind aggregation, holding the product matched, does not",
        fontsize=9.8, y=1.05,
    )
    fig.tight_layout(rect=(0.14, 0.1, 1, 1))

    path = OUT / "fix_attempts.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def main() -> None:
    setup()
    p = fig_fix_attempts()
    print(f"wrote {p}")


if __name__ == "__main__":
    main()
