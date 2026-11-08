"""Retention must never delete signals before the outcome tracker can score them."""
from datetime import datetime, timedelta
import pytest


@pytest.fixture()
def sess_factory(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    from app.models import signals_journal as sj
    from app.services import signals_logger as sl
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng, tables=[sj.SignalJournalEntry.__table__])
    SessionLocal = sessionmaker(bind=eng)
    monkeypatch.setattr(sl, "SessionLocal", SessionLocal)
    return SessionLocal, sj.SignalJournalEntry, sl


def _row(E, age_days, status):
    kw = dict(symbol="X", direction="BULLISH", entry=100.0,
              emitted_at=datetime.utcnow() - timedelta(days=age_days),
              outcome_status=status)
    return E(**{k: v for k, v in kw.items() if hasattr(E, k)})


def test_default_retention_keeps_pending_and_recent_scored(sess_factory):
    SL, E, sl = sess_factory
    with SL() as s:
        s.add_all([_row(E, 20, "PENDING"), _row(E, 100, "PENDING"),
                   _row(E, 200, "EVALUATED"), _row(E, 50, "EVALUATED")])
        s.commit()
    out = sl.purge_older_than_days()
    assert out["deleted"] == 1          # only the 200-day EVALUATED row
    with SL() as s:
        ages = sorted((datetime.utcnow() - r.emitted_at).days for r in s.query(E))
    assert ages == [20, 50, 100]


def test_old_14_day_callers_cannot_starve_the_tracker(sess_factory):
    """Even if something still calls purge(days=14), PENDING rows younger than
    the pending retention floor (75d) survive so they can be scored."""
    SL, E, sl = sess_factory
    with SL() as s:
        s.add_all([_row(E, 20, "PENDING"), _row(E, 60, "PENDING"),
                   _row(E, 90, "PENDING"), _row(E, 20, "EVALUATED")])
        s.commit()
    out = sl.purge_older_than_days(days=14)
    assert out["deleted"] == 2          # 90d PENDING (past floor) + 20d EVALUATED
    with SL() as s:
        left = sorted((r.outcome_status, (datetime.utcnow() - r.emitted_at).days) for r in s.query(E))
    assert left == [("PENDING", 20), ("PENDING", 60)]


def test_maintenance_start_is_idempotent_and_run_once_never_raises(monkeypatch):
    from app.services import journal_maintenance as jm
    monkeypatch.setattr(jm, "_started", False)
    assert jm.start(first_delay_sec=3600) is True
    assert jm.start(first_delay_sec=3600) is False
    assert isinstance(jm.run_once(), dict)
