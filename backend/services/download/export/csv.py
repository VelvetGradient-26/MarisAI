"""CSV export for the Universal Ocean Data Downloader — clean UTF-8, no
nested structures, one row per observation."""

from __future__ import annotations

import pandas as pd


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")
