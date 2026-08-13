"""Shared configuration for the Marine Data Fusion Layer.

One region, one common grid, one set of paths — both problem statements (HAB
early warning and fish habitat / PFZ) read from here so they see an identical
view of ocean state (ML Technical Approach, sections 2 and 5).

Credentials are read from the backend's untracked ``backend/.env`` rather than
duplicated, so there is a single place where Copernicus/NASA/GFW secrets live.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
BACKEND_ENV = REPO_ROOT / "backend" / ".env"

load_dotenv(BACKEND_ENV, override=False)
load_dotenv(PROJECT_ROOT / ".env", override=False)


# --------------------------------------------------------------------------
# Region & grid
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Region:
    """A named lon/lat box. ``west``/``east`` are longitudes, ``south``/``north``
    latitudes — always min/max normalised at construction so a caller passing
    them the wrong way round can't silently produce an empty subset."""

    name: str
    west: float
    east: float
    south: float
    north: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "west", min(self.west, self.east))
        object.__setattr__(self, "east", max(self.west, self.east))
        object.__setattr__(self, "south", min(self.south, self.north))
        object.__setattr__(self, "north", max(self.south, self.north))

    @property
    def wkt(self) -> str:
        """Closed WKT polygon, for the OBIS/GBIF ``geometry`` parameter."""
        w, e, s, n = self.west, self.east, self.south, self.north
        return f"POLYGON(({w} {s}, {e} {s}, {e} {n}, {w} {n}, {w} {s}))"

    def contains(self, lat: float, lon: float) -> bool:
        return self.south <= lat <= self.north and self.west <= lon <= self.east


# Northern Indian Ocean — the Arabian Sea / Bay of Bengal coastal belt that
# INCOIS issues PFZ advisories and Algal Bloom Information Service bulletins
# for. Chosen over the full Indian Ocean because occurrence-record density
# collapses outside it (verified against OBIS while building this pipeline:
# a 68-76E/8-22N box returns single-digit records for most target species,
# this box returns 280-400 for the tunas).
NORTH_INDIAN_OCEAN = Region("north_indian_ocean", west=55.0, east=95.0, south=-5.0, north=25.0)

# Smaller Arabian Sea box — fast iteration / smoke runs, and the HAB region.
ARABIAN_SEA = Region("arabian_sea", west=68.0, east=78.0, south=6.0, north=23.0)

# --- HAB regions ----------------------------------------------------------
#
# The HAB problem is deliberately **multi-region rather than global**, and the
# arithmetic is why. The Arabian Sea store is 3.9M rows / 1.59 GB over ~1,780
# ocean cells at 0.25 degrees; the global ocean is ~736,000 such cells, so the
# same six years worldwide is ~1.6 billion rows and ~650 GB. Coarsening is not
# the escape either — 1 degree is ~110 km, wider than most blooms.
#
# It would also be the wrong shape of data. Blooms are a coastal and upwelling
# phenomenon, so most of that 650 GB would be open-ocean rows that are
# near-constant negatives: enormous cost to make the positive class rarer.
#
# So: bloom-prone boxes, each its own feature store and model, each keeping
# daily fields at 0.25 degrees. Thresholds and climatology are fitted **per
# region** (see the pipeline) — they define what counts as a bloom, and one
# region's distribution must not define another's labels.
BAY_OF_BENGAL = Region("bay_of_bengal", west=80.0, east=95.0, south=5.0, north=22.0)
BENGUELA = Region("benguela", west=8.0, east=20.0, south=-34.0, north=-17.0)
CALIFORNIA_CURRENT = Region(
    "california_current", west=-127.0, east=-115.0, south=30.0, north=43.0
)
BALTIC_SEA = Region("baltic_sea", west=12.0, east=30.0, south=53.0, north=66.0)

# Ordered with the Arabian Sea first because it is the control: it is the only
# box with a known-good result to reproduce, so it is rebuilt and checked
# before any fetch is spent on the others.
HAB_REGIONS: dict[str, Region] = {
    "arabian_sea": ARABIAN_SEA,
    "bay_of_bengal": BAY_OF_BENGAL,
    "benguela": BENGUELA,
    "california_current": CALIFORNIA_CURRENT,
    "baltic_sea": BALTIC_SEA,
}

