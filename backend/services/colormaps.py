"""Generic continuous-value -> RGB colormap builder.

Deliberately not SST-specific: `build_colormap` takes any list of
(value, RGB) control points and returns a vectorized function usable for any
scalar field (chlorophyll-a, salinity, wave height, ...), so a future variable
just needs its own stop list, not a new rendering path.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

ColorStop = tuple[float, tuple[int, int, int]]


def build_colormap(stops: list[ColorStop]) -> Callable[[np.ndarray], np.ndarray]:
    """Returns f(values) -> uint8 array of shape (*values.shape, 3).

    Piecewise-linear per RGB channel via np.interp, which also clamps
    out-of-range inputs to the first/last stop (no extrapolation past the
    color scale's own endpoints). NaN inputs propagate as NaN through
    np.interp; callers are responsible for treating those as transparent.
    """
    sorted_stops = sorted(stops, key=lambda s: s[0])
    values = np.array([s[0] for s in sorted_stops], dtype=np.float64)
    channels = np.array([s[1] for s in sorted_stops], dtype=np.float64)  # (n, 3)

    def colormap(x: np.ndarray) -> np.ndarray:
        flat = x.reshape(-1).astype(np.float64)
        rgb = np.stack(
            [np.interp(flat, values, channels[:, c]) for c in range(3)], axis=-1
        )
        return rgb.reshape(*x.shape, 3)

    return colormap


# Windy-style SST scale: -2C deep purple through 35C red. Kept in sync by hand
# with the CSS hex stops in frontend/src/features/map/layers/layerRegistry.ts
# (the `sst` entry's gradient legend) — two different representations (RGB
# tuples for numpy interpolation vs. CSS hex for a static bar), not
# derivable from one shared source without a build step.
SST_COLORMAP_STOPS: list[ColorStop] = [
    (-2, (59, 15, 112)),  # deep purple
    (0, (30, 58, 138)),  # dark blue
    (5, (29, 78, 216)),  # blue
    (10, (6, 182, 212)),  # cyan
    (15, (20, 184, 166)),  # turquoise
    (20, (34, 197, 94)),  # green
    (25, (234, 179, 8)),  # yellow
    (30, (249, 115, 22)),  # orange
    (35, (220, 38, 38)),  # red
]

SST_COLORMAP = build_colormap(SST_COLORMAP_STOPS)


# Normalised ramps, defined on a unit domain so one colormap serves every
# variable: the caller scales its values into the domain and the same object
# renders sea surface temperature, chlorophyll or wave height. A per-variable
# stop list would mean a new entry every time a variable is trained, which is
# exactly the branching the forecasting engine exists to avoid.
#
# These three are consumed only by `services/forecast_tiles.py` (checked
# 2026-09-06: `predictions.py` and `copernicus_sst.py` carry their own stop
# lists). That is what makes it safe for this file to give the *forecast* map
# its own palette, distinct from every observed layer, without that choice
# leaking onto anything else — a forecast is model output, not measurement,
# and a reader comparing the two benefits from the map itself saying so before
# they read a single number. Chosen from `matplotlib`'s `plasma` (sequential)
# and ColorBrewer's `PRGn` (diverging), both published perceptually-uniform /
# colour-vision-deficiency-safe scales, rather than picked by eye — the same
# bar the viridis/RdBu pair they replace was held to.

# Sequential, on [0, 1]. Plasma control points: violet through magenta and
# orange to a pale gold, monotonic in lightness like viridis but routed
# through an entirely different hue family, so a forecast reads as its own
# kind of thing next to an observed layer's blue-green-yellow.
SEQUENTIAL_STOPS: list[ColorStop] = [
    (0.00, (13, 8, 135)),
    (0.25, (126, 3, 168)),
    (0.50, (204, 71, 120)),
    (0.75, (248, 149, 64)),
    (1.00, (240, 249, 33)),
]
SEQUENTIAL_COLORMAP = build_colormap(SEQUENTIAL_STOPS)

# Diverging, on [-1, 1], for a *change* or anomaly field. Purple-neutral-green
# (ColorBrewer PRGn) rather than blue-red: still a near-white centre so "no
# change" stays visually absent and the sign of the change is the first thing
# read, but a purple/green forecast delta no longer looks like the same
# quantity as a blue/red *observed* anomaly would, which matters exactly when
# both are on screen together. The caller must keep the domain symmetric —
# an asymmetric one would put zero off the neutral point.
DIVERGING_STOPS: list[ColorStop] = [
    (-1.00, (64, 0, 75)),
    (-0.60, (118, 42, 131)),
    (-0.25, (153, 112, 171)),
    (-0.05, (231, 212, 232)),
    (0.00, (247, 247, 247)),
    (0.05, (217, 240, 211)),
    (0.25, (166, 219, 160)),
    (0.60, (90, 174, 97)),
    (1.00, (27, 120, 55)),
]
DIVERGING_COLORMAP = build_colormap(DIVERGING_STOPS)

# Cyclic, on [0, 1], for a compass bearing. The first and last stop are the
# *same colour* by construction — that is what makes it cyclic, and it is the
# whole point: on a sequential ramp 359 degrees and 1 degree sit at opposite
# ends of the scale, so a heading nudging across north reads as the largest
# possible change rather than the smallest.
#
# Hue cycles at fixed saturation and value rather than following a perceptual
# cyclic map like twilight, for one reason specific to this app: twilight and
# its relatives pass through near-black at a quarter turn, and this repo has
# already measured what a near-black ramp end does over the Abyss basemap's
# #030f1e ocean — 1.13:1, indistinguishable from bare basemap. Every stop here
# composites at >= 3.34:1 against it, and opposite headings stay at least 246
# apart in RGB, so the ramp reads as a direction rather than as a smear.
#
# This is the same validated ring of six hues as before, rotated 180 degrees
# (0 degrees now reads cyan instead of red) rather than re-derived: every
# contrast and separation guarantee above is unchanged because it is the same
# set of colours, just reassigned to different headings — which is enough to
# stop a forecast bearing looking identical to how one might be drawn
# elsewhere, without re-measuring a ramp that was already correct.
#
# The tradeoff, stated: hue at constant lightness is not perceptually uniform,
# so equal angular steps are not equal perceptual steps. For a bearing that is
# acceptable — the reader is judging "which way", not "how much".
CYCLIC_STOPS: list[ColorStop] = [
    (0.000, (68, 242, 242)),
    (0.125, (68, 111, 242)),
    (0.250, (155, 68, 242)),
    (0.375, (242, 68, 199)),
    (0.500, (242, 68, 68)),
    (0.625, (242, 199, 68)),
    (0.750, (155, 242, 68)),
    (0.875, (68, 242, 111)),
    (1.000, (68, 242, 242)),
]
CYCLIC_COLORMAP = build_colormap(CYCLIC_STOPS)
