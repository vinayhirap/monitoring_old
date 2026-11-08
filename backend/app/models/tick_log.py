"""Tick log — live WebSocket ticks landed for replay/audit."""
from sqlalchemy import Column, String, Float, DateTime, Integer

from app.database import Base


class TickLog(Base):
    __tablename__ = "tick_log"

    id        = Column(Integer, primary_key=True, autoincrement=True)
    symbol    = Column(String(32), index=True, nullable=False)
    ts        = Column(DateTime, index=True, nullable=False)
    ltp       = Column(Float, nullable=False)
    bid       = Column(Float)
    ask       = Column(Float)
    volume    = Column(Float)
    source    = Column(String(16), default="angelone_ws")
