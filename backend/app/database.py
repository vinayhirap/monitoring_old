"""Database session factory.

Supports SQLite (default — zero-config) and PostgreSQL (set DATABASE_URL to
`postgresql+psycopg2://user:pw@host:5432/db` or async `postgresql+asyncpg://...`).

When PostgreSQL is detected AND `create_hypertables=True` (default), startup
attempts to convert the `ohlcv_bars` table into a TimescaleDB hypertable.
The attempt is no-op safe — if Timescale isn't installed, we log a warning
and continue using plain PG tables.
"""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from sqlalchemy.exc import OperationalError, ProgrammingError
from loguru import logger

from app.config import settings


def _is_sqlite() -> bool:
    return settings.database_url.startswith("sqlite")


def _is_postgres() -> bool:
    return settings.database_url.startswith(("postgresql", "postgres"))


# Connection args + pool config tuned per dialect.
_engine_kwargs: dict = {"pool_pre_ping": True, "echo": False}
if _is_sqlite():
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
elif _is_postgres():
    # Sensible PG defaults for a single-VM deployment.
    _engine_kwargs.update({
        "pool_size": 10,
        "max_overflow": 20,
        "pool_recycle": 1800,
        "pool_timeout": 30,
    })

engine = create_engine(settings.database_url, **_engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Session:
    """FastAPI dependency — yields a session and closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_timescale_hypertables() -> None:
    """Convert time-series tables to hypertables if TimescaleDB is available.
    Safe no-op if extension missing or already converted.
    """
    if not _is_postgres() or not settings.create_hypertables:
        return
    hypertables = [
        ("ohlcv_bars",      "ts"),
        ("signals_journal", "emitted_at"),
        ("tick_log",        "ts"),
    ]
    with engine.begin() as conn:
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb;"))
        except (OperationalError, ProgrammingError) as e:
            logger.warning("TimescaleDB extension not available — using plain PG tables ({})",
                            e.__class__.__name__)
            return
        for table, time_col in hypertables:
            try:
                conn.execute(text(
                    f"SELECT create_hypertable('{table}', '{time_col}', if_not_exists => TRUE);"
                ))
                logger.info("hypertable ready: {} on {}", table, time_col)
            except (OperationalError, ProgrammingError) as e:
                logger.warning("hypertable creation skipped for {}: {}", table, e)


def init_db() -> None:
    """Create all tables (called on startup)."""
    # Import models so SQLAlchemy registers them.
    from app.models import signal, trade, user                        # noqa: F401
    # New advanced models
    try:
        from app.models import (
            ohlcv_bar, signals_journal, tick_log, watchlist, subscription,
            audit_log,   # noqa: F401
        )
    except ImportError as e:
        logger.warning("Advanced models not yet importable: {}", e)
    Base.metadata.create_all(bind=engine)
    _ensure_timescale_hypertables()
    logger.info("DB initialised — dialect: {}", "postgres" if _is_postgres() else
                                                  "sqlite" if _is_sqlite() else "other")
