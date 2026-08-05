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
