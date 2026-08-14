#!/usr/bin/env python
"""Which `as_of` snapshot date do the cached history parquets correspond to?

Read-only. The history cache key folds in start/end dates, and the trainer
derives both from `datetime.now(UTC)`, so a run today misses every entry a run
last week wrote. This finds the date that maximises cache hits per variable,
which is what makes the paper's experiments runnable offline.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from forecasting.config import get_config  # noqa: E402
from forecasting.history import CACHE_DIR, HistoryRequest, clamp_to_coverage  # noqa: E402
from forecasting.registry import fetch_codes, resolve  # noqa: E402
from services.download.models import Resolution  # noqa: E402


def keys_for(key: str, as_of: date) -> list[str]:
    config = get_config()
    variable = resolve(key, config)
    codes = fetch_codes(variable)
    features = config.features_for(key)
    training = config.training_for(key)
    pad = max(config.horizons_for(key) or [1])
    start = as_of - timedelta(days=training.history_days + features.max_lookback_days + pad)

    out = []
    for point in training.points:
        request = clamp_to_coverage(
            HistoryRequest(
                codes=codes,
                latitude=point.latitude,
                longitude=point.longitude,
                start_date=start,
                end_date=as_of,
                resolution=Resolution(training.resolution),
            )
        )
        out.append(request.cache_key())
    return out


def main() -> None:
    config = get_config()
    today = date(2026, 8, 14)
    candidates = [today - timedelta(days=n) for n in range(0, 15)]

    print(f"cache dir: {CACHE_DIR}  ({len(list(CACHE_DIR.glob('*.parquet')))} entries)\n")
    print(f"{'variable':<26} {'best as_of':<12} {'hits':<8} runner-up")
    for key in config.variables:
        scored = []
        for as_of in candidates:
            keys = keys_for(key, as_of)
            hits = sum((CACHE_DIR / f"{k}.parquet").exists() for k in keys)
            scored.append((hits, as_of, len(keys)))
        scored.sort(key=lambda row: (-row[0], row[1]))
        best, second = scored[0], scored[1]
        print(
            f"{key:<26} {best[1].isoformat():<12} {best[0]}/{best[2]:<6} "
            f"{second[1].isoformat()} {second[0]}/{second[2]}"
        )


if __name__ == "__main__":
    main()
