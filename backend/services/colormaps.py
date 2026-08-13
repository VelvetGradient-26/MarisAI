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

# Sequential, on [0, 1]. Perceptually uniform (viridis control points), so
# equal steps in value read as equal steps in colour and the scale stays
# legible in greyscale and to colour-vision deficiencies.
SEQUENTIAL_STOPS: list[ColorStop] = [
    (0.00, (68, 1, 84)),
    (0.25, (59, 82, 139)),
    (0.50, (33, 145, 140)),
    (0.75, (94, 201, 98)),
    (1.00, (253, 231, 37)),
]
SEQUENTIAL_COLORMAP = build_colormap(SEQUENTIAL_STOPS)

# Diverging, on [-1, 1], for a *change* or anomaly field. Blue-neutral-red with
# a near-white centre, so the sign of the change is the first thing read and
# "no change" is visually absent rather than a colour of its own. The caller
# must scale symmetrically — an asymmetric domain would put zero off the
# neutral point and make a warming ocean out of a longer positive tail.
DIVERGING_STOPS: list[ColorStop] = [
    (-1.00, (5, 48, 97)),
    (-0.60, (33, 102, 172)),
    (-0.25, (103, 169, 207)),
    (-0.05, (209, 229, 240)),
    (0.00, (247, 247, 247)),
    (0.05, (253, 219, 199)),
    (0.25, (239, 138, 98)),
    (0.60, (178, 24, 43)),
    (1.00, (103, 0, 31)),
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
# composites at >= 3.34:1 against it (weakest is 270 degrees at 3.34), and
# opposite headings stay at least 246 apart in RGB, so the ramp reads as a
# direction rather than as a smear.
#
# The tradeoff, stated: hue at constant lightness is not perceptually uniform,
# so equal angular steps are not equal perceptual steps. For a bearing that is
# acceptable — the reader is judging "which way", not "how much".
CYCLIC_STOPS: list[ColorStop] = [
    (0.000, (242, 68, 68)),
    (0.125, (242, 199, 68)),
    (0.250, (155, 242, 68)),
    (0.375, (68, 242, 111)),
    (0.500, (68, 242, 242)),
    (0.625, (68, 111, 242)),
    (0.750, (155, 68, 242)),
    (0.875, (242, 68, 199)),
    (1.000, (242, 68, 68)),
]
CYCLIC_COLORMAP = build_colormap(CYCLIC_STOPS)
