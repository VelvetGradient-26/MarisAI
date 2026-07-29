"""Marine Data Fusion Layer — the shared spine under both Maris AI problem
statements (HAB early warning, fish habitat / PFZ).

Ingestion, regridding/QC, the shared feature store, the geometry and temporal
feature libraries, and the leakage-free validation harness all live here and
are used by both ``hab_early_warning`` and ``fish_habitat_prediction``. Only
labels and problem-specific derived features diverge (approach doc section 5).
"""

__all__ = ["config", "sources", "fusion", "features", "validation"]
