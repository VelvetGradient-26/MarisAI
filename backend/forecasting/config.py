"""Configuration for the forecasting engine — the file that makes adding a
variable a config change rather than a code change.

Everything that varies per variable is a key in `config/forecasting.yaml`:
which registry code supplies its history, which other variables are useful as
covariates, how far ahead it can usefully be forecast, how its outliers should
be treated. Nothing downstream of this module branches on a variable name.

Two design points worth stating, because they are what keeps the promise real:

* **Labels, units and providers are not repeated here.** They already exist in
  `services/download/registry.py`, which the loader validates every configured
  code against. A typo, or a variable whose provider was never implemented,
  fails at load with a message naming it — not at 3am inside a training run.
* **Defaults are inherited, not copied.** A variable block may be empty; it
  then gets the global feature set, horizons and windows. The 30 shipped
  variables mostly *are* empty, which is the point: the interesting config is
  the handful of genuine per-variable facts (chlorophyll is log-scaled,
  directions are circular, waves are 3-hourly).
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any, Literal, cast

import yaml
from pydantic import BaseModel, Field, model_validator

from forecasting import ForecastingError
from services.download.registry import VARIABLE_REGISTRY

CONFIG_PATH = Path(__file__).resolve().parent / "config" / "forecasting.yaml"

# Named so the default_factory below can be annotated with it; pydantic needs
# the Literal element type, and a bare list literal infers as list[str].
RollingStatistic = Literal["mean", "std", "min", "max"]


class ConfigError(ForecastingError):
    """The YAML is missing, malformed, or names something that doesn't exist."""


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------


class FeatureConfig(BaseModel):
    """Which derived columns the feature builder emits.

    All of these are trailing by construction — see `feature_engineering.py`.
    The only forward shift in this package is the target itself.
    """

    lags: list[int] = Field(default_factory=lambda: [1, 3, 7, 14, 30])
    rolling_windows: list[int] = Field(default_factory=lambda: [7, 14, 30])
    rolling_statistics: list[RollingStatistic] = Field(
        # Annotated rather than a bare list literal: without it the lambda
        # infers as list[str], which does not satisfy the Literal element type.
        default_factory=lambda: cast(
            list[RollingStatistic], ["mean", "std", "min", "max"]
        )
    )
    # First difference, percentage change and the slope of a trailing linear
    # fit. Cheap, and they carry the "rising fast from a low base" signal that
    # a level-only feature set cannot express.
    differences: bool = True
    trend_windows: list[int] = Field(default_factory=lambda: [7, 30])
    calendar: bool = True
    cyclical: bool = True
    static: bool = True

    @model_validator(mode="after")
    def _check_positive(self) -> FeatureConfig:
        for name, values in (
            ("lags", self.lags),
            ("rolling_windows", self.rolling_windows),
            ("trend_windows", self.trend_windows),
        ):
            if any(value < 1 for value in values):
                raise ValueError(f"{name} must all be >= 1")
        return self

    @property
    def max_lookback_days(self) -> int:
        """Longest trailing window any feature needs.

        The history fetch adds this to the requested window, so the first row
        the model actually scores has every feature populated rather than a
        third of them NaN.
        """
        return max([1, *self.lags, *self.rolling_windows, *self.trend_windows])


class ValidationConfig(BaseModel):
    """Rolling-origin settings. Never a random split — see `evaluator.py`."""

    n_splits: int = Field(5, ge=2, le=20)
    # Days dropped between each fold's train end and test start. Defaults to
    # the forecast horizon at call time: predicting t+h from features at t
    # means a training row within h days of the test window shares its target
    # period, so without the gap the score is measuring memorisation.
    embargo_days: int | None = None
    min_train_fraction: float = Field(0.4, gt=0.0, lt=1.0)


