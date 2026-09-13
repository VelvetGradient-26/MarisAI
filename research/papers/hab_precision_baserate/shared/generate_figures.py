"""Generates the one figure shared/body.tex references.

Run with the machine_learning venv (has matplotlib; the backend one may not):
    /Users/deepak/Desktop/MarisAI/machine_learning/.venv/bin/python \
        research/papers/hab_precision_baserate/shared/generate_figures.py

Values are hand-transcribed from the same files shared/generated/macros.tex
documents (machine_learning/reports/hab_early_warning*_holdout.csv and the
matching *_summary.json for each of the five regions), not recomputed here --
this script only draws them. If those source files change, re-verify these
arrays against them before regenerating.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parent / "generated"
OUT.mkdir(parents=True, exist_ok=True)

# Palette: one muted colour per quantity, shared across all five regions'
# bars, plus a highlight colour to pick out the Arabian Sea / Bay of Bengal
# pair the paper's central contrast rests on.
BASE = "#6b8390"
PREC = "#2f6f9e"
LIFT = "#d1611f"
HIGHLIGHT = "#b3212e"
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
            "axes.titlesize": 11,
            "axes.labelsize": 10,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.fontsize": 9,
            "axes.titlelocation": "left",
            "axes.titlepad": 8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.edgecolor": "#5a6b73",
            "axes.linewidth": 0.8,
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.color": RULE,
            "grid.linewidth": 0.6,
            "xtick.major.width": 0.8,
            "ytick.major.width": 0.8,
            "xtick.color": "#5a6b73",
            "ytick.color": "#5a6b73",
            "text.color": INK,
            "axes.labelcolor": INK,
            "legend.frameon": False,
        }
    )


def fig_baserate_precision_lift() -> Path:
    """Grouped bars, one group per region ordered by base rate: base rate,
    t+7 precision, and t+7 lift over persistence.

    The point the figure exists to make: the base-rate and precision bars
    move together across regions (as the paper's argument says they always
    will); the lift bar does not track either one. Bay of Bengal and Arabian
    Sea show almost identical first two bars and a starkly different third;
    Baltic Sea's lift bar is taller than Benguela's despite a lower base
    rate.
    """
    # Source: machine_learning/reports/hab_early_warning*_holdout.csv and
    # *_summary.json, horizon t+7, read directly (see macros.tex).
    regions = ["Arabian\nSea", "Bay of\nBengal", "Baltic\nSea", "Benguela", "California\nCurrent"]
    base = [0.076, 0.078, 0.138, 0.154, 0.266]
    prec = [0.202, 0.187, 0.416, 0.566, 0.844]
    lift = [0.053, 0.150, 0.327, 0.111, 0.076]

    x = np.arange(len(regions))
    width = 0.26

    fig, ax = plt.subplots(figsize=(7.0, 3.8))
    b1 = ax.bar(x - width, base, width, label="Base rate (bloom prevalence)", color=BASE)
    b2 = ax.bar(x, prec, width, label="Precision @ recall 0.8", color=PREC)
    b3 = ax.bar(x + width, lift, width, label="Lift over persistence (PR-AUC)", color=LIFT)

    for bars in (b1, b2, b3):
        for bar in bars:
            h = bar.get_height()
            ax.annotate(
                f"{h:.3f}",
                xy=(bar.get_x() + bar.get_width() / 2, h),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=7.5,
                color=MUTED,
            )

    ax.set_xticks(x)
    ax.set_xticklabels(regions)
    ax.set_ylim(0, 1.02)
    ax.set_ylabel("Score")
    ax.set_title(
        "Base rate and precision track each other across regions; skill lift does not"
    )
    ax.legend(loc="upper left", ncol=1, fontsize=8)

    # Annotate the central contrast directly on the plot: one label, two thin
    # arrows down to the Arabian Sea and Bay of Bengal lift bars specifically
    # (the two bars whose corresponding base-rate and precision bars are
    # visually identical, at x=0 and x=1).
    # Arrow tips land inside the bar itself (half its height), not just above
    # it, so they don't cross the "0.053"/"0.150" value labels sitting just
    # above each bar's top. Each arrow also bows outward (away from the
    # intervening precision bar/label at the group's own centre) rather than
    # cutting a straight diagonal through it.
    label_xy = (0.5, 0.56)
    ax.annotate(
        "", xy=(0 + width, lift[0] * 0.5), xytext=label_xy,
        arrowprops=dict(arrowstyle="->", color=HIGHLIGHT, linewidth=0.9,
                         shrinkA=2, shrinkB=2, connectionstyle="arc3,rad=0.25"),
    )
    ax.annotate(
        "", xy=(1 + width, lift[1] * 0.5), xytext=label_xy,
        arrowprops=dict(arrowstyle="->", color=HIGHLIGHT, linewidth=0.9,
                         shrinkA=2, shrinkB=2, connectionstyle="arc3,rad=-0.25"),
    )
    ax.text(
        label_xy[0], label_xy[1] + 0.02,
        "same base rate, same precision,\n2.8$\\times$ the lift",
        ha="center", va="bottom", fontsize=8, color=HIGHLIGHT,
    )

    fig.tight_layout()

    path = OUT / "baserate_precision_lift.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def main() -> None:
    setup()
    p1 = fig_baserate_precision_lift()
    print(f"wrote {p1}")


if __name__ == "__main__":
    main()
