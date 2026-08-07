"""Application configuration."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Postgres. The SQLAlchemy schema under app/models/ is real and migrated,
    # but nothing in the app queries it. Defaulted rather than required so the
    # app boots without a Postgres it never connects to.
    #
    # Authentication was removed from the project (see docs/AUTH_REMOVAL.md),
    # taking the MongoDB, Google OAuth, session-secret and cookie settings with
    # it. Restoring sign-in means restoring those keys here as well as the
    # modules — the guide lists them.
    DATABASE_URL: str = ""

    # Where the frontend is served from. Still used for links and redirects
    # even though the OAuth callback that originally motivated it is gone.
    FRONTEND_BASE_URL: str = "http://localhost:5173"

    # Comma-separated allowlist (see cors_origins). CORSMiddleware cannot use
    # "*" here: browsers reject a wildcard origin combined with
    # allow_credentials=True, which stays enabled (see main.py).
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

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

    # Whether boot should kick off the forecast-grid rebuild. On by default,
    # because that boot-time call is what lets a fresh deployment start
    # producing grids instead of waiting twelve hours for the first scheduler
    # tick — and it already skips anything still fresh, so a restart is
    # normally free.
    #
    # It is worth switching off on a small development machine. The rebuild
    # walks every buildable variable, and one variable's build peaks around
    # 3 GB on its own; a restart that finds every grid stale pays that back to
    # back. Set FORECAST_GRID_REFRESH_ON_BOOT=false in backend/.env. The
    # scheduled job is unaffected, so grids still refresh while the server
    # runs — this only removes the thundering herd at startup.
    FORECAST_GRID_REFRESH_ON_BOOT: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()
