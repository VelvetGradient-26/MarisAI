"""Raw-zone ingestion: one self-contained module per external data source."""

from marine_ml.sources import copernicus, gebco, obis

__all__ = ["copernicus", "gebco", "obis"]
