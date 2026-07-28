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