# The whole ocean, for the worldwide habitat model.
#
# North is 90 but **south is -80, not -90**: the Copernicus global grid stops
# near there, and asking past it buys empty rows rather than an error. Nothing
# in the target-species range is south of the Antarctic Circumpolar Current
# anyway.
#
# Worth knowing before reaching for this: going global multiplies *label
# density*, not the usable window. Measured against OBIS on 2026-08-10, target
# species 2000-2013 vs 2014-2025 — worldwide: yellowfin 67,780 -> 772,
# skipjack 18,759 -> 272, bigeye 29,982 -> 59. **The post-2014 drought that
# HABITAT_END records is global, not an artefact of the regional box.** It is
# the same cliff in every basin, so no amount of widening moves the window;
# what widening buys is ~170x more records inside it (~117,000 vs ~800).
#
# The two Indian coastal species do not benefit: oil sardine has 112 records
# worldwide and *all of them* are already inside NORTH_INDIAN_OCEAN, Indian
# mackerel 243. They stay in the pooled table (see fish_habitat labels.py,
# which stacks species deliberately so sparse ones borrow strength) but expect
# no gain for them from going global.
GLOBAL_OCEAN = Region("global_ocean", west=-180.0, east=180.0, south=-80.0, north=90.0)

DEFAULT_REGION = NORTH_INDIAN_OCEAN

# Common analysis grid, in degrees. 0.25 matches the Copernicus BGC product's
# native resolution — the coarsest input — so gridding is a downsample of the
# 0.083 physics rather than an invented upsample of biogeochemistry.
# Section 5 of the approach doc calls for resolution-aware regridding; this is
# the knob, and nearshore work should lower it with a matching regional product.
GRID_RESOLUTION = 0.25


# --------------------------------------------------------------------------
# Temporal defaults
# --------------------------------------------------------------------------

# Copernicus "my" (multi-year reanalysis) products, not the near-real-time
# analysis-forecast ones the backend map uses: training needs a long, stable,
# consistently-reprocessed history, and NRT products only reach back to ~2022.
DEFAULT_START = date(2019, 1, 1)
DEFAULT_END = date(2021, 12, 31)

# --- Problem B (fish habitat / PFZ) ---------------------------------------
# Bounded by *label* availability, not by what Copernicus can serve. OBIS
# occurrence records for the target species in this region are concentrated
# in 2000-2013 and effectively stop after 2014 (verified against the API:
# ~800 records across the five species in this window, single digits after).
# Training outside this window would mean environmental fields with no labels
# attached to them.
HABITAT_START = date(2000, 1, 1)
HABITAT_END = date(2013, 12, 31)

# --- Problem A (HAB early warning) ----------------------------------------
# Daily fields are non-negotiable for a t+3/t+5/t+7 forecast, so the region is
# what gives (see ARABIAN_SEA) — but the *span* is set by interannual
# variability, and this was measured rather than guessed.
#
# An earlier 2020-2021 window put exactly one southwest-monsoon bloom season
# in training, and the 2021 season ran ~40% greener than 2020's (August mean
# chlorophyll 0.229 vs 0.164 mg/m3; validation-period p99 2.11 vs 0.53). A
# model fitted through May 2021 and asked about September 2021 scored
# ROC-AUC 0.53 — chance. The same model trained three months closer to the
# test period scored 0.76. That gap is not a tuning problem, it is a model
# that has never seen the regime it is being asked about.
#
# Six years puts five monsoon seasons in the training period instead of one.
HAB_START = date(2016, 1, 1)
HAB_END = date(2021, 12, 31)

# Chronological, never random (doc 3.6 / 3.7). Expressed as fractions of each
# problem's own span so the two pipelines share one splitting rule despite
# covering different periods; everything after TRAIN_FRACTION + VAL_FRACTION
# is held out and never seen during training or tuning.
TRAIN_FRACTION = 0.70
VALIDATION_FRACTION = 0.15


# --------------------------------------------------------------------------
# Copernicus dataset IDs
# --------------------------------------------------------------------------

