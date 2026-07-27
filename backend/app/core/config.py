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

    # LLM insights provider (swap providers without touching code)
    LLM_PROVIDER: str = "gemini"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = ""
    LLM_BASE_URL: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
