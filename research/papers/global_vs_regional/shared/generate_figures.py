"""Generates the two figures shared/body.tex references.

Run with the machine_learning venv (has matplotlib; the backend one may not):
    /Users/deepak/Desktop/MarisAI/machine_learning/.venv/bin/python \
        research/papers/global_vs_regional/shared/generate_figures.py

Values are hand-transcribed from the same two source files
shared/generated/macros.tex documents (machine_learning/reports/
global_vs_regional_habitat.csv and the two fish_habitat*_summary.json files),
not recomputed here -- this script only draws them. If those source files
change, re-verify these arrays against them before regenerating.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parent / "generated"
OUT.mkdir(parents=True, exist_ok=True)

# Palette continuity with the shipped "Rising Skill, Falling Skill" paper's
# notebooks (research/notebooks/marisviz.py): green marks the stronger/local
# result, orange the weaker/broader-extent one it is contrasted against.
REGIONAL = "#2f7d5a"
GLOBAL = "#d1611f"
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


def fig_matched_holdout() -> Path:
    """Grouped bars: the four matched-holdout accuracy metrics, regional vs
    global, on the identical 885 rows."""
    metrics = ["TSS", "Boyce", "ROC-AUC", "PR-AUC"]
    regional = [0.798, 0.923, 0.945, 0.804]
    global_ = [0.448, 0.721, 0.790, 0.489]

    x = np.arange(len(metrics))
    width = 0.36

    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    b1 = ax.bar(x - width / 2, regional, width, label="Regional (1,902 train rows)", color=REGIONAL)
    b2 = ax.bar(x + width / 2, global_, width, label="Global (123,104 train rows)", color=GLOBAL)

    for bars in (b1, b2):
        for bar in bars:
            h = bar.get_height()
            ax.annotate(
                f"{h:.3f}",
                xy=(bar.get_x() + bar.get_width() / 2, h),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=8,
                color=MUTED,
            )

    ax.set_xticks(x)
    ax.set_xticklabels(metrics)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Score (higher is better)")
    ax.set_title("Matched-holdout comparison: identical 885 regional rows")
    ax.legend(loc="lower left", ncol=1)
    fig.tight_layout()

    path = OUT / "matched_holdout_bars.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def fig_shap_displacement() -> Path:
    """Two horizontal-bar panels, same feature axis order, showing the
    regional -> global importance shift for the six features that appear in
    either model's own top six."""
    # (feature, regional mean |SHAP|, global mean |SHAP|)
    # Source: fish_habitat_summary.json (regional) and
    # fish_habitat_global_ocean_summary.json (global) top_features.
    rows = [
        ("depth", 1.085, 0.656),
        ("distance_to_coast", 0.847, 0.262),
        ("o2", None, 1.773),
        ("thetao_lag60", None, 1.058),
        ("thermal_position", 0.250, 0.760),
        ("zos", 0.372, 0.314),
    ]
    # Order by global importance descending, so the displaced features (o2,
    # thetao_lag60) read at the top -- the figure's point.
    rows.sort(key=lambda r: (r[2] is None, -(r[2] or 0)))

    labels = [r[0] for r in rows]
    regional_vals = [r[1] if r[1] is not None else 0.0 for r in rows]
    global_vals = [r[2] if r[2] is not None else 0.0 for r in rows]
    regional_present = [r[1] is not None for r in rows]

    y = np.arange(len(labels))
    height = 0.36

    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    ax.barh(y + height / 2, regional_vals, height, label="Regional model", color=REGIONAL)
    ax.barh(y - height / 2, global_vals, height, label="Global model", color=GLOBAL)

    for yi, present in zip(y, regional_present):
        if not present:
            ax.text(
                0.02, yi + height / 2, "not in regional top 12",
                va="center", ha="left", fontsize=7.5, color=MUTED, style="italic",
            )

    ax.set_yticks(y)
    ax.set_yticklabels(labels, family="monospace", fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel(r"mean $|\mathrm{SHAP}|$")
    ax.set_title("Feature displacement: LightGBM tier, regional vs global")
    ax.legend(loc="lower right")
    fig.tight_layout()

    path = OUT / "shap_displacement.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def main() -> None:
    setup()
    p1 = fig_matched_holdout()
    p2 = fig_shap_displacement()
    print(f"wrote {p1}")
    print(f"wrote {p2}")


if __name__ == "__main__":
    main()
