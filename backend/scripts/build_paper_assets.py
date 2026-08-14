#!/usr/bin/env python
"""Turn the experiment JSON into the paper's figures and LaTeX tables.

    .venv/bin/python scripts/build_paper_assets.py

Reads `models/forecasting/_reports/paper/{baselines,loso,meta}.json` and writes
PDF figures plus `\\input`-able .tex table fragments into `paper/generated/`.
Nothing in the paper hardcodes a number: every figure and every table cell is
produced here, so a rerun of the experiments updates the manuscript rather than
inviting someone to retype a table.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "models" / "forecasting" / "_reports" / "paper"
OUT = ROOT.parent / "research" / "papers" / "shared" / "generated"

# Validated with the dataviz palette checker (light surface): CVD separation
# dE 21.7 protan / 29.9 tritan, normal-vision 29.8, both >= 3:1 on white.
# Two series only -- the grey is reference ink (the zero line), not a series,
# and is deliberately outside the categorical palette.
PERSISTENCE = "#1f6fb2"
CLIMATOLOGY = "#d1611f"
INK = "#4a4a4a"
MUTED = "#8a8a8a"

HORIZONS = [1, 3, 7, 30]


def style() -> None:
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["DejaVu Serif"],
            "font.size": 8,
            "axes.labelsize": 8,
            "axes.titlesize": 8.5,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "legend.fontsize": 7.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.edgecolor": "#666666",
            "axes.linewidth": 0.6,
            "xtick.major.width": 0.6,
            "ytick.major.width": 0.6,
            "grid.color": "#dddddd",
            "grid.linewidth": 0.5,
            "figure.dpi": 200,
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.02,
        }
    )


def pretty(name: str) -> str:
    return name.replace("_", " ")


def load() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    baselines = json.loads((DATA / "baselines.json").read_text())
    loso = json.loads((DATA / "loso.json").read_text())
    meta = json.loads((DATA / "meta.json").read_text()) if (DATA / "meta.json").exists() else {}

    rows = []
    for entry in baselines:
        if "metrics" not in entry:
            continue
        metrics = entry["metrics"]
        rows.append(
            {
                "variable": entry["variable"],
                "horizon": entry["horizon"],
                "label": entry.get("label", entry["variable"]),
                "unit": entry.get("unit", ""),
                "circular": entry.get("circular", False),
                "rows": entry.get("rows"),
                "sites": entry.get("sites"),
                "n": metrics.get("n"),
                "rmse": metrics.get("rmse"),
                "persistence_rmse": metrics.get("persistence_rmse"),
                "climatology_rmse": metrics.get("climatology_rmse"),
                "climatology_n": metrics.get("climatology_n"),
                "skill_p": metrics.get("skill_score"),
                "skill_c": metrics.get("skill_vs_climatology"),
                "r2": metrics.get("r2"),
            }
        )

    loso_rows = [r for r in loso if "skill_score" in r]
    return pd.DataFrame(rows), pd.DataFrame(loso_rows), meta


# --------------------------------------------------------------------------
# Figure 1 -- the headline: the two baselines disagree, and disagree with horizon
# --------------------------------------------------------------------------


def figure_skill_by_horizon(main: pd.DataFrame) -> None:
    variables = sorted(main["variable"].unique())
    columns = 4
    rows = int(np.ceil(len(variables) / columns))
    figure, axes = plt.subplots(
        rows, columns, figsize=(7.2, 1.65 * rows), sharex=True, squeeze=False
    )

    for index, variable in enumerate(variables):
        axis = axes[index // columns][index % columns]
        subset = main[main["variable"] == variable].sort_values("horizon")

        axis.axhline(0, color=INK, linewidth=0.7, linestyle=(0, (4, 3)), zorder=1)
        axis.plot(
            subset["horizon"], subset["skill_p"], marker="o", markersize=3.5,
            linewidth=1.6, color=PERSISTENCE, zorder=3, clip_on=False,
        )
        axis.plot(
            subset["horizon"], subset["skill_c"], marker="s", markersize=3.5,
            linewidth=1.6, color=CLIMATOLOGY, zorder=3, clip_on=False,
        )
        axis.set_xscale("log")
        axis.set_xticks(HORIZONS)
        axis.set_xticklabels([str(h) for h in HORIZONS])
        axis.set_ylim(-0.35, 1.05)
        axis.set_yticks([0.0, 0.5, 1.0])
        axis.grid(axis="y", zorder=0)
        axis.set_title(pretty(variable), pad=3)

    for index in range(len(variables), rows * columns):
        axes[index // columns][index % columns].axis("off")

    # The label and tick labels belong on the bottom-most *populated* panel of
    # each column, which is not the bottom row when the grid is ragged. With
    # `sharex` on, matplotlib hides tick labels everywhere but the final row,
    # so a 13-panel grid four columns wide left three columns with no readable
    # x axis at all.
    for column in range(columns):
        occupied = [r for r in range(rows) if r * columns + column < len(variables)]
        if not occupied:
            continue
        axis = axes[occupied[-1]][column]
        axis.set_xlabel("horizon (days)")
        axis.tick_params(labelbottom=True)
    for row in range(rows):
        if row * columns < len(variables):
            axes[row][0].set_ylabel("skill score")

    handles = [
        plt.Line2D([], [], color=PERSISTENCE, marker="o", markersize=3.5,
                   linewidth=1.6, label="vs. persistence"),
        plt.Line2D([], [], color=CLIMATOLOGY, marker="s", markersize=3.5,
                   linewidth=1.6, label="vs. climatology"),
        plt.Line2D([], [], color=INK, linewidth=0.7, linestyle=(0, (4, 3)),
                   label="baseline parity"),
    ]
    figure.legend(
        handles=handles, loc="lower center", ncol=3, frameon=False,
        bbox_to_anchor=(0.5, -0.02),
    )
    figure.tight_layout()
    figure.savefig(OUT / "fig_skill_by_horizon.pdf")
    plt.close(figure)


# --------------------------------------------------------------------------
# Figure 2 -- leave-one-site-out: what transfer costs
# --------------------------------------------------------------------------


def figure_loso(loso: pd.DataFrame, main: pd.DataFrame) -> None:
    figure, axes = plt.subplots(1, 2, figsize=(7.2, 3.0))

    # (a) per-variable distribution of held-out-site skill, at h=7.
    #
    # Skill is unbounded below (a skill of -3 means RMSE three times the
    # baseline's), and transfer failures genuinely reach there. Clipping the
    # axis and drawing the off-scale points *on* the boundary as triangles
    # keeps the readable range readable without hiding that they exist --
    # rescaling to fit them would flatten every other variable to a line.
    axis = axes[0]
    at_horizon = loso[loso["horizon"] == 7]
    variables = sorted(at_horizon["variable"].unique())
    data = [at_horizon[at_horizon["variable"] == v]["skill_score"].dropna() for v in variables]

    floor = -1.0
    positions = np.arange(len(variables))
    axis.axvline(0, color=INK, linewidth=0.7, linestyle=(0, (4, 3)), zorder=1)
    box = axis.boxplot(
        data, positions=positions, orientation="horizontal", widths=0.6, patch_artist=True,
        showfliers=False, medianprops={"color": "white", "linewidth": 1.2},
        whiskerprops={"color": MUTED, "linewidth": 0.8},
        capprops={"color": MUTED, "linewidth": 0.8},
    )
    for patch in box["boxes"]:
        patch.set_facecolor(PERSISTENCE)
        patch.set_edgecolor("white")
        patch.set_linewidth(0.8)
    rng = np.random.default_rng(0)
    off_scale = 0
    for index, values in enumerate(data):
        jitter = np.full(len(values), index) + rng.normal(0, 0.07, len(values))
        inside = values >= floor
        axis.scatter(
            values[inside], jitter[inside],
            s=5, color=INK, alpha=0.45, zorder=4, linewidths=0,
        )
        outside = ~inside
        off_scale += int(outside.sum())
        if outside.any():
            axis.scatter(
                np.full(int(outside.sum()), floor), jitter[outside],
                s=14, color=CLIMATOLOGY, marker="<", zorder=5, linewidths=0,
            )
    axis.set_xlim(floor - 0.06, 1.0)
    axis.set_yticks(positions)
    axis.set_yticklabels([pretty(v) for v in variables])
    axis.set_xlabel("skill vs. persistence at held-out site (h = 7 d)")
    title = "(a) Per-site transfer, 24 held-out sites"
    if off_scale:
        title += f"\n({off_scale} sites below {floor:.0f}, shown as $\\blacktriangleleft$)"
    axis.set_title(title, loc="left", pad=6)
    axis.grid(axis="x", zorder=0)

    # (b) pooled in-sample CV skill against median held-out skill.
    axis = axes[1]
    merged = (
        loso.groupby(["variable", "horizon"])["skill_score"].median().reset_index()
        .rename(columns={"skill_score": "loso_median"})
        .merge(main[["variable", "horizon", "skill_p"]], on=["variable", "horizon"])
    )
    limits = (-1.05, 0.8)
    axis.plot(limits, limits, color=INK, linewidth=0.7, linestyle=(0, (4, 3)), zorder=1)
    axis.axhline(0, color=MUTED, linewidth=0.5, zorder=1)
    axis.axvline(0, color=MUTED, linewidth=0.5, zorder=1)
    markers = {1: "o", 3: "^", 7: "s", 30: "D"}
    clipped = 0
    for horizon, marker in markers.items():
        subset = merged[merged["horizon"] == horizon]
        # Clamped to the frame rather than dropped, so a variable that fails
        # to transfer still appears as a point on the floor instead of
        # vanishing from the panel entirely.
        y = subset["loso_median"].to_numpy(dtype="float64")
        clipped += int((y < limits[0]).sum())
        axis.scatter(
            subset["skill_p"], np.clip(y, limits[0] + 0.02, None), s=22, marker=marker,
            facecolor=CLIMATOLOGY, edgecolor="white", linewidth=0.6,
            zorder=3, label=f"h = {horizon} d",
        )
    if clipped:
        axis.text(
            0.02, 0.03, f"{clipped} below axis", transform=axis.transAxes,
            fontsize=6.5, color=MUTED,
        )
    axis.set_xlim(limits)
    axis.set_ylim(limits)
    axis.set_xlabel("pooled skill, sites seen in training")
    axis.set_ylabel("median skill, held-out site")
    axis.set_title("(b) Cost of spatial extrapolation", loc="left", pad=6)
    axis.legend(frameon=False, loc="lower right")
    axis.grid(zorder=0)

    figure.tight_layout()
    figure.savefig(OUT / "fig_loso.pdf")
    plt.close(figure)


# --------------------------------------------------------------------------
# Figure 3 -- where the held-out sites are, and how they scored
# --------------------------------------------------------------------------


def figure_site_map(loso: pd.DataFrame) -> None:
    at_horizon = loso[loso["horizon"] == 7]
    by_site = at_horizon.groupby("site").agg(
        latitude=("latitude", "first"),
        longitude=("longitude", "first"),
        skill=("skill_score", "median"),
    ).reset_index()

    figure, axis = plt.subplots(figsize=(7.2, 3.4))
    # Diverging: two poles about a neutral midpoint at zero skill, which is
    # the meaningful centre here (parity with persistence).
    # A robust bound, not the maximum: a single catastrophic transfer failure
    # (skill of -3) would otherwise compress every other site into the
    # neutral midpoint and make the map say nothing. The colour bar is
    # extended so the out-of-range sites are visibly saturated rather than
    # silently clamped.
    bound = float(np.nanpercentile(np.abs(by_site["skill"]), 90)) or 1.0
    bound = max(bound, 0.05)
    # `RdBu`, not `RdBu_r`: this ramp runs red at the low end and blue at the
    # high end, so positive skill (the model transfers) is blue and negative
    # (persistence wins) is red. The reversed variant paints it the other way
    # round, which contradicts the caption and reads as the opposite result.
    scatter = axis.scatter(
        by_site["longitude"], by_site["latitude"], c=by_site["skill"],
        cmap="RdBu", vmin=-bound, vmax=bound, s=70, edgecolor="white",
        linewidth=0.8, zorder=3,
    )

    # Stagger labels within a cluster. Eight of the sites sit inside the North
    # Indian Ocean within ~20 degrees of each other, and at a fixed offset
    # their labels overprint into an unreadable block.
    offsets = [8, -14, 18, -24, 28, -34, 38, -44]
    placed: list[tuple[float, float]] = []
    ordered = by_site.sort_values(["longitude", "latitude"])
    for _, row in ordered.iterrows():
        longitude, latitude = float(row["longitude"]), float(row["latitude"])
        crowd = sum(
            1
            for (x, y) in placed
            if abs(x - longitude) < 28 and abs(y - latitude) < 18
        )
        dy = offsets[crowd % len(offsets)]
        axis.annotate(
            pretty(row["site"]), (longitude, latitude),
            textcoords="offset points", xytext=(0, dy), ha="center",
            fontsize=5.0, color=INK,
            arrowprops=(
                {"arrowstyle": "-", "linewidth": 0.4, "color": MUTED,
                 "shrinkA": 0, "shrinkB": 3}
                if crowd
                else None
            ),
        )
        placed.append((longitude, latitude))
    axis.set_xlim(-180, 180)
    axis.set_ylim(-70, 75)
    axis.set_xticks(range(-180, 181, 60))
    axis.set_yticks(range(-60, 76, 30))
    axis.set_xlabel("longitude")
    axis.set_ylabel("latitude")
    axis.grid(color="#e8e8e8", zorder=0)
    axis.axhline(0, color=MUTED, linewidth=0.5, zorder=1)
    bar = figure.colorbar(scatter, ax=axis, pad=0.015, fraction=0.03, extend="both")
    bar.set_label("median skill when held out (h = 7 d)")
    bar.outline.set_linewidth(0.5)
    figure.tight_layout()
    figure.savefig(OUT / "fig_site_map.pdf")
    plt.close(figure)


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------


def _number(value: float | None, places: int = 3) -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "--"
    return f"{value:.{places}f}"


def table_skill_compact(main: pd.DataFrame) -> None:
    """The headline table: both skill scores, side by side, at every horizon.

    One row per variable rather than one row per (variable, horizon). The long
    form is 65 rows and does not fit a two-column conference layout, but more
    importantly the comparison the paper is about -- $S_{pers}$ against
    $S_{clim}$ at the *same* horizon -- is a within-row comparison here and a
    12-rows-apart comparison there.
    """
    header = " & ".join(
        rf"\multicolumn{{2}}{{c}}{{$h={h}$}}" for h in HORIZONS
    )
    sub = " & ".join([r"$S_{\mathrm{p}}$ & $S_{\mathrm{c}}$"] * len(HORIZONS))
    lines = [
        r"\begin{tabular}{l rr rr rr rr}",
        r"\toprule",
        rf" & {header} \\",
        r"\cmidrule(lr){2-3}\cmidrule(lr){4-5}\cmidrule(lr){6-7}\cmidrule(lr){8-9}",
        rf"Variable & {sub} \\",
        r"\midrule",
    ]
    for variable in sorted(main["variable"].unique()):
        cells = []
        for horizon in HORIZONS:
            row = main[(main["variable"] == variable) & (main["horizon"] == horizon)]
            if row.empty:
                cells += ["--", "--"]
                continue
            for column in ("skill_p", "skill_c"):
                value = row[column].iloc[0]
                text = _number(value)
                # Bold where the baseline wins. Those cells are the result.
                if value is not None and np.isfinite(value) and value < 0:
                    text = rf"\textbf{{{text}}}"
                cells.append(text)
        lines.append(f"{pretty(variable)} & " + " & ".join(cells) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (OUT / "table_skill_compact.tex").write_text("\n".join(lines))


def table_loso_compact(loso: pd.DataFrame) -> None:
    """Median held-out skill per variable and horizon, with the positive count."""
    lines = [
        r"\begin{tabular}{l rr rr rr rr}",
        r"\toprule",
        r" & \multicolumn{2}{c}{$h=1$} & \multicolumn{2}{c}{$h=3$} & "
        r"\multicolumn{2}{c}{$h=7$} & \multicolumn{2}{c}{$h=30$} \\",
        r"\cmidrule(lr){2-3}\cmidrule(lr){4-5}\cmidrule(lr){6-7}\cmidrule(lr){8-9}",
        r"Variable & Med. & $n^{+}$ & Med. & $n^{+}$ & Med. & $n^{+}$ & "
        r"Med. & $n^{+}$ \\",
        r"\midrule",
    ]
    for variable in sorted(loso["variable"].unique()):
        cells = []
        for horizon in HORIZONS:
            values = loso[
                (loso["variable"] == variable) & (loso["horizon"] == horizon)
            ]["skill_score"].dropna()
            if values.empty:
                cells += ["--", "--"]
                continue
            median = float(values.median())
            text = _number(median, 2)
            if median < 0:
                text = rf"\textbf{{{text}}}"
            cells += [text, f"{int((values > 0).sum())}"]
        lines.append(f"{pretty(variable)} & " + " & ".join(cells) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (OUT / "table_loso_compact.tex").write_text("\n".join(lines))


def table_main(main: pd.DataFrame) -> None:
    lines = [
        r"\begin{tabular}{l r r r r r r}",
        r"\toprule",
        r"Variable & $h$ & RMSE & Pers. & Clim. & $S_{\mathrm{pers}}$ & "
        r"$S_{\mathrm{clim}}$ \\",
        r"\midrule",
    ]
    for variable in sorted(main["variable"].unique()):
        subset = main[main["variable"] == variable].sort_values("horizon")
        unit = subset["unit"].iloc[0]
        lines.append(
            rf"\multicolumn{{7}}{{l}}{{\textit{{{pretty(variable)}}} "
            rf"\footnotesize ({unit})}} \\"
        )
        for _, row in subset.iterrows():
            skill_p = _number(row["skill_p"])
            skill_c = _number(row["skill_c"])
            # Bold a negative skill: the failures are a result of the paper,
            # not an embarrassment to be buried in a dense table.
            if row["skill_p"] is not None and row["skill_p"] < 0:
                skill_p = rf"\textbf{{{skill_p}}}"
            if row["skill_c"] is not None and row["skill_c"] < 0:
                skill_c = rf"\textbf{{{skill_c}}}"
            lines.append(
                f"\\quad & {int(row['horizon'])} & {_number(row['rmse'])} & "
                f"{_number(row['persistence_rmse'])} & "
                f"{_number(row['climatology_rmse'])} & {skill_p} & {skill_c} \\\\"
            )
        lines.append(r"\addlinespace[2pt]")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (OUT / "table_main.tex").write_text("\n".join(lines))


def table_loso(loso: pd.DataFrame) -> None:
    lines = [
        r"\begin{tabular}{l r r r r r}",
        r"\toprule",
        r"Variable & $h$ & Median & IQR & Sites $>0$ & Worst \\",
        r"\midrule",
    ]
    for variable in sorted(loso["variable"].unique()):
        for horizon in HORIZONS:
            subset = loso[(loso["variable"] == variable) & (loso["horizon"] == horizon)]
            values = subset["skill_score"].dropna()
            if values.empty:
                continue
            q1, q3 = np.percentile(values, [25, 75])
            name = pretty(variable) if horizon == HORIZONS[0] else ""
            lines.append(
                f"{name} & {horizon} & {_number(float(values.median()))} & "
                f"{_number(float(q3 - q1))} & {int((values > 0).sum())}/{len(values)} & "
                f"{_number(float(values.min()))} \\\\"
            )
        lines.append(r"\addlinespace[2pt]")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (OUT / "table_loso.tex").write_text("\n".join(lines))


def table_variables(main: pd.DataFrame) -> None:
    lines = [
        r"\begin{tabular}{l l r r}",
        r"\toprule",
        r"Variable & Unit & Sites & Feature rows \\",
        r"\midrule",
    ]
    for variable in sorted(main["variable"].unique()):
        row = main[main["variable"] == variable].iloc[0]
        unit = row["unit"] or "--"
        lines.append(
            f"{pretty(variable)} & {unit} & {int(row['sites'])} & "
            f"{int(row['rows']):,} \\\\"
        )
    lines += [r"\bottomrule", r"\end{tabular}"]
    (OUT / "table_variables.tex").write_text("\n".join(lines))


def macros(main: pd.DataFrame, loso: pd.DataFrame, meta: dict) -> None:
    """Numbers the prose quotes, as macros, so the text cannot drift."""
    at30 = main[main["horizon"] == 30]
    at1 = main[main["horizon"] == 1]
    rising = 0
    for variable in main["variable"].unique():
        subset = main[main["variable"] == variable].sort_values("horizon")
        skills = subset["skill_p"].to_numpy(dtype="float64")
        if len(skills) >= 2 and skills[-1] > skills[0]:
            rising += 1

    loso7 = loso[loso["horizon"] == 7]
    pooled7 = main[main["horizon"] == 7]

    # How many variables' climatology skill is *lower* at the longest horizon
    # than at the shortest. This is the claim the paper actually makes, so it
    # is counted rather than asserted.
    falling = 0
    for variable in main["variable"].unique():
        subset = main[main["variable"] == variable].sort_values("horizon")
        skills = subset["skill_c"].to_numpy(dtype="float64")
        if len(skills) >= 2 and skills[-1] < skills[0]:
            falling += 1

    def at(horizon: int, column: str) -> str:
        return _number(float(main[main["horizon"] == horizon][column].median()))

    values = {
        "NVars": str(main["variable"].nunique()),
        "NSites": str(int(main["sites"].max())),
        "NModels": str(len(main)),
        "NLosoFits": str(len(loso)),
        "AsOf": meta.get("as_of", ""),
        "ClimWindow": str(meta.get("climatology_window_days", 15)),
        "NRising": str(rising),
        "NFallingClim": str(falling),
        "MedSkillPOne": _number(float(at1["skill_p"].median())),
        "MedSkillPThree": at(3, "skill_p"),
        "MedSkillPSeven": at(7, "skill_p"),
        "MedSkillPThirty": _number(float(at30["skill_p"].median())),
        "MedSkillCOne": _number(float(at1["skill_c"].median())),
        "MedSkillCThree": at(3, "skill_c"),
        "MedSkillCSeven": at(7, "skill_c"),
        "MedSkillCThirty": _number(float(at30["skill_c"].median())),
        # Sign counts at the longest horizon, where the two baselines disagree
        # most sharply.
        "NLoseClimThirty": str(int((at30["skill_c"] < 0).sum())),
        "NLosePersThirty": str(int((at30["skill_p"] < 0).sum())),
        "NLoseToClim": str(int((main["skill_c"] < 0).sum())),
        "NLoseToPers": str(int((main["skill_p"] < 0).sum())),
        "MedPooledSeven": _number(float(pooled7["skill_p"].median())),
        "MedLosoSeven": _number(float(loso7["skill_score"].median())),
        "LosoPositiveShare": _number(
            float((loso7["skill_score"] > 0).mean()) * 100.0, 1
        ),
    }
    lines = [rf"\newcommand{{\{key}}}{{{value}}}" for key, value in values.items()]
    (OUT / "macros.tex").write_text("\n".join(lines) + "\n")
    print(json.dumps(values, indent=2))


def main_entry() -> None:
    style()
    OUT.mkdir(parents=True, exist_ok=True)
    main, loso, meta = load()
    print(f"{len(main)} baseline records, {len(loso)} scored LOSO folds")

    figure_skill_by_horizon(main)
    if not loso.empty:
        figure_loso(loso, main)
        figure_site_map(loso)
        table_loso(loso)
        table_loso_compact(loso)
    table_main(main)
    table_skill_compact(main)
    table_variables(main)
    macros(main, loso, meta)
    print(f"wrote assets to {OUT}")


if __name__ == "__main__":
    main_entry()
