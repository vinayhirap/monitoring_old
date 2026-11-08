"""Per-user watchlist — symbols the user wants to track on the portal home."""
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, UniqueConstraint

from app.database import Base


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    user_id     = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    symbol      = Column(String(32), nullable=False)
    exchange    = Column(String(8),  default="NSE")
    added_at    = Column(DateTime, default=datetime.utcnow)
    sort_order  = Column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("user_id", "symbol", "exchange", name="uq_watchlist_user_symbol"),
    )
