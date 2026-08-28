"""Descriptive analytics for one variable at one point.

The counterpart to `forecasting/`: that package answers "what will this be",
this one answers "what has it been". Both read the same history through
`forecasting.history`, so a metric page and a forecast never disagree about
what the record says.

Kept out of `forecasting/` deliberately. Nothing here fits or serves a model —
it is pandas over a series — and folding it in would blur a package whose
whole claim is that it is a modelling engine. The dependency runs one way:
`services/metrics/` imports `forecasting.history`, never the reverse.
"""

from __future__ import annotations


class MetricsError(RuntimeError):
    """Base for this package's errors.

    Matches the `XError(RuntimeError)` convention every other service module
    uses, so `routers/metrics.py` can stay thin and never leak a pandas or
    provider traceback to a client.
    """
