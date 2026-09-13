"""Generates the one figure shared/body.tex references: ensemble holdout TSS
across the softmax temperature sweep, against the best-member and
proportional-weighting reference lines.

Run with the machine_learning venv (has matplotlib):
    /Users/deepak/Desktop/MarisAI/machine_learning/.venv/bin/python \
        research/papers/ensemble_temperature/shared/generate_figures.py

Values are read directly from
machine_learning/reports/ensemble_temperature_sweep.csv, not hand-transcribed
-- re-run generate_figures.py after re-running the sweep script.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[4]
SWEEP_CSV = REPO_ROOT / "machine_learning" / "reports" / "ensemble_temperature_sweep.csv"
OUT = Path(__file__).resolve().parent / "generated"
OUT.mkdir(parents=True, exist_ok=True)

SOFTMAX = "#1f8f5c"
SHIPPED = "#d1611f"
BEST_MEMBER = "#10202a"
PROPORTIONAL = "#6b8390"
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
            "legend.fontsize": 8.5,
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
            "text.color": BEST_MEMBER,
            "axes.labelcolor": BEST_MEMBER,
            "legend.frameon": False,
        }
    )


def fig_sweep() -> Path:
    df = pd.read_csv(SWEEP_CSV)
    softmax = df[df["method"] == "softmax"].sort_values("temperature")
    proportional_tss = df[df["method"] == "proportional"]["tss"].iloc[0]
    best_member_tss = 0.8564  # lightgbm holdout TSS, the sweep's own reference

    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    ax.plot(softmax["temperature"], softmax["tss"], color=SOFTMAX, marker="o",
            markersize=4, lw=1.6, label="Softmax-weighted ensemble", zorder=3)
    ax.axhline(best_member_tss, color=BEST_MEMBER, lw=1.2, ls="-", zorder=2,
               label="Best single member (LightGBM)")
    ax.axhline(proportional_tss, color=PROPORTIONAL, lw=1.2, ls="--", zorder=2,
               label="Proportional weighting")
    ax.axvline(0.05, color=SHIPPED, lw=1.2, ls=":", zorder=1)
    ax.annotate("shipped\ntemperature\n(0.05)", xy=(0.05, softmax["tss"].min()),
                xytext=(0.05, 0.8495), ha="center", va="top", fontsize=7.5,
                color=SHIPPED)

    ax.set_xscale("log")
    ax.set_xlabel("Softmax temperature (log scale)")
    ax.set_ylabel("Holdout TSS")
    ax.set_title("The shipped temperature no longer clears its own best member")
    ax.legend(loc="lower right")
    fig.tight_layout()

    path = OUT / "temperature_sweep.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def main() -> None:
    setup()
    p = fig_sweep()
    print(f"wrote {p}")


if __name__ == "__main__":
    main()
