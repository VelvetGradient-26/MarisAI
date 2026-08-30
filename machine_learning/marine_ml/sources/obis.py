"""OBIS occurrence records — the label source for Problem B (fish habitat).

Two kinds of query live here and they serve different roles:

``fetch_occurrences``
    Presence records for a target species. These become the positive class.

``fetch_target_group``
    Occurrence records for the wider taxonomic group (ray-finned fishes) in
    the same region and period. These are *not* absences; they are the pool
    from which pseudo-absences get drawn in ``fish_habitat.labels``. Drawing
    background points from places where somebody actually sampled — and
    recorded some other fish — inherits the survey effort bias of the
    presences and cancels much of it, which random ocean points do not do
    (approach doc 4.5). Marine occurrence data clusters hard around research
    institutes, ports and shipping routes, so this matters more here than the
    choice of classifier does.

OBIS is presence-only: a species missing from a cell means nobody recorded it
there, not that it was absent. Nothing in this module should be read as
evidence of absence.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterator

import numpy as np
import pandas as pd
import requests

from marine_ml import config

_API_ROOT = "https://api.obis.org/v3"
_PAGE_SIZE = 5000
_TIMEOUT_SECONDS = 120
_MAX_PAGES = 200  # hard stop; 1M records at this page size

# Columns kept from the (very wide) OBIS record. `dataset_id` and
# `institutionCode` are retained deliberately: they identify *who sampled*,
# which is what makes a sampling-bias diagnostic possible later.
# `occurrenceID`/`catalogNumber` are the dedup keys
# `fish_habitat_prediction.src.labels.union_presences` needs to combine this
# frame with `marine_ml.sources.gbif`'s — see that module's docstring.
_COLUMNS = {
    "decimalLatitude": "latitude",
    "decimalLongitude": "longitude",
    "eventDate": "event_date",
    "scientificName": "scientific_name",
    "species": "species",
    "basisOfRecord": "basis_of_record",
    "dataset_id": "dataset_id",
    "institutionCode": "institution_code",
    "individualCount": "individual_count",
    "occurrenceID": "occurrence_id",
    "catalogNumber": "catalog_number",
}


class ObisError(RuntimeError):
    """Raised when OBIS cannot be queried or returns nothing usable."""


def _paged_request(params: dict) -> Iterator[dict]:
    """Yield occurrence records, following OBIS's ``after`` cursor.

    OBIS caps a single response well below the size of these queries, so deep
    paging is mandatory — a single un-paged call silently truncates.
    """
    after: str | None = None
    for page in range(_MAX_PAGES):
        page_params = dict(params, size=_PAGE_SIZE)
        if after is not None:
            page_params["after"] = after
        try:
            response = requests.get(
                f"{_API_ROOT}/occurrence", params=page_params, timeout=_TIMEOUT_SECONDS
            )
        except requests.RequestException as exc:
            raise ObisError(f"OBIS request failed: {exc}") from exc
        if not response.ok:
            raise ObisError(
                f"OBIS returned HTTP {response.status_code}: {response.text[:200]}"
            )

        results = response.json().get("results", [])
        if not results:
            return
        yield from results
        if len(results) < _PAGE_SIZE:
            return
        after = results[-1].get("id")
        if after is None:
            # Without an id there is no cursor to continue from; stopping is
            # the honest outcome, silently looping the same page is not.
            return

    # Falling out of the loop means the cap was reached with more data behind
    # it. Returning here would hand back a *truncated* frame that looks
    # complete, and because pages follow the `after` cursor the truncation is
    # ordered, not random — for a background pool whose entire job is to
    # represent where people sampled, a spatially-skewed prefix is worse than
    # no pool at all. Raising the cap is not the fix either: the global target
    # group is 21.8M records. Use `sample_target_group`.
    raise ObisError(
        f"OBIS query exceeded {_MAX_PAGES} pages "
        f"({_MAX_PAGES * _PAGE_SIZE:,} records) and would be silently "
        f"truncated: {params}. Narrow the query, or draw a sample with "
        f"`sample_target_group` instead of enumerating every record."
    )


def _to_frame(records: list[dict]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=list(_COLUMNS.values()) + ["observation_date"])

    frame = pd.DataFrame(records)
    for source in _COLUMNS:
        if source not in frame.columns:
            frame[source] = pd.NA
    frame = frame[list(_COLUMNS)].rename(columns=_COLUMNS)

    frame["latitude"] = pd.to_numeric(frame["latitude"], errors="coerce")
    frame["longitude"] = pd.to_numeric(frame["longitude"], errors="coerce")
    # OBIS event dates are heterogeneous ISO strings, sometimes ranges
    # ("2013-02-01/2013-02-28"); take the start of any range, then parse.
    starts = frame["event_date"].astype("string").str.split("/").str[0]
    frame["observation_date"] = pd.to_datetime(
        starts, errors="coerce", utc=True, format="mixed"
    ).dt.tz_localize(None).dt.normalize()

    return frame.dropna(subset=["latitude", "longitude", "observation_date"]).reset_index(
        drop=True
    )


def _cached_query(
    cache_name: str,
    params: dict,
    refresh: bool,
    max_records: int | None = None,
) -> pd.DataFrame:
    """Run a paged query, caching the parsed frame.

    ``max_records`` stops paging once that many records have been collected.
    That is a *quota*, not a safety cap, and only `sample_target_group` passes
    it — it deliberately takes an equal slice from each sampled cell. Every
    other caller leaves it None and gets the whole result or an error, because
    a partial answer they did not ask for is indistinguishable from a complete
    one.
    """
    config.ensure_directories()
    cached: Path = config.OBIS_RAW_DIR / f"{cache_name}.parquet"
    if cached.exists() and not refresh:
        return pd.read_parquet(cached)

    records: list[dict] = []
    for record in _paged_request(params):
        records.append(record)
        if max_records is not None and len(records) >= max_records:
            break

    frame = _to_frame(records)
    frame.to_parquet(cached, index=False)
    return frame


def _slug(text: str) -> str:
    return text.lower().replace(" ", "_").replace("/", "_")


def fetch_occurrences(
    scientific_name: str,
    region: config.Region = config.DEFAULT_REGION,
    start: date = config.DEFAULT_START,
    end: date = config.DEFAULT_END,
    refresh: bool = False,
) -> pd.DataFrame:
    """Presence records for one species within ``region`` and the date range."""
    params = {
        "scientificname": scientific_name,
        "geometry": region.wkt,
        "startdate": start.isoformat(),
        "enddate": end.isoformat(),
    }
    cache = f"occ_{_slug(scientific_name)}_{region.name}_{start}_{end}"
    frame = _cached_query(cache, params, refresh)
    frame = frame.assign(scientific_name=scientific_name)
    return frame


def fetch_target_group(
    region: config.Region = config.DEFAULT_REGION,
    start: date = config.DEFAULT_START,
    end: date = config.DEFAULT_END,
    taxon_id: int = config.TARGET_GROUP_TAXON_ID,
    refresh: bool = False,
) -> pd.DataFrame:
    """All occurrence records for the target taxonomic group in ``region``.

    The background pool for target-group pseudo-absence sampling — see the
    module docstring for why this, and not random ocean points.
    """
    params = {
        "taxonid": taxon_id,
        "geometry": region.wkt,
        "startdate": start.isoformat(),
        "enddate": end.isoformat(),
    }
    cache = f"targetgroup_{taxon_id}_{region.name}_{start}_{end}"
    return _cached_query(cache, params, refresh)


# Geohash precision for the effort grid. 3 is ~1.4 degrees and returns ~7,700
# ocean cells worldwide in a single ~1.4 MB response — fine enough to steer
# sampling toward where people actually surveyed, coarse enough to stay one
# cheap call. Precision 4 is ~0.18 degrees and tens of thousands of cells.
_EFFORT_PRECISION = 3


def fetch_effort_grid(
    region: config.Region = config.DEFAULT_REGION,
    start: date = config.DEFAULT_START,
    end: date = config.DEFAULT_END,
    taxon_id: int = config.TARGET_GROUP_TAXON_ID,
    precision: int = _EFFORT_PRECISION,
    refresh: bool = False,
) -> pd.DataFrame:
    """Records per grid cell for the target group — a sampling-effort surface.

    One call to OBIS's ``/occurrence/grid/{precision}``, which answers "how
    many records are there here" without transferring the records. Verified
    2026-08-10: worldwide Actinopterygii 2000-2013 returns 7,664 cells whose
    counts sum to exactly the 21,789,311 that ``/statistics`` reports.

    Returns one row per cell with ``latitude``/``longitude`` (centroid),
    ``records``, and the cell bounds needed to query inside it.
    """
    config.ensure_directories()
    cache = (
        config.OBIS_RAW_DIR
        / f"effort_{taxon_id}_p{precision}_{region.name}_{start}_{end}.parquet"
    )
    if cache.exists() and not refresh:
        return pd.read_parquet(cache)

    params = {
        "taxonid": taxon_id,
        "geometry": region.wkt,
        "startdate": start.isoformat(),
        "enddate": end.isoformat(),
    }
    try:
        response = requests.get(
            f"{_API_ROOT}/occurrence/grid/{precision}",
            params=params,
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise ObisError(f"OBIS effort-grid request failed: {exc}") from exc
    if not response.ok:
        raise ObisError(
            f"OBIS effort grid returned HTTP {response.status_code}: "
            f"{response.text[:200]}"
        )

    rows = []
    for feature in response.json().get("features", []):
        count = (feature.get("properties") or {}).get("n")
        ring = (feature.get("geometry") or {}).get("coordinates")
        if not count or not ring:
            continue
        longitudes = [point[0] for point in ring[0]]
        latitudes = [point[1] for point in ring[0]]
        rows.append(
            {
                "records": int(count),
                "west": min(longitudes),
                "east": max(longitudes),
                "south": min(latitudes),
                "north": max(latitudes),
                "longitude": (min(longitudes) + max(longitudes)) / 2,
                "latitude": (min(latitudes) + max(latitudes)) / 2,
            }
        )

    if not rows:
        raise ObisError(
            f"OBIS effort grid returned no cells for taxon {taxon_id} in "
            f"{region.name} between {start} and {end}"
        )

    frame = pd.DataFrame(rows)
    frame.to_parquet(cache, index=False)
    return frame


def sample_target_group(
    region: config.Region = config.DEFAULT_REGION,
    start: date = config.DEFAULT_START,
    end: date = config.DEFAULT_END,
    taxon_id: int = config.TARGET_GROUP_TAXON_ID,
    n_cells: int = 400,
    records_per_cell: int = 5000,
    seed: int = config.RANDOM_SEED,
    refresh: bool = False,
) -> pd.DataFrame:
    """An effort-weighted sample of the target group, for wide regions.

    `fetch_target_group` enumerates every record, which is right regionally
    (10,051 records over NORTH_INDIAN_OCEAN) and impossible worldwide: the same
    query global is **21,789,311 records**, ~4,400 pages.

    The sampling is designed around what the background pool is actually used
    for. `fish_habitat.labels.build_background` thins the pool to **one point
    per (0.25 degree cell, month) slot** before drawing from it, so records
    beyond the first in any slot are discarded — enumerating 21.8M records to
    keep a few hundred thousand slots is almost all waste.

    So: **choose cells with probability proportional to their record count,
    then take an equal quota from each chosen cell.** Expected records per cell
    is then proportional to effort, which is the property that makes
    target-group background sampling work at all (doc 4.5) — background points
    inherit the survey bias of the presences and cancel much of it. Weighting
    only the *selection*, rather than fetching a quota from all 7,664 cells,
    keeps this to `n_cells` requests instead of thousands.

    Cells are drawn **without replacement** so a handful of enormous cells
    cannot become the entire pool: the largest single cell worldwide holds
    2.15M records, ~10% of the total.

    **Budget by cells, and measure the rate before trusting an estimate.**
    At these defaults a cell costs **~62 s** (measured over 34 worldwide cells,
    2026-08-10), so 400 cells is ~7 hours — this dominates the whole global
    build, which pays only ~25 minutes for all 28 Copernicus year-files. An
    earlier estimate of ~10 s/cell came from a probe at
    ``records_per_cell=2000`` and did not survive contact with the default:
    effort-weighted selection favours dense cells, and dense cells page more.

    If that ever needs to be faster, **raise `n_cells` and lower
    `records_per_cell` rather than the reverse.** Both of the things this pool
    is judged on improve that way: distinct cells produce distinct
    (cell, month) slots, whereas extra records inside one dense cell mostly
    land in slots already taken and are thinned away, and wider cell coverage
    is a better picture of survey effort. The per-cell caches are keyed on cell
    index alone, so changing the quota does not invalidate them.
    """
    rng = np.random.default_rng(seed)
    effort = fetch_effort_grid(region, start, end, taxon_id, refresh=refresh)

    weights = effort["records"].to_numpy(dtype="float64")
    take = min(n_cells, len(effort))
    chosen = rng.choice(
        len(effort), size=take, replace=False, p=weights / weights.sum()
    )

    frames: list[pd.DataFrame] = []
    for rank, index in enumerate(sorted(chosen)):
        cell = effort.iloc[int(index)]
        box = config.Region(
            f"{region.name}_cell{int(index)}",
            west=float(cell["west"]), east=float(cell["east"]),
            south=float(cell["south"]), north=float(cell["north"]),
        )
        params = {
            "taxonid": taxon_id,
            "geometry": box.wkt,
            "startdate": start.isoformat(),
            "enddate": end.isoformat(),
        }
        cache = (
            f"targetgroup_sample_{taxon_id}_{region.name}_{start}_{end}"
            f"_c{int(index)}"
        )
        try:
            frame = _cached_query(cache, params, refresh, max_records=records_per_cell)
        except ObisError as exc:
            # One unreachable cell must not cost the other 399. The pool is a
            # sample by construction, so a gap in it is a smaller sample, not a
            # wrong one — but say so, since silent shrinkage is how a
            # background pool stops representing effort.
            print(f"  warning: cell {int(index)} ({rank+1}/{take}) failed: {exc}",
                  flush=True)
            continue
        if not frame.empty:
            frames.append(frame)

    if not frames:
        raise ObisError(
            f"effort-weighted target-group sample returned nothing for taxon "
            f"{taxon_id} in {region.name} between {start} and {end}"
        )

    pool = pd.concat(frames, ignore_index=True)
    # Cells are drawn without replacement and their boxes do not overlap, but
    # a record exactly on a shared edge can be returned by both neighbours.
    if "dataset_id" in pool.columns:
        pool = pool.drop_duplicates(
            subset=["latitude", "longitude", "observation_date", "dataset_id"]
        )
    return pool.reset_index(drop=True)


def fetch_all_target_species(
    species: dict[str, str] | None = None,
    region: config.Region = config.DEFAULT_REGION,
    start: date = config.DEFAULT_START,
    end: date = config.DEFAULT_END,
    refresh: bool = False,
) -> pd.DataFrame:
    """Presence records for every configured target species, concatenated."""
    species = species or config.TARGET_SPECIES
    frames = [
        fetch_occurrences(name, region, start, end, refresh).assign(species_key=key)
        for key, name in species.items()
    ]
    frames = [f for f in frames if not f.empty]
    if not frames:
        raise ObisError(
            f"no occurrence records for any target species in {region.name} "
            f"between {start} and {end}"
        )
    return pd.concat(frames, ignore_index=True)
