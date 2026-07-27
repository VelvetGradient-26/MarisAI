"""Application configuration."""

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

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
