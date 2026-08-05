"""MarisAI forecasting engine.

One framework that forecasts *any* variable the platform carries, rather than
one model implementation per variable. The shape is:

    variable + point  ->  history adapter  ->  features  ->  one trained
    LightGBM per (variable, horizon)  ->  prediction + interval + drivers

Nothing in this package knows what "sea surface temperature" means. A variable
is a row in `config/forecasting.yaml` naming a code the download registry
already resolves, so adding one is configuration, not code.

Public surface is deliberately small — `api.router` for HTTP, `predictor` and
`trainer` for programmatic use. Everything else is an implementation detail of
those three.
"""

from __future__ import annotations

__all__ = ["ForecastingError"]


class ForecastingError(RuntimeError):
    """Base for every error this package raises.

    Mirrors the `XError(RuntimeError)` convention every other service module
    in this backend uses, so `api.py` can stay thin: it catches the specific
    subclasses it has status codes for, and this base for everything else,
    and never lets a raw LightGBM/xarray traceback reach a client.
    """
