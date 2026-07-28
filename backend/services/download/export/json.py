"""JSON export for the Universal Ocean Data Downloader — pretty-printed,
flat {metadata, variables, data} shape, no provider-specific nesting."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from services.download.registry import VariableInfo


def to_json_bytes(
    df: pd.DataFrame, metadata: dict[str, Any], variables: dict[str, VariableInfo]
) -> bytes:
    payload = {
        "metadata": metadata,
        "variables": [
            {"code": code, "label": info.label, "unit": info.unit, "category": info.category}
            for code, info in variables.items()
        ],
        # Round-trip through pandas' own JSON encoder (handles NaN -> null and
        # datetime -> ISO 8601 correctly) rather than reinventing that here.
        "data": json.loads(df.to_json(orient="records", date_format="iso")),
    }
    return json.dumps(payload, indent=2).encode("utf-8")