class UncertaintyConfig(BaseModel):
    """Bootstrap prediction intervals — see `uncertainty.py`."""

    method: Literal["residual_bootstrap", "bagged_bootstrap"] = "residual_bootstrap"
    n_bootstrap: int = Field(500, ge=50, le=5000)
    confidence_level: float = Field(0.95, gt=0.5, lt=1.0)
    random_seed: int = 42


class ModelConfig(BaseModel):
    """LightGBM hyperparameters.

    Deliberately conservative and fixed rather than searched. These series are
    short (a few hundred to a few thousand daily rows per point), so an
    aggressive tree is a memorisation machine; and a tuning sweep per variable
    per horizon is exactly the per-variable maintenance burden this engine
    exists to avoid.
    """

    kind: Literal["lightgbm"] = "lightgbm"
    n_estimators: int = 400
    learning_rate: float = 0.05
    num_leaves: int = 31
    max_depth: int = -1
    min_child_samples: int = 20
    subsample: float = 0.8
    subsample_freq: int = 1
    colsample_bytree: float = 0.8
    reg_alpha: float = 0.0
    reg_lambda: float = 1.0
    random_state: int = 42
    n_jobs: int = -1
    verbosity: int = -1

    def to_lightgbm_params(self) -> dict[str, Any]:
        return self.model_dump(exclude={"kind"})


class BaselineConfig(BaseModel):
    """Prophet, used for benchmarking only — never served as a forecast.

    Off by default: Prophet is a heavy optional dependency and its value here
    is a sanity check during training ("is the tree beating a trend+season
    fit?"), not a production path.
    """

    enabled: bool = False
    kind: Literal["prophet"] = "prophet"
    yearly_seasonality: bool = True
    weekly_seasonality: bool = False
    daily_seasonality: bool = False


class TrainingPoint(BaseModel):
    """One ocean location contributing rows to a global model."""

    name: str
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


class TrainingConfig(BaseModel):
    """How the offline trainer assembles a training set.

    A model is global: one LightGBM per (variable, horizon) fitted across
    every point below, with latitude/longitude/bathymetry as features, so it
    scores an arbitrary coordinate rather than only the ones it saw. That is
    the whole reason the static features exist.
    """

    history_days: int = Field(730, ge=90)
    resolution: Literal["hourly", "daily"] = "daily"
    points: list[TrainingPoint] = Field(default_factory=list)
    # A point whose history comes back too short to build features from is
    # skipped with a warning rather than failing the run — coverage genuinely
    # differs per variable, and one bad location should not cost the model.
    min_rows_per_point: int = Field(120, ge=30)
    # Below this the trainer refuses to write a model at all. A LightGBM fitted
    # on 80 rows will happily produce confident nonsense.
    min_total_rows: int = Field(400, ge=100)


class OutlierConfig(BaseModel):
    """Outlier handling — see `preprocessing.py`.

    Detection replaces a flagged value with NaN and refills it like any other
    gap; nothing is ever dropped, because removing a row from a time series
    silently changes every lag that steps over it.

    **The default is `none`, and that was measured rather than assumed.** Every
    source behind this engine is a quality-controlled model or reanalysis
    product, not a raw instrument — there are no sensor spikes to remove. Run
    against real Copernicus SST, the Hampel filter flagged 5-12% of a clean
    daily series at every window and threshold tried (7-21 steps, 3-5 sigma),
    because its local-scale assumption inverts on a smooth field: the series
    tracks its own rolling median so closely that the MAD collapses, and
    ordinary variation then looks extreme against it. Interpolating over 12%
    of a good SST record is exactly the fabrication this platform refuses
    elsewhere.

    The filters stay implemented and are one config line away, for the sources
    that genuinely need them — buoy feeds and satellite retrievals, where a
    spike really is an instrument artifact.
    """

    method: Literal["none", "iqr", "zscore", "hampel"] = "none"
    # Sigma-equivalents. Hampel measures them against a robust local scale, so
    # 3 is far stricter here than a 3-sigma z-score would be.
    threshold: float = 4.0
    window: int = 15


