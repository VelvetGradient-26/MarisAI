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

    # Tavily web search (services/web_search.py), the assistant's
    # controlled-internet tool. Without this the tool raises rather than
    # silently degrading — a web search that always returns nothing is
    # indistinguishable from a broken feature, so it is treated the same way
    # GFW_TOKEN's absence is (see services/gfw.py): a clear "not configured"
    # error the chat loop relays plainly, not an empty result set.
    TAVILY_API_KEY: str = ""

    # Sent as CrossRef's `mailto` query param (services/literature.py) to use
    # its documented "polite pool" — no key required either way, but omitting
    # it risks the shared anonymous pool's lower rate limit under load.
    CROSSREF_MAILTO: str = ""

    # HMAC key for services/watch_tokens.py's signed confirm/unsubscribe
    # tokens (sihtodo.md item 8). Not an external credential — a locally
    # generated app secret (any random string) — but treated the same way:
    # empty by default, and the create-a-watch endpoint raises a clear "not
    # configured" error rather than signing tokens with an empty key.
    WATCH_TOKEN_SECRET: str = ""

    # LLM insights provider (swap providers without touching code)
    LLM_PROVIDER: str = "gemini"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = ""
    LLM_BASE_URL: str = ""

    # Controlled internet tools for the Ocean Assistant's web_research
    # specialist (services/web_search.py, services/webpage.py,
    # services/literature.py — sihtodo.md item 4). Only web_search needs a
    # key: fetch_webpage has no provider, and services/literature.py's
    # Crossref backend is keyless. Without this, web_search degrades to a
    # clear "not configured" tool error rather than failing the assistant.
    TAVILY_API_KEY: str = ""

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

    # Logging. See app/core/logging.py — until it existed, nothing in the server
    # process configured logging at all and INFO from 31 stdlib-logging modules
    # was discarded at source.
    #
    # DEBUG is genuinely usable here rather than a firehose, because the noisy
    # third parties (httpx, copernicusmarine, botocore, s3fs) are pinned to
    # WARNING independently of this setting.
    LOG_LEVEL: str = "INFO"
    # One JSON object per line instead of the human format. For a deployment
    # that ships logs somewhere that parses them; off by default because the
    # normal reader here is a terminal.
    LOG_JSON: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()
