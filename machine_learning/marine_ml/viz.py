"""Shared plotting style for the analysis notebooks.

One validated palette and one set of matplotlib defaults, so every figure in
every notebook reads as part of the same system rather than as whatever
matplotlib happened to do that day.

The palette is not a taste choice — it was checked with a colour-vision
validator against a white notebook surface:

* **Categorical**, used for series identity. The slot *order* is the
  colour-blind-safety mechanism, so assign slots in order and never cycle
  past the list. Adjacent-pair separation (bars, lines) passes for all five
  slots; for scatter and map contexts, where every pair is visible at once,
  only the first **three** slots clear the floor — past three, facet into
  small multiples instead of adding a fourth colour.
* **Sequential**, one hue light to dark, for magnitude. Never a rainbow: a
  multi-hue ramp invents category boundaries the data does not have.
* **Diverging**, two opposed hues with a *neutral grey* midpoint, for
  quantities with a meaningful zero (anomalies). The midpoint must read as
  "nothing"; a hue there would imply a third state.

Three of the categorical slots sit below 3:1 contrast on white. That is
allowed only because every figure here also carries visible labels — legends,
axis text, or a printed table — so colour never carries meaning alone.
"""

from __future__ import annotations

from matplotlib.colors import LinearSegmentedColormap

# --------------------------------------------------------------------------
# Palette
# --------------------------------------------------------------------------

# Assign in order. See the module docstring for the 3-slot scatter cap.
CATEGORICAL = [
    "#2a78d6",  # 1 blue
    "#eb6834",  # 2 orange
    "#1baf7a",  # 3 aqua
    "#eda100",  # 4 yellow
    "#e87ba4",  # 5 magenta
    "#008300",  # 6 green
    "#4a3aa7",  # 7 violet
    "#e34948",  # 8 red
]

# Safe for scatter/map contexts, where all pairs are simultaneously visible.
CATEGORICAL_ALL_PAIRS = CATEGORICAL[:3]

PRESENCE = CATEGORICAL[0]      # blue  — the positive class
BACKGROUND = "#9a9a94"         # grey  — background points are context, not a rival series
ACCENT = CATEGORICAL[1]        # orange — the one thing being called out

# Ink and chrome. Recessive by design: the data should be the darkest thing.
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#8a8a84"
GRID = "#e8e8e4"
SURFACE = "#ffffff"

_SEQUENTIAL_STEPS = [
    "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
    "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b",
]

#: Magnitude. Light = near zero.
SEQUENTIAL = LinearSegmentedColormap.from_list("marine_seq", _SEQUENTIAL_STEPS)

#: Anomalies. Blue (cool/low) ↔ grey (nothing) ↔ red (warm/high).
DIVERGING = LinearSegmentedColormap.from_list(
    "marine_div",
    ["#0d366b", "#2a78d6", "#9ec5f4", "#f0efec", "#f3a3a2", "#e34948", "#8f2222"],
)


def species_colors(keys) -> dict:
    """Map species keys to categorical slots, in a fixed order.

    Colour follows the entity, not its rank — so a figure that drops a species
    must not repaint the survivors. Sorting the keys makes the assignment
    depend only on identity.
    """
    return {key: CATEGORICAL[i % len(CATEGORICAL)] for i, key in enumerate(sorted(keys))}


# --------------------------------------------------------------------------
# Matplotlib defaults
# --------------------------------------------------------------------------


def use_house_style() -> None:
    """Apply the shared figure defaults. Call once per notebook."""
    import matplotlib as mpl

    mpl.rcParams.update({
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "figure.dpi": 110,
        "savefig.dpi": 150,

        "font.size": 10,
        "axes.titlesize": 12,
        "axes.titleweight": "semibold",
        "axes.titlepad": 10,
        "axes.labelsize": 10,
        "axes.labelcolor": INK_SECONDARY,
        "text.color": INK,

        # Recessive chrome: only left and bottom rules, hairline weight.
        "axes.edgecolor": GRID,
        "axes.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,

        # Solid hairline grid. Never dashed — dashing reads as "threshold".
        "axes.grid": True,
        "axes.grid.axis": "y",
        "grid.color": GRID,
        "grid.linewidth": 0.8,
        "grid.linestyle": "-",
        "grid.alpha": 1.0,

        "xtick.color": INK_MUTED,
        "ytick.color": INK_MUTED,
        "xtick.labelcolor": INK_SECONDARY,
        "ytick.labelcolor": INK_SECONDARY,
        "xtick.direction": "out",
        "ytick.direction": "out",
        "xtick.major.size": 0,
        "ytick.major.size": 0,

        "lines.linewidth": 2.0,
        "lines.markersize": 5,

        "legend.frameon": False,
        "legend.fontsize": 9,

        "axes.prop_cycle": mpl.cycler(color=CATEGORICAL),
    })


def label_axes(ax, title=None, xlabel=None, ylabel=None, subtitle=None) -> None:
    """Title/axis labels with a consistent hierarchy.

    A subtitle is where the *interpretation* goes — the sentence telling the
    reader what they are supposed to notice. Charts that omit it make the
    reader re-derive the point every time.
    """
    if title:
        ax.set_title(title, loc="left", color=INK)
    if subtitle:
        ax.text(
            0.0, 1.02, subtitle, transform=ax.transAxes,
            fontsize=9, color=INK_SECONDARY, va="bottom", ha="left",
        )
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)


def annotate_land(ax, bathymetry, region, color="#efeeea") -> None:
    """Shade land on a map axis, so coastal patterns are readable as coastal."""
    elevation = bathymetry["elevation"]
    ax.contourf(
        elevation["longitude"], elevation["latitude"], elevation.values,
        levels=[0, 1e5], colors=[color], zorder=0,
    )
    ax.set_xlim(region.west, region.east)
    ax.set_ylim(region.south, region.north)
    ax.set_aspect("equal")
    ax.grid(False)
