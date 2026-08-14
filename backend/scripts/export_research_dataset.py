#!/usr/bin/env python
"""Export a self-contained dataset for the research notebooks.

    .venv/bin/python scripts/export_research_dataset.py

The notebooks must run for someone who has cloned the repository and has no
Copernicus credentials, no populated history cache, and no intention of
waiting ~700 s per variable for an upstream fetch. So the cleaned point series
every experiment is built from is exported once, here, into a single tidy
parquet that the notebooks read directly.

Deliberately exported *before* feature construction. The notebooks build lags,
rolling statistics and the delta target themselves, because that is the part a
reader needs to see and re-derive; shipping a finished feature matrix would
hide exactly the step the paper's methodology section is about.

Long format (one row per variable/site/field/timestamp) rather than wide,
because the value columns differ per variable — each has its own covariate
list — and a wide frame would be mostly nulls.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("MARISAI_FROZEN_HISTORY_CACHE", "1")

from forecasting.config import get_config  # noqa: E402
from forecasting.history import HistoryRequest, fetch  # noqa: E402
from forecasting.preprocessing import clean  # noqa: E402
from forecasting.registry import fetch_codes, resolve  # noqa: E402
from scripts.run_paper_experiments import AS_OF, VARIABLES  # noqa: E402
from services.download.models import Resolution  # noqa: E402

logger = logging.getLogger("export_research_dataset")

OUT = Path(__file__).resolve().parents[2] / "research" / "data"


async def export() -> None:
    config = get_config()
    frames: list[pd.DataFrame] = []
    manifest: list[dict[str, object]] = []

    for key in VARIABLES:
        variable = resolve(key, config)
        codes = fetch_codes(variable)
        features = config.features_for(key)
        training = config.training_for(key)
        pad = max(config.horizons_for(key) or [1])
        start = AS_OF - timedelta(
            days=training.history_days + features.max_lookback_days + pad
        )
        resolution = Resolution(training.resolution)

        rows = 0
        for point in training.points:
            series = await fetch(
                HistoryRequest(
                    codes=codes,
                    latitude=point.latitude,
                    longitude=point.longitude,
                    start_date=start,
                    end_date=AS_OF,
                    resolution=resolution,
                )
            )
            value_columns = [c for c in codes if c in series.frame.columns]
            cleaned, _quality = clean(
                series.frame,
                value_columns,
                resolution=resolution,
                outliers=config.outliers_for(key),
            )
            tidy = cleaned.melt(
                id_vars=["timestamp"],
                value_vars=value_columns,
                var_name="field",
                value_name="value",
            )
            tidy["variable"] = key
            tidy["site"] = point.name
            tidy["latitude"] = series.latitude
            tidy["longitude"] = series.longitude
            # `field == variable.code` is the target; everything else is a
            # covariate. Recorded as a column so a notebook never has to
            # re-derive it from the config.
            tidy["role"] = ["target" if f == variable.code else "covariate"
                            for f in tidy["field"]]
            frames.append(tidy)
            rows += len(cleaned)

        manifest.append(
            {
                "variable": key,
                "label": variable.label,
                "unit": variable.unit,
                "category": variable.category,
                "code": variable.code,
                "covariates": list(variable.covariates),
                "circular": bool(variable.circular),
                "log_transform": bool(variable.log_transform),
                "target_mode": config.target_mode_for(key),
                "horizons": list(config.horizons_for(key)),
                "sites": len(training.points),
                "timesteps_per_site": rows // max(len(training.points), 1),
            }
        )
        logger.info(f"{key}: {rows} cleaned rows across {len(training.points)} sites")

    combined = pd.concat(frames, ignore_index=True)
    combined = combined[
        ["variable", "site", "latitude", "longitude", "timestamp", "field", "role", "value"]
    ]
    # Categoricals so the parquet dictionary-encodes the repeated strings; the
    # difference is roughly an order of magnitude on this shape.
    for column in ("variable", "site", "field", "role"):
        combined[column] = combined[column].astype("category")

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "point_series.parquet"
    combined.to_parquet(path, index=False, compression="zstd")

    sites = (
        combined.groupby("site", observed=True)[["latitude", "longitude"]]
        .first()
        .reset_index()
    )
    sites.to_csv(OUT / "sites.csv", index=False)
    (OUT / "variables.json").write_text(json.dumps(manifest, indent=2))

    size = path.stat().st_size / 1024**2
    print(f"{len(combined):,} rows -> {path} ({size:.1f} MB)")
    print(f"{len(sites)} sites -> {OUT / 'sites.csv'}")
    print(f"{len(manifest)} variables -> {OUT / 'variables.json'}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("forecasting").setLevel(logging.WARNING)
    asyncio.run(export())
