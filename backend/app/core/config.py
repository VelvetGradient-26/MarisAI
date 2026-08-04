"""Application configuration."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Postgres. The SQLAlchemy schema under app/models/ is real and migrated,
    # but nothing in the app queries it — identity lives in MongoDB instead
    # (see MONGODB_URI). Defaulted rather than required so the app boots
    # without a Postgres it never connects to.
    DATABASE_URL: str = ""

    # MongoDB Atlas — users, saved locations, download history.
    MONGODB_URI: str = ""
    MONGODB_DB_NAME: str = "marisai"

    # Google OAuth (authorization-code flow, run server-side so the client
    # secret never reaches the browser). Create the client at
    # console.cloud.google.com -> APIs & Services -> Credentials.
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    # MUST be on the same origin that serves the app, not the backend's own
    # host:port. Cookies are scoped by host, so a callback landing anywhere
    # else means the browser withholds the OAuth state cookie (sign-in fails
    # verification) and the session cookie gets written to an origin the app
    # never reads. In dev that origin is the Vite server, which proxies /api
    # through to this backend; `localhost` and `127.0.0.1` are *different*
    # hosts for cookie purposes, so the two must not be mixed.
    OAUTH_REDIRECT_URI: str = "http://localhost:5173/api/v1/auth/callback"

    # Signs the session cookie. Generate with `openssl rand -hex 32`.
    # Rotating it invalidates every existing session.
    SESSION_SECRET: str = ""

    # Where /api/v1/auth/callback sends the browser once sign-in succeeds.
    FRONTEND_BASE_URL: str = "http://localhost:5173"

    # Comma-separated allowlist (see cors_origins). CORSMiddleware cannot use
    # "*" here: browsers reject a wildcard origin combined with
    # allow_credentials=True, which would silently break the session cookie.
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Whether to mark session cookies Secure. Leave unset to derive it from
    # FRONTEND_BASE_URL's scheme (see `cookie_secure`) — defaulting to a bare
    # False meant an HTTPS deployment that forgot this setting silently
    # shipped its session cookie over plaintext-eligible requests. Set it
    # explicitly only to override that inference.
    COOKIE_SECURE: bool | None = None

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

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def cookie_secure(self) -> bool:
        """Secure flag for session cookies.

        Inferred from the frontend's scheme when COOKIE_SECURE is unset, so
        the safe value is the one you get by doing nothing: an https frontend
        marks cookies Secure automatically, and a plain-http dev setup does
        not (where marking them Secure would stop the browser storing them at
        all, breaking local sign-in)."""
        if self.COOKIE_SECURE is not None:
            return self.COOKIE_SECURE
        return self.FRONTEND_BASE_URL.strip().lower().startswith("https://")


settings = Settings()
