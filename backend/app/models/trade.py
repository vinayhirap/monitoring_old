"""Order/position persistence."""
from datetime import datetime
from sqlalchemy import String, DateTime, Float, Integer, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"), nullable=True)

    broker: Mapped[str] = mapped_column(String(32), default="angelone")
    broker_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    exchange: Mapped[str] = mapped_column(String(16), default="NSE")
    instrument_type: Mapped[str] = mapped_column(String(16), default="EQ")  # EQ/FUT/CE/PE
    side: Mapped[str] = mapped_column(String(8))                            # BUY/SELL
    qty: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")      # PENDING/FILLED/CANCELLED/REJECTED
    is_paper: Mapped[bool] = mapped_column(Boolean, default=True)

    pnl: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
