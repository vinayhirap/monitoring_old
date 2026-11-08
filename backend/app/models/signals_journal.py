"""Signals journal — every emitted signal logged for outcome tracking.

This is the single most important table for proving (or disproving) edge.
Each row captures the full state of a signal at emission, then a background
job updates the outcome columns 1d / 5d / 20d later.
"""
from sqlalchemy import Column, String, Float, DateTime, Integer, Boolean, JSON, Index
from sqlalchemy.sql import func

from app.database import Base


class SignalJournalEntry(Base):
    __tablename__ = "signals_journal"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    emitted_at      = Column(DateTime, server_default=func.now(), index=True, nullable=False)
    symbol          = Column(String(32), index=True, nullable=False)
    exchange        = Column(String(8),  default="NSE")
    horizon         = Column(String(16), index=True)

    # Headline signal
    signal_label    = Column(String(16), index=True)      # STRONG_BUY..STRONG_SELL
    direction       = Column(String(8),  index=True)      # BULLISH/BEARISH/NEUTRAL
    confidence      = Column(Float)
    stars           = Column(Integer)

    # Entry plan snapshot
    entry           = Column(Float)
    stoploss        = Column(Float)
    target_1        = Column(Float)
    target_2        = Column(Float)
    target_3        = Column(Float)

    # Engine snapshot (JSONB on PG)
    engines_snapshot = Column(JSON)                       # all engine scores + biases at emission
    reasons          = Column(JSON)
    grade            = Column(JSON)                       # ProfessionalGrade.to_dict() if available

    # Outcome (populated by outcome_tracker cron)
    outcome_1d_pnl_pct       = Column(Float)
    outcome_5d_pnl_pct       = Column(Float)
    outcome_20d_pnl_pct      = Column(Float)
    outcome_target_hit       = Column(Integer)            # 0=none, 1=T1, 2=T2, 3=T3
    outcome_stoploss_hit     = Column(Boolean, default=False)
    outcome_max_favorable    = Column(Float)              # MFE — best price in trade
    outcome_max_adverse      = Column(Float)              # MAE — worst price in trade
    outcome_evaluated_at     = Column(DateTime)
    outcome_status           = Column(String(16), default="PENDING")  # PENDING/EVALUATED/STALE

    __table_args__ = (
        Index("ix_signals_journal_sym_emitted", "symbol", "emitted_at"),
        Index("ix_signals_journal_status_emitted", "outcome_status", "emitted_at"),
    )
