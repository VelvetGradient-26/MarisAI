from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Data Directories
DATA_DIR = PROJECT_ROOT / "data"

RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
INTERIM_DIR = DATA_DIR / "interim"

# Raw Data Sources
OBIS_DIR = RAW_DIR / "obis"

COPERNICUS_DIR = RAW_DIR / "copernicus"
COPERNICUS_PHYSICS_DIR = COPERNICUS_DIR / "physics"
COPERNICUS_BGC_DIR = COPERNICUS_DIR / "biogeochemistry"
COPERNICUS_METADATA_DIR = COPERNICUS_DIR / "metadata"

GEBCO_DIR = RAW_DIR / "gebco"
NASA_DIR = RAW_DIR / "nasa"
GBIF_DIR = RAW_DIR / "gbif"

# Processed Data
FEATURES_DIR = PROCESSED_DIR / "features"
MERGED_DIR = PROCESSED_DIR / "merged"
TRAINING_DIR = PROCESSED_DIR / "training"

# Models
MODELS_DIR = PROJECT_ROOT / "models"

# Reports
REPORTS_DIR = PROJECT_ROOT / "reports"

# Create Directories
DIRECTORIES = [
    DATA_DIR,
    RAW_DIR,
    PROCESSED_DIR,
    INTERIM_DIR,

    OBIS_DIR,

    COPERNICUS_DIR,
    COPERNICUS_PHYSICS_DIR,
    COPERNICUS_BGC_DIR,
    COPERNICUS_METADATA_DIR,

    GEBCO_DIR,
    NASA_DIR,
    GBIF_DIR,

    FEATURES_DIR,
    MERGED_DIR,
    TRAINING_DIR,

    MODELS_DIR,
    REPORTS_DIR,
]

for directory in DIRECTORIES:
    directory.mkdir(parents=True, exist_ok=True)

# Indian Ocean Bounding Box
INDIAN_OCEAN = {
    "min_lat": -45.0,
    "max_lat": 30.0,
    "min_lon": 20.0,
    "max_lon": 120.0,
}

SPECIES = {
    "yellowfin_tuna": "Thunnus albacares",
    "skipjack_tuna": "Katsuwonus pelamis",
    "bigeye_tuna": "Thunnus obesus",
    "indian_mackerel": "Rastrelliger kanagurta",
    "sardine": "Sardinella longiceps",
    "swordfish": "Xiphias gladius",
    "mahi_mahi": "Coryphaena hippurus",
}