"""Trade signal persistence."""
from datetime import datetime
from sqlalchemy import String, DateTime, Float, JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    exchange: Mapped[str] = mapped_column(String(16), default="NSE")
    signal: Mapped[str] = mapped_column(String(16))         # STRONG_BUY/BUY/NEUTRAL/SELL/STRONG_SELL
    trend: Mapped[str] = mapped_column(String(16))          # BULLISH/BEARISH/SIDEWAYS
    confidence: Mapped[float] = mapped_column(Float)        # 0..100
    entry: Mapped[float] = mapped_column(Float)
    stoploss: Mapped[float] = mapped_column(Float)
    targets: Mapped[list] = mapped_column(JSON)
    risk_reward: Mapped[float] = mapped_column(Float)
    capital_allocation_pct: Mapped[float] = mapped_column(Float, default=0.0)

    # Sub-engine scores (0..100)
    technical_score: Mapped[float] = mapped_column(Float, default=0.0)
    astro_score: Mapped[float] = mapped_column(Float, default=0.0)
    gann_score: Mapped[float] = mapped_column(Float, default=0.0)
    numerology_score: Mapped[float] = mapped_column(Float, default=0.0)
    options_score: Mapped[float] = mapped_column(Float, default=0.0)

    reasons: Mapped[dict] = mapped_column(JSON)             # {technical: "...", astro: "...", ...}
    timeframe: Mapped[str] = mapped_column(String(8), default="1d")
    horizon: Mapped[str] = mapped_column(String(16), default="SWING")  # INTRADAY/SWING/POSITIONAL

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
