"""GBIF occurrence records — the second presence source for Problem B (fish habitat).

**Why a second presence source at all.** OBIS and GBIF overlap heavily (much
of GBIF's marine holdings *are* OBIS datasets, republished) but neither
dominates the other everywhere. Measured live 2026-08-05 over
`NORTH_INDIAN_OCEAN`, 2000-2013:

    species                    OBIS    GBIF
    Thunnus albacares            394    1228
    Katsuwonus pelamis            280    1622
    Thunnus obesus                283     678
    Rastrelliger kanagurta          67       9
    Sardinella longiceps          112       9

GBIF dominates for the three tunas (3-6x); OBIS dominates ~10x for Indian
mackerel and oil sardine — the two species that matter most for Indian
coastal fisheries. So this is a **union**, not a switch: taking whichever
source is bigger per species would still throw away the smaller source's
real, distinct records. `fish_habitat_prediction.src.labels.union_presences`
is where the two are actually combined and deduplicated; this module only
fetches GBIF's half, in the same shape `marine_ml.sources.obis` already
produces so the two frames can be concatenated directly.

**Only presences, not the target-group background pool.** OBIS's
`sample_target_group` stays the sole background source — this module has no
equivalent of it. Unioning backgrounds would double-count survey effort
between the two overlapping databases in exactly the way `labels.py`'s own
docstring warns a naive background must not: the whole point of target-group
sampling is that it carries the *same* bias as the presences, and merging
two databases' background pools without the same duplicate-suppression
presences get would reintroduce exactly the sampling-bias problem this
scheme exists to cancel.

**Simple offset paging is enough here, deliberately.** GBIF's `occurrence/
search` hard-caps at `offset + limit <= 100,000` — real for the wider
target-group query, irrelevant for what this module actually fetches (five
species, each under ~1,700 records over `NORTH_INDIAN_OCEAN` 2000-2013,
measured above). A predicate-download (GBIF's own answer for a result set
past that cap) needs a registered account and an async job, which this
problem's presence counts never require.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterator

import pandas as pd
import requests

from marine_ml import config

_API_ROOT = "https://api.gbif.org/v1/occurrence/search"
_PAGE_SIZE = 300  # GBIF's own per-request maximum for this endpoint.
_TIMEOUT_SECONDS = 60
_MAX_OFFSET = 100_000

# Same renamed shape `marine_ml.sources.obis._to_frame` produces, so a GBIF
# and an OBIS frame can be concatenated without a translation step.
# `occurrence_id`/`catalog_number` are the dedup keys `labels.union_presences`
# needs — see its own docstring for the occurrenceID-first, fallback-second
# scheme (much of GBIF's marine data is OBIS republished, so the same
# specimen commonly carries the same `occurrenceID` in both).
_COLUMNS = {
    "decimalLatitude": "latitude",
    "decimalLongitude": "longitude",
    "eventDate": "event_date",
    "scientificName": "scientific_name",
    "species": "species",
    "basisOfRecord": "basis_of_record",
    "datasetKey": "dataset_id",
    "institutionCode": "institution_code",
    "individualCount": "individual_count",
    "occurrenceID": "occurrence_id",
    "catalogNumber": "catalog_number",
}


class GbifError(RuntimeError):
    """Raised when GBIF cannot be queried or returns nothing usable."""


def _paged_request(params: dict) -> Iterator[dict]:
    """Yield occurrence records via GBIF's offset/limit paging.

    Refuses past `_MAX_OFFSET` rather than truncating silently — same
    reasoning `obis._paged_request` gives for its own hard stop, and the
    exact cap GBIF's own API enforces for this endpoint (a predicate
    download is GBIF's answer past it, and needs a registered account).
    """
    offset = 0
    while True:
        page_params = dict(params, limit=_PAGE_SIZE, offset=offset)
        try:
            response = requests.get(_API_ROOT, params=page_params, timeout=_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            raise GbifError(f"GBIF request failed: {exc}") from exc
        if not response.ok:
            raise GbifError(f"GBIF returned HTTP {response.status_code}: {response.text[:200]}")

        payload = response.json()
        results = payload.get("results", [])
        yield from results

        if payload.get("endOfRecords", True) or not results:
            return
        offset += _PAGE_SIZE
        if offset >= _MAX_OFFSET:
            raise GbifError(
                f"GBIF query exceeded the {_MAX_OFFSET:,}-record offset cap and would be "
                f"silently truncated: {params}. This module fetches named target species "
                "only, which should never approach this — narrow the query."
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
    # GBIF's eventDate is a plain ISO date or datetime string (unlike OBIS,
    # it does not publish "/"-joined ranges for these records), but parsed
    # the same tolerant way regardless — a source that started emitting a
    # range would degrade to a coerced NaT and be dropped, not silently
    # misparsed.
    starts = frame["event_date"].astype("string").str.split("/").str[0]
    frame["observation_date"] = (
        pd.to_datetime(starts, errors="coerce", utc=True, format="mixed").dt.tz_localize(None).dt.normalize()
    )

    return frame.dropna(subset=["latitude", "longitude", "observation_date"]).reset_index(drop=True)


def _slug(text: str) -> str:
    return text.lower().replace(" ", "_").replace("/", "_")


def _cached_query(cache_name: str, params: dict, refresh: bool) -> pd.DataFrame:
    config.ensure_directories()
    cached: Path = config.GBIF_RAW_DIR / f"{cache_name}.parquet"
    if cached.exists() and not refresh:
        return pd.read_parquet(cached)

    records = list(_paged_request(params))
    frame = _to_frame(records)
    frame.to_parquet(cached, index=False)
    return frame


def fetch_occurrences(
    scientific_name: str,
    region: config.Region = config.DEFAULT_REGION,
    start: date = config.DEFAULT_START,
    end: date = config.DEFAULT_END,
    refresh: bool = False,
) -> pd.DataFrame:
    """Presence records for one species within `region` and the date range."""
    params = {
        "scientificName": scientific_name,
        "geometry": region.wkt,
        "eventDate": f"{start.isoformat()},{end.isoformat()}",
        "hasCoordinate": "true",
    }
    cache = f"occ_{_slug(scientific_name)}_{region.name}_{start}_{end}"
    frame = _cached_query(cache, params, refresh)
    return frame.assign(scientific_name=scientific_name)


def fetch_all_target_species(
    species: dict[str, str] | None = None,
    region: config.Region = config.DEFAULT_REGION,
    start: date = config.DEFAULT_START,
    end: date = config.DEFAULT_END,
    refresh: bool = False,
) -> pd.DataFrame:
    """Presence records for every configured target species, concatenated.

    Mirrors `obis.fetch_all_target_species` exactly — same species keys, same
    empty-frames-dropped behaviour — so `labels.union_presences` receives two
    directly comparable frames.
    """
    species = species or config.TARGET_SPECIES
    frames = [
        fetch_occurrences(name, region, start, end, refresh).assign(species_key=key)
        for key, name in species.items()
    ]
    frames = [f for f in frames if not f.empty]
    if not frames:
        raise GbifError(
            f"no GBIF occurrence records for any target species in {region.name} "
            f"between {start} and {end}"
        )
    return pd.concat(frames, ignore_index=True)
