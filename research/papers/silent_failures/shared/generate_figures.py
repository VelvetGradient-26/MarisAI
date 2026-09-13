"""Generates the one figure shared/body.tex references: a small-multiples
"naive reading vs. what the cheap check found" panel across six of the
eleven instances (the ones with two numbers in a shared unit; the other five
are qualitative or five-way comparisons better served by the paper's table).

Run with the machine_learning venv (has matplotlib):
    /Users/deepak/Desktop/MarisAI/machine_learning/.venv/bin/python \
        research/papers/silent_failures/shared/generate_figures.py

Values are hand-transcribed from shared/generated/macros.tex, which documents
each one's source; this script only draws them. Re-verify against macros.tex
before regenerating if those values change.

Colour choice: the house green (#2f7d5a, used in the two prior papers) fails
the accessibility palette validator's chroma-floor check (reads as gray under
CVD simulation) when paired with the house orange. #1f8f5c keeps the same hue
and passes; it is used here instead. Every point also carries a direct value
label, which is required regardless because the pair's CVD separation sits in
the 6-8 "warn" band (legal only with secondary encoding) -- see
`node scripts/validate_palette.js "#1f8f5c,#d1611f" --mode light` in the
dataviz skill.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parent / "generated"
OUT.mkdir(parents=True, exist_ok=True)

NAIVE = "#d1611f"
CHECKED = "#1f8f5c"
INK = "#10202a"
MUTED = "#6b8390"
RULE = "#d8e2e6"


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
            "axes.titlesize": 9.5,
            "axes.labelsize": 9,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "legend.fontsize": 9,
            "axes.titlelocation": "left",
            "axes.titlepad": 6,
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


# (short tag, naive/plausible label+value, checked/corrected label+value,
#  unit string for annotation, panel title)
PANELS = [
    (
        "I.4  Mixed-cadence merge",
        "00:00 sample",
        23.0,
        "true daily mean",
        20.0,
        "°C",
    ),
    (
        "I.7  Hampel filter on",
        "filtered (default on)",
        0.138,
        "filter off",
        0.202,
        "7-day skill",
    ),
    (
        "I.1  Ensemble vote (2026-08-13)",
        "proportional-weight ensemble",
        0.694,
        "best single member",
        0.788,
        "holdout TSS",
    ),
    (
        "I.12  Cross-product SST baseline",
        "matched (stale) product",
        0.026,
        "fresher, mismatched product",
        -0.149,
        "below-p10 contrast",
    ),
    (
        "I.2  Global vs regional habitat",
        "global (123,104 train rows)",
        0.448,
        "regional (1,902 train rows)",
        0.798,
        "matched-holdout TSS",
    ),
    (
        "2.5  Batched point sampling",
        "0-day pad",
        2.92,
        "45-day pad",
        0.0,
        "°C error on thetao",
    ),
]


def fig_naive_vs_checked() -> Path:
    fig, axes = plt.subplots(3, 2, figsize=(6.8, 5.6))
    for ax, (title, naive_label, naive_val, checked_label, checked_val, unit) in zip(
        axes.ravel(), PANELS
    ):
        y = 0
        ax.plot([naive_val, checked_val], [y, y], color=MUTED, lw=1.4, zorder=1)
        ax.scatter(
            [naive_val], [y], s=70, color=NAIVE, marker="o", zorder=3,
            edgecolor="white", linewidth=0.8,
        )
        ax.scatter(
            [checked_val], [y], s=70, color=CHECKED, marker="D", zorder=3,
            edgecolor="white", linewidth=0.8,
        )

        span = abs(checked_val - naive_val) or 1.0
        pad = span * 0.55
        lo, hi = sorted((naive_val, checked_val))
        ax.set_xlim(lo - pad, hi + pad)
        ax.set_ylim(-1, 1)

        above = naive_val >= checked_val
        ax.annotate(
            f"{naive_label}\n{naive_val:g} {unit}",
            xy=(naive_val, y),
            xytext=(0, 10 if above else -10),
            textcoords="offset points",
            ha="center",
            va="bottom" if above else "top",
            fontsize=7.3,
            color=NAIVE,
        )
        ax.annotate(
            f"{checked_label}\n{checked_val:g} {unit}",
            xy=(checked_val, y),
            xytext=(0, 10 if not above else -10),
            textcoords="offset points",
            ha="center",
            va="bottom" if not above else "top",
            fontsize=7.3,
            color=CHECKED,
        )

        ax.axhline(0, color=RULE, lw=0.8, zorder=0)
        ax.set_yticks([])
        ax.set_xticks([])
        ax.set_title(title, fontsize=8.6, color=INK, pad=18)

    handles = [
        plt.Line2D([0], [0], marker="o", color="none", markerfacecolor=NAIVE,
                   markeredgecolor="white", markersize=8, label="Reported / naive reading"),
        plt.Line2D([0], [0], marker="D", color="none", markerfacecolor=CHECKED,
                   markeredgecolor="white", markersize=8, label="What the cheap check found"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=2, bbox_to_anchor=(0.5, -0.02),
               frameon=False, fontsize=9)
    fig.suptitle(
        "Six of the eleven instances: a plausible number, and the number a second,\n"
        "cheap check produced from the same run",
        fontsize=9.5, y=1.03,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))

    path = OUT / "naive_vs_checked.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def main() -> None:
    setup()
    p = fig_naive_vs_checked()
    print(f"wrote {p}")


if __name__ == "__main__":
    main()