class VariableConfig(BaseModel):
    """One forecastable variable.

    `code` keys into `services/download/registry.VARIABLE_REGISTRY`; label,
    unit and provider are read from there rather than restated, so they cannot
    drift out of sync with what the downloader actually serves.
    """

    code: str
    # Other registry codes fetched alongside the target and fed in as trailing
    # features. This is what lets SST's explanation name wind speed and air
    # temperature, as opposed to only its own lags.
    covariates: list[str] = Field(default_factory=list)
    horizons: list[int] | None = None
    features: FeatureConfig | None = None
    model: ModelConfig | None = None
    outliers: OutlierConfig | None = None
    training: TrainingConfig | None = None
    # Fit on log1p and invert on predict. Right for strictly-positive,
    # heavy-tailed fields (chlorophyll spans three orders of magnitude), wrong
    # for anything that can go negative.
    log_transform: bool = False
    # What the model actually regresses on. See `Defaults.target_mode` — this
    # overrides it per variable, and almost nothing should need to.
    target_mode: Literal["delta", "level"] | None = None
    # Degrees on a circle: 359 and 1 are two degrees apart, not 358. Flagged
    # here so the feature builder can encode sin/cos and the evaluator can use
    # circular error instead of pretending the axis is linear.
    #
    # Not stated in the YAML: it is read from the registry entry `code` names,
    # exactly as label/unit/category are, because whether a quantity is a
    # bearing is a property of the quantity and not of one consumer's opinion
    # about it. It was briefly declared in both places, and the two disagreeing
    # is a class of bug worth designing out — the modelling half would encode
    # sin/cos while the rendering half painted a linear ramp, and both would
    # look plausible.
    circular: bool | None = None
    # Hard physical bounds, applied to the prediction and its interval. None
    # means unbounded on that side.
    valid_min: float | None = None
    valid_max: float | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def _inherit_circular(self) -> VariableConfig:
        if self.circular is None:
            # `code` is validated against the registry by the loader, so a
            # missing entry here means the file was constructed by hand in a
            # test; default to linear rather than raising a second time.
            info = VARIABLE_REGISTRY.get(self.code)
            object.__setattr__(self, "circular", bool(info and info.circular))
        return self

    @property
    def label(self) -> str:
        return VARIABLE_REGISTRY[self.code].label

    @property
    def unit(self) -> str:
        return VARIABLE_REGISTRY[self.code].unit

    @property
    def category(self) -> str:
        return VARIABLE_REGISTRY[self.code].category


