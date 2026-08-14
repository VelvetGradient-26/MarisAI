"""Shared setup for the research notebooks: paths, data loading, plot style.

Every notebook starts with

    import marisviz as mv
    mv.setup()

which fixes the matplotlib configuration once so all four notebooks produce
figures that look like they came from the same study — and, importantly, at a
resolution that survives being dropped into a slide or printed.

The module also puts `backend/` on `sys.path`, so the notebooks import the
*actual* implementation (`forecasting.climatology`,
`forecasting.feature_engineering`) rather than re-deriving it. A notebook that
reimplements the method it is documenting can agree with the paper while the
shipped code disagrees with both.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Paths -- resolved from this file, never from the notebook's cwd, which
# differs between `jupyter lab`, `jupyter notebook` and nbconvert.
# --------------------------------------------------------------------------

NOTEBOOKS = Path(__file__).resolve().parent
RESEARCH = NOTEBOOKS.parent
REPO = RESEARCH.parent
BACKEND = REPO / "backend"
DATA = RESEARCH / "data"
RESULTS = BACKEND / "models" / "forecasting" / "_reports" / "paper"
FIGURES = NOTEBOOKS / "figures"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


# --------------------------------------------------------------------------
# Palette
# --------------------------------------------------------------------------

# The two baselines are the only categorical pair in this study, and these are
# the exact hues used in the paper. Validated for colour-vision deficiency:
# dE 21.7 (protan), 29.9 (tritan), 29.8 normal-vision separation, both >= 3:1
# against white. Do not swap them for defaults -- the figures here and the
# figures in the manuscript are meant to be recognisably the same study.
PERSISTENCE = "#1f6fb2"
CLIMATOLOGY = "#d1611f"
MODEL = "#2f7d5a"
INK = "#10202a"
MUTED = "#6b8390"
RULE = "#d8e2e6"

# Sequential and diverging ramps, named so a notebook never picks one ad hoc.
SEQUENTIAL = "viridis"
DIVERGING = "RdBu"  # low = red, high = blue: positive skill reads blue


def setup(dpi: int = 140, save_dpi: int = 300) -> None:
    """High-resolution, consistent matplotlib configuration.

    `figure.dpi` governs on-screen size in the notebook; `savefig.dpi` governs
    exported files, and is set to 300 so a figure dropped into a slide or a
    print submission is not resampled mush. Retina inline format is requested
    where IPython is present.
    """
    mpl.rcParams.update(
        {
            # Resolution
            "figure.dpi": dpi,
            "savefig.dpi": save_dpi,
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.03,
            "savefig.facecolor": "white",
            "figure.facecolor": "white",
            "figure.figsize": (7.0, 4.0),
            # Type -- a serif face, matching the manuscript
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
            # Recessive chrome: the data should be the darkest thing on the page
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
            "lines.linewidth": 1.8,
            "lines.markersize": 5,
            "axes.prop_cycle": mpl.cycler(
                color=[PERSISTENCE, CLIMATOLOGY, MODEL, "#7b5aa6", "#a8341a"]
            ),
        }
    )
    try:  # only meaningful inside IPython; harmless under nbconvert/CLI
        from IPython.display import set_matplotlib_formats  # noqa: PLC0415

        set_matplotlib_formats("retina")
    except Exception:  # noqa: BLE001 - purely cosmetic
        pass

    FIGURES.mkdir(exist_ok=True)
    pd.set_option("display.max_columns", 60)
    pd.set_option("display.width", 120)


def save(figure: plt.Figure, name: str) -> Path:
    """Write a figure to `notebooks/figures/` at print resolution."""
    FIGURES.mkdir(exist_ok=True)
    path = FIGURES / f"{name}.png"
    figure.savefig(path)
    return path


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------


def load_series() -> pd.DataFrame:
    """The tidy cleaned point series: one row per variable/site/field/time.

    Exported by `backend/scripts/export_research_dataset.py` so these notebooks
    run without Copernicus credentials or a populated history cache.
    """
    frame = pd.read_parquet(DATA / "point_series.parquet")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    return frame


def load_variables() -> pd.DataFrame:
    return pd.DataFrame(json.loads((DATA / "variables.json").read_text()))


def load_sites() -> pd.DataFrame:
    return pd.read_csv(DATA / "sites.csv")


def target_panel(series: pd.DataFrame, variable: str) -> pd.DataFrame:
    """One variable's target field, wide: rows are dates, columns are sites."""
    subset = series[(series["variable"] == variable) & (series["role"] == "target")]
    return subset.pivot_table(
        index="timestamp", columns="site", values="value", observed=True
    )


def load_results() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """The experiment output the manuscript is built from."""
    baselines = json.loads((RESULTS / "baselines.json").read_text())
    loso = json.loads((RESULTS / "loso.json").read_text())
    meta = json.loads((RESULTS / "meta.json").read_text())

    rows = []
    for entry in baselines:
        if "metrics" not in entry:
            continue
        m = entry["metrics"]
        rows.append(
            {
                "variable": entry["variable"],
                "horizon": entry["horizon"],
                "unit": entry.get("unit", ""),
                "rmse": m.get("rmse"),
                "persistence_rmse": m.get("persistence_rmse"),
                "climatology_rmse": m.get("climatology_rmse"),
                "skill_p": m.get("skill_score"),
                "skill_c": m.get("skill_vs_climatology"),
            }
        )
    return (
        pd.DataFrame(rows),
        pd.DataFrame([r for r in loso if "skill_score" in r]),
        meta,
    )


# --------------------------------------------------------------------------
# Small analysis helpers used by more than one notebook
# --------------------------------------------------------------------------


def autocorrelation(values: pd.Series | np.ndarray, max_lag: int = 60) -> np.ndarray:
    """Sample autocorrelation at lags 0..max_lag, NaN-safe.

    Written out rather than pulled from statsmodels: it is eight lines, and the
    repository's convention is to avoid a dependency for a single function.
    """
    x = np.asarray(values, dtype="float64")
    x = x[np.isfinite(x)]
    if len(x) < max_lag + 2:
        return np.full(max_lag + 1, np.nan)
    x = x - x.mean()
    denominator = float(np.dot(x, x))
    if denominator == 0:
        return np.full(max_lag + 1, np.nan)
    return np.array(
        [float(np.dot(x[: len(x) - k], x[k:])) / denominator for k in range(max_lag + 1)]
    )


def pretty(name: str) -> str:
    return name.replace("_", " ")


def skill(rmse: float, reference_rmse: float) -> float:
    """1 - (RMSE/RMSE_ref)^2. Positive means the model beats the reference."""
    if not reference_rmse:
        return float("nan")
    return 1.0 - (rmse**2) / (reference_rmse**2)
