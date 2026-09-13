"""Generates the two figures shared/body.tex references.

Run with the machine_learning venv (has matplotlib; the backend one may not):
    /Users/deepak/Desktop/MarisAI/machine_learning/.venv/bin/python \
        research/papers/upwelling_control_arm/shared/generate_figures.py

Values are hand-transcribed from shared/generated/macros.tex, which documents
its own primary sources (backend/services/upwelling.py's and
backend/services/sst_anomaly.py's module docstrings, DONE.md) -- not
recomputed here, this script only draws them. If macros.tex changes,
re-verify these arrays against it before regenerating.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parent / "generated"
OUT.mkdir(parents=True, exist_ok=True)

# Palette continuity with this research program's other figures
# (research/papers/global_vs_regional/shared/generate_figures.py): green marks
# the arm a claim is being made about, orange the arm it is contrasted
# against. Here that is favourable-wind cells versus the downwelling control.
FAVOUR = "#2f7d5a"
CONTROL = "#d1611f"
TRAILING = "#1f6fa8"
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


def fig_corroboration_bars() -> Path:
    """Grouped bars: favourable vs. control, at both tiers, 2026-08-17."""
    tiers = ["Weak\n(cool anomaly)", "Strong\n(below seasonal p10)"]
    favourable = [19.9, 4.1]
    control = [17.2, 3.9]

    x = np.arange(len(tiers))
    width = 0.36

    fig, ax = plt.subplots(figsize=(5.6, 3.6))
    b1 = ax.bar(x - width / 2, favourable, width, label="Upwelling-favourable", color=FAVOUR)
    b2 = ax.bar(x + width / 2, control, width, label="Control (downwelling-favourable)", color=CONTROL)

    for bars in (b1, b2):
        for bar in bars:
            h = bar.get_height()
            ax.annotate(
                f"{h:.1f}%",
                xy=(bar.get_x() + bar.get_width() / 2, h),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=8,
                color=MUTED,
            )

    ax.set_xticks(x)
    ax.set_xticklabels(tiers)
    ax.set_ylim(0, 24)
    ax.set_ylabel("Coastal cells with a cold anomaly (%)")
    ax.set_title("Corroboration vs. control, live global field, 2026-08-17")
    ax.legend(loc="upper right", ncol=1)
    fig.tight_layout()

    path = OUT / "corroboration_bars.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def fig_wind_history_spread() -> Path:
    """Two panels: each tier's contrast across three unchanged-configuration
    dates (circles) plus the 2026-08-28 trailing-mean arm (diamond), with a
    shaded band spanning the three-date range of the unchanged configuration."""
    dates = ["Aug 17\ninstant.", "Aug 25\ninstant.", "Aug 28\ninstant."]
    x = np.arange(len(dates)) * 1.3

    weak = [0.026, 0.027, 0.0234]
    weak_trailing = 0.0182
    strong = [0.002, -0.001, -0.0061]
    strong_trailing = -0.0049

    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.6), sharex=False)

    for ax, values, trailing, title, ylabel in (
        (axes[0], weak, weak_trailing, "Weak tier (cool anomaly)", "Favourable $-$ control fraction"),
        (axes[1], strong, strong_trailing, "Strong tier (below seasonal p10)", ""),
    ):
        lo, hi = min(values), max(values)
        ax.axhspan(lo, hi, color=MUTED, alpha=0.15, zorder=0,
                   label="3-date spread,\nunchanged config.")
        ax.axhline(0.0, color=RULE, linewidth=1.0, zorder=0)
        ax.plot(x, values, "o", color=FAVOUR, markersize=8, zorder=3,
               label="Instantaneous wind\n(unchanged config.)")
        # Arrow from the 2026-08-28 instantaneous point to the trailing-mean value.
        trailing_x = x[-1] + 1.0
        ax.annotate(
            "",
            xy=(trailing_x, trailing),
            xytext=(x[-1], values[-1]),
            arrowprops=dict(arrowstyle="-|>", color=TRAILING, lw=1.4),
            zorder=2,
        )
        ax.plot([trailing_x], [trailing], "D", color=TRAILING, markersize=8, zorder=3,
               label="1.2-day trailing mean\n(2026-08-28)")
        ax.set_xticks(list(x) + [trailing_x])
        ax.set_xticklabels(dates + ["Aug 28\ntrailing"], fontsize=7.5)
        ax.set_title(title)
        if ylabel:
            ax.set_ylabel(ylabel)
        ax.set_xlim(x[0] - 0.55, trailing_x + 0.55)

    axes[1].legend(loc="upper right", fontsize=7, ncol=1)
    fig.suptitle(
        "Wind-history follow-up (all dates 2026): movement from averaging vs. "
        "natural day-to-day spread",
        x=0.02, ha="left", fontsize=10.5,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.93))

    path = OUT / "wind_history_spread.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def main() -> None:
    setup()
    p1 = fig_corroboration_bars()
    p2 = fig_wind_history_spread()
    print(f"wrote {p1}")
    print(f"wrote {p2}")


if __name__ == "__main__":
    main()
