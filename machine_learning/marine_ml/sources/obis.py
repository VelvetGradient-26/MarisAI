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
}


class ObisError(RuntimeError):
    """Raised when OBIS cannot be queried or returns nothing usable."""


def _paged_request(params: dict) -> Iterator[dict]:
    """Yield occurrence records, following OBIS's ``after`` cursor.

    OBIS caps a single response well below the size of these queries, so deep
    paging is mandatory — a single un-paged call silently truncates.
    """
    after: str | None = None
    for _ in range(_MAX_PAGES):
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
) -> pd.DataFrame:
    config.ensure_directories()
    cached: Path = config.OBIS_RAW_DIR / f"{cache_name}.parquet"
    if cached.exists() and not refresh:
        return pd.read_parquet(cached)

    frame = _to_frame(list(_paged_request(params)))
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
