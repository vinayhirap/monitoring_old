"""OHLCV time-series table — TimescaleDB hypertable when PG dialect used."""
from sqlalchemy import Column, String, Float, DateTime, Integer, Index

from app.database import Base


class OHLCVBar(Base):
    __tablename__ = "ohlcv_bars"
    # Composite primary key — symbol + timeframe + ts is unique. On Timescale,
    # `ts` is the time dimension for hypertable partitioning.
    symbol     = Column(String(32), primary_key=True, index=True)
    timeframe  = Column(String(8),  primary_key=True, index=True)
    ts         = Column(DateTime,   primary_key=True, index=True)
    open       = Column(Float, nullable=False)
    high       = Column(Float, nullable=False)
    low        = Column(Float, nullable=False)
    close      = Column(Float, nullable=False)
    volume     = Column(Float, default=0.0)
    source     = Column(String(16), default="angelone")

    __table_args__ = (
        Index("ix_ohlcv_sym_tf_ts_desc", "symbol", "timeframe", "ts"),
    )
