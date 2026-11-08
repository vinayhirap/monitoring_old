"""Application settings loaded from .env."""
from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from loguru import logger


def _clean_credential(v: str | None) -> str:
    """Defensive scrubbing of credential values from .env.

    Catches the common mistake where a user copies the placeholder/comment text
    from .env.example as the value. Examples we reject:
      • starts with '#'            → it's a comment, treat as empty
      • starts with '<'            → "<your-api-key-here>" placeholder
      • contains 'optional'        → likely the comment "optional — leave blank…"
      • contains 'your-' or 'change-me'  → placeholder text
    """
    if v is None:
        return ""
    v = str(v).strip().strip('"').strip("'")
    if not v:
        return ""
    if v.startswith("#") or v.startswith("<"):
        logger.warning("Credential value looks like a comment/placeholder ({!r}) — treating as empty",
                        v[:60])
        return ""
    bad_phrases = ("optional", "leave blank", "your-", "change-me", "your api", "your client",
                   "your totp", "paste here", "TODO", "FIXME", "example")
    low = v.lower()
    if any(p in low for p in bad_phrases):
        logger.warning("Credential value looks like placeholder text ({!r}) — treating as empty",
                        v[:80])
        return ""
    return v


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # App
    app_env: str = "development"
    secret_key: str = "change-me"
    database_url: str = "sqlite:///./marketlens.db"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Redis (optional — graceful in-memory fallback when blank)
    redis_url: str = ""

    # Celery (optional — synchronous in-process execution when blank)
    celery_broker_url: str = ""
    celery_result_backend: str = ""

    # ML
    ml_models_dir: str = "./ml_models"
    ml_min_training_samples: int = 500

    # TimescaleDB — when DATABASE_URL points to postgres://, create_hypertables=True
    # converts ohlcv table into a hypertable on startup.
    create_hypertables: bool = True

    # Angel One
    angelone_api_key: str = ""
    angelone_client_code: str = ""
    angelone_password: str = ""
    angelone_totp_secret: str = ""

    # LIVE_ONLY — when True the backend refuses to serve synthetic/paper data.
    # All endpoints that need market data will return 503 if the broker is not
    # authenticated, and the auto-login retries every 5 minutes in the background.
    live_only: bool = False

    # Astrology
    astro_latitude: float = 19.0760
    astro_longitude: float = 72.8777
    astro_timezone: str = "Asia/Kolkata"
    astro_ayanamsa: str = "LAHIRI"

    # Risk
    risk_max_daily_loss_pct: float = 2.0
    risk_max_position_pct: float = 5.0
    risk_default_rr: float = 2.0

    # ----- Defensive credential cleaning -----
    @field_validator("angelone_api_key", "angelone_client_code",
                      "angelone_password", "angelone_totp_secret", mode="before")
    @classmethod
    def _scrub(cls, v):
        return _clean_credential(v)

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def paper_mode(self) -> bool:
        """True when Angel One credentials are insufficient for live login.
        Minimum for live mode: api_key + client_code + MPIN/password + totp_secret.
        (Angel One's SmartAPI ALWAYS requires the 4-digit MPIN even when TOTP is enabled.)"""
        return not (
            self.angelone_api_key
            and self.angelone_client_code
            and self.angelone_password
            and self.angelone_totp_secret
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
