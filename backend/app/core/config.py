"""Application configuration."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str

    # Copernicus Marine
    COPERNICUS_USERNAME: str = ""
    COPERNICUS_PASSWORD: str = ""

    # NASA Earthdata
    NASA_BEARER_TOKEN: str = ""

    # Global Fishing Watch
    GFW_TOKEN: str = ""

    # aisstream.io live AIS websocket feed. Without this the vessel layer
    # serves an empty collection rather than failing — the rest of the map
    # must not depend on a live socket being up.
    AISSTREAM_API_KEY: str = ""

    # LLM insights provider (swap providers without touching code)
    LLM_PROVIDER: str = "gemini"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = ""
    LLM_BASE_URL: str = ""

    # Feedback form email delivery (Gmail SMTP + app password)
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""

    # Where the offline ML pipelines write their precomputed prediction grids.
    # The backend reads these files; it never imports `machine_learning` or
    # loads a model. Regenerate with `scripts/export_predictions.py` there.
    PREDICTIONS_DIR: str = str(
        Path(__file__).resolve().parents[3] / "machine_learning" / "exports"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
