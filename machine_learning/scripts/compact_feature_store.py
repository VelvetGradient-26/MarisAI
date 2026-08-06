"""Rewrite a feature store in place at the dtypes ``compact_dtypes`` would give it.

Stores written before ``compact_dtypes`` was wired into ``write_feature_store``
are float64 on disk. ``read_feature_store`` downcasts, but only *after*
``pd.read_parquet`` has materialized the full-width table, so every experiment
pays a doubled peak. Rewriting once removes that permanently.

The rewrite streams row group by row group and casts with Arrow, never pandas:
loading 3.9M x 151 float64 to cast it would need the very ~7 GB peak this
exists to remove. Coordinate columns keep float64 for the reason
``fusion._KEEP_FLOAT64`` documents — downstream code *groups* on them, and
float32 rounding could split one grid cell into two.

    uv run python scripts/compact_feature_store.py hab_gridded

Writes a sibling ``.compacting.parquet`` and renames over the original only
after the row counts and column names match, so an interrupted run leaves the
existing store untouched.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from marine_ml import config  # noqa: E402
from marine_ml.fusion import _KEEP_FLOAT64  # noqa: E402


def compact_schema(schema: pa.Schema) -> pa.Schema:
    """The Arrow mirror of ``compact_dtypes``: float64 -> float32, int64 -> int32."""
    fields = []
    for field in schema:
        if field.name in _KEEP_FLOAT64:
            fields.append(field)
        elif pa.types.is_float64(field.type):
            fields.append(field.with_type(pa.float32()))
        elif pa.types.is_int64(field.type):
            fields.append(field.with_type(pa.int32()))
        else:
            fields.append(field)
    return pa.schema(fields, metadata=schema.metadata)


def compact(path: Path, *, compression: str = "zstd") -> None:
    source = pq.ParquetFile(path)
    target_schema = compact_schema(source.schema_arrow)
    temporary = path.with_suffix(".compacting.parquet")

    rows_written = 0
    with pq.ParquetWriter(temporary, target_schema, compression=compression) as writer:
        for index in range(source.metadata.num_row_groups):
            table = source.read_row_group(index)
            writer.write_table(table.cast(target_schema))
            rows_written += table.num_rows
            print(
                f"  row group {index + 1}/{source.metadata.num_row_groups}"
                f" — {rows_written:,} rows",
                flush=True,
            )

    check = pq.ParquetFile(temporary)
    if check.metadata.num_rows != source.metadata.num_rows:
        temporary.unlink()
        raise SystemExit(
            f"row count changed ({source.metadata.num_rows} -> "
            f"{check.metadata.num_rows}); original left in place"
        )
    if check.schema_arrow.names != source.schema_arrow.names:
        temporary.unlink()
        raise SystemExit("column names changed; original left in place")

    before = path.stat().st_size
    after = temporary.stat().st_size
    temporary.replace(path)
    print(
        f"{path.name}: {before / 1e9:.2f} GB -> {after / 1e9:.2f} GB "
        f"({100 * after / before:.0f}% of original), {rows_written:,} rows"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="feature store name, e.g. hab_gridded")
    parser.add_argument(
        "--compression",
        default="zstd",
        help="parquet codec for the rewritten file (default: zstd)",
    )
    args = parser.parse_args()

    path = config.FEATURE_STORE_DIR / f"{args.name}.parquet"
    if not path.exists():
        raise SystemExit(f"no feature store at {path}")
    compact(path, compression=args.compression)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