class Defaults(BaseModel):
    # Regress on the *change* from the current value, not the absolute level.
    #
    # This is the single most consequential setting in the file, and it was
    # chosen from measurement rather than taste. A gradient-boosted tree
    # predicts a piecewise-constant function of its inputs, so it cannot
    # represent the identity y(t+h) = y(t) — it can only approximate that
    # straight line with steps. On a strongly autocorrelated geophysical
    # series, where persistence is a genuinely hard baseline, that structural
    # limit showed up exactly as it should: fitting on levels scored *worse
    # than persistence at every horizon tested*, including one day ahead
    # (skill -0.12 at h=1, -0.14 at h=7).
    #
    # Fitting on the delta removes the handicap. Persistence becomes the
    # constant zero, which a tree represents exactly, so the model starts from
    # parity and only has to learn the departure from it. Same features, same
    # data, same hyperparameters.
    #
    # `level` is kept for fields where the absolute value is the signal and
    # there is no meaningful anchor to difference against.
    target_mode: Literal["delta", "level"] = "delta"
    horizons: list[int] = Field(default_factory=lambda: [1, 3, 7, 30])
    features: FeatureConfig = Field(default_factory=FeatureConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    uncertainty: UncertaintyConfig = Field(default_factory=UncertaintyConfig)
    baseline: BaselineConfig = Field(default_factory=BaselineConfig)
    outliers: OutlierConfig = Field(default_factory=OutlierConfig)
    training: TrainingConfig = Field(default_factory=TrainingConfig)
    # Horizons the engine will accept from a request even though nothing is
    # trained for them yet. Listing 90 and 365 here is the "future-proof"
    # requirement: the API validates against this, and an untrained horizon
    # returns a clear "not trained" rather than a 422 that implies it never
    # could be.
    supported_horizons: list[int] = Field(default_factory=lambda: [1, 3, 7, 14, 30, 90, 365])
    # Longest history a single request may ask for, in days. Guards the
    # upstream providers as much as this process.
    max_history_days: int = 3650


class ForecastingConfig(BaseModel):
    """The whole file, after defaults have been folded into each variable."""

    defaults: Defaults = Field(default_factory=Defaults)
    variables: dict[str, VariableConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_against_download_registry(self) -> ForecastingConfig:
        """Every configured code must be a variable the platform can fetch.

        This is the check that makes config-only extension safe. Registering
        `turbidity` here before a provider exists for it would otherwise
        produce a variable that lists fine, trains to nothing, and fails at
        inference with a KeyError from three modules away.
        """
        problems: list[str] = []
        for key, variable in self.variables.items():
            for code in (variable.code, *variable.covariates):
                info = VARIABLE_REGISTRY.get(code)
                role = "variable" if code == variable.code else "covariate"
                if info is None:
                    problems.append(
                        f"{key}: {role} {code!r} is not in the download registry"
                    )
                elif not info.available:
                    problems.append(
                        f"{key}: {role} {code!r} is registered but has no provider yet"
                    )
            if variable.code in variable.covariates:
                problems.append(f"{key}: {variable.code!r} lists itself as a covariate")
        if problems:
            raise ValueError("invalid forecasting config:\n  - " + "\n  - ".join(problems))
        return self

    # ---- resolution helpers -------------------------------------------

    def horizons_for(self, key: str) -> list[int]:
        return self.variables[key].horizons or self.defaults.horizons

    def features_for(self, key: str) -> FeatureConfig:
        return self.variables[key].features or self.defaults.features

    def model_for(self, key: str) -> ModelConfig:
        return self.variables[key].model or self.defaults.model

    def outliers_for(self, key: str) -> OutlierConfig:
        return self.variables[key].outliers or self.defaults.outliers

    def target_mode_for(self, key: str) -> str:
        return self.variables[key].target_mode or self.defaults.target_mode

    def training_for(self, key: str) -> TrainingConfig:
        variable_training = self.variables[key].training
        if variable_training is None:
            return self.defaults.training
        # A variable-level training block that omits `points` means "same
        # locations, different window", which is the common case (a product
        # with a late coverage start needs a shorter history, not a different
        # geography).
        if not variable_training.points:
            return variable_training.model_copy(update={"points": self.defaults.training.points})
        return variable_training

    def enabled_variables(self) -> dict[str, VariableConfig]:
        return {key: value for key, value in self.variables.items() if value.enabled}


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def load_config(path: Path | None = None) -> ForecastingConfig:
    """Parse and validate the YAML. Raises ConfigError, never a raw yaml error."""
    resolved = path or CONFIG_PATH
    try:
        raw = yaml.safe_load(resolved.read_text()) or {}
    except FileNotFoundError as exc:
        raise ConfigError(f"forecasting config not found at {resolved}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"forecasting config at {resolved} is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"forecasting config at {resolved} must be a mapping at the top level")

    try:
        return ForecastingConfig.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError, or our own ValueError
        raise ConfigError(f"forecasting config at {resolved} is invalid: {exc}") from exc


@functools.lru_cache(maxsize=1)
def get_config() -> ForecastingConfig:
    """Process-wide config, parsed once.

    Cached because it is read on every request. `get_config.cache_clear()` in
    tests, or after editing the YAML in a long-lived dev server.
    """
    return load_config()