# Access pattern here is "one bounded area, many timesteps", so every fetch
# goes through the arco-time-series service (fine lat/lon chunks, huge time
# chunks). arco-geo-series would be the wrong tool by orders of magnitude —
# see backend/services/download/providers/copernicus.py for the same call.
COPERNICUS_SERVICE = "arco-time-series"

# ...and the opposite pattern, for GLOBAL_OCEAN: whole globe, few timesteps,
# where one global timestep per chunk is exactly what is wanted. Measured
# 2026-08-10 on one year of global monthly physics coarsened to 0.25deg —
# geo-series 7.5s, time-series 89.0s, so ~12x. Pass this per call
# (`fetch_physics(service=...)`); do not change COPERNICUS_SERVICE itself,
# which would make every regional fetch pathological.
GLOBAL_COPERNICUS_SERVICE = "arco-geo-series"

PHYSICS_DATASET_ID = "cmems_mod_glo_phy_my_0.083deg_P1D-m"
PHYSICS_VARIABLES = ("thetao", "so", "uo", "vo", "zos", "mlotst")

BGC_DATASET_ID = "cmems_mod_glo_bgc_my_0.25deg_P1D-m"
BGC_VARIABLES = ("chl", "no3", "po4", "si", "o2", "nppv")

# Static bathymetry. NOAA ERDDAP's etopo180 griddap endpoint serves the same
# global relief grid GEBCO does, over plain HTTP with a bbox in the URL, and
# needs no account — so it is the practical access path for a 15-arc-sec-class
# depth/slope covariate.
BATHYMETRY_URL = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/etopo180.nc"


# --------------------------------------------------------------------------
# Species (Problem B)
# --------------------------------------------------------------------------

# Commercially significant species of the Indian EEZ with enough OBIS presence
# records in DEFAULT_REGION to model (record counts verified against the OBIS
# API, not assumed).
TARGET_SPECIES: dict[str, str] = {
    "yellowfin_tuna": "Thunnus albacares",
    "skipjack_tuna": "Katsuwonus pelamis",
    "bigeye_tuna": "Thunnus obesus",
    "indian_mackerel": "Rastrelliger kanagurta",
    "oil_sardine": "Sardinella longiceps",
}

# OBIS taxon id for Actinopterygii (ray-finned fishes). Background/pseudo-
# absence points are drawn from *this group's* occurrence records, not from
# random ocean points, so the background carries the same survey/sampling
# bias as the presences (doc 4.5, "target-group background sampling").
TARGET_GROUP_TAXON_ID = 10194


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
INTERIM_DIR = DATA_DIR / "interim"
PROCESSED_DIR = DATA_DIR / "processed"

COPERNICUS_RAW_DIR = RAW_DIR / "copernicus"
GEBCO_RAW_DIR = RAW_DIR / "gebco"
OBIS_RAW_DIR = RAW_DIR / "obis"

# The shared (lat, lon, date)-keyed feature store both problems read from.
FEATURE_STORE_DIR = PROCESSED_DIR / "feature_store"

MODELS_DIR = PROJECT_ROOT / "models"
REPORTS_DIR = PROJECT_ROOT / "reports"

_ALL_DIRS = (
    DATA_DIR, RAW_DIR, INTERIM_DIR, PROCESSED_DIR,
    COPERNICUS_RAW_DIR, GEBCO_RAW_DIR, OBIS_RAW_DIR,
    FEATURE_STORE_DIR, MODELS_DIR, REPORTS_DIR,
)


def ensure_directories() -> None:
    """Create the data/model/report tree. Called by the pipeline entry points
    rather than at import time, so importing config stays side-effect free."""
    for directory in _ALL_DIRS:
        directory.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# Credentials
# --------------------------------------------------------------------------


def copernicus_credentials() -> tuple[str, str]:
    """Copernicus Marine username/password from ``backend/.env``."""
    username = os.getenv("COPERNICUS_USERNAME", "")
    password = os.getenv("COPERNICUS_PASSWORD", "")
    if not username or not password:
        raise RuntimeError(
            "COPERNICUS_USERNAME / COPERNICUS_PASSWORD are not set. "
            f"Add them to {BACKEND_ENV} (or machine_learning/.env)."
        )
    return username, password


RANDOM_SEED = 42
