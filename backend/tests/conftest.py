"""Pytest fixtures shared across the test suite.

Key fixtures:
  • synthetic_ohlcv     — a reproducible 200-bar OHLCV DataFrame
                          (seeded random walk, never network)
  • flat_ohlcv          — 200 bars with zero price movement
                          (used for engine edge-case tests)
  • crash_ohlcv         — 200 bars with a synthetic crash
                          (catches engines that mis-handle downside)
  • client              — FastAPI TestClient with the live app mounted
  • db_session          — empty in-memory SQLite session for unit tests

All fixtures are session-scoped where possible to keep the suite fast.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient


# ----------------------------------------------------------------------------
# OHLCV fixtures
# ----------------------------------------------------------------------------

def _make_ohlcv(*, n: int = 200, seed: int = 42,
                 trend_pct_per_bar: float = 0.0,
                 vol_pct: float = 1.5,
                 start_price: float = 1000.0) -> pd.DataFrame:
    """Reproducible OHLCV with a configurable trend and volatility.

    Deterministic given (n, seed, trend_pct_per_bar, vol_pct, start_price).
    """
    rng = np.random.default_rng(seed)
    returns = rng.normal(loc=trend_pct_per_bar / 100,
                          scale=vol_pct / 100, size=n)
    closes = start_price * np.exp(np.cumsum(returns))
    # OHLC derived from close with realistic intra-bar range
    opens = np.concatenate([[start_price], closes[:-1]])
    intrabar = rng.uniform(0.3, 1.2, size=n) * vol_pct / 100 * closes
    highs = np.maximum(opens, closes) + intrabar / 2
    lows  = np.minimum(opens, closes) - intrabar / 2
    volumes = rng.integers(100_000, 1_000_000, size=n)
    index = pd.date_range(end=datetime.utcnow(), periods=n, freq="D")
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": volumes,
    }, index=index)


@pytest.fixture(scope="session")
def synthetic_ohlcv() -> pd.DataFrame:
    """Default fixture — mild uptrend, normal volatility."""
    return _make_ohlcv(trend_pct_per_bar=0.05, vol_pct=1.5)


@pytest.fixture(scope="session")
def flat_ohlcv() -> pd.DataFrame:
    """Edge case — no movement. Engines must not divide-by-zero."""
    return _make_ohlcv(trend_pct_per_bar=0.0, vol_pct=0.05)


@pytest.fixture(scope="session")
def crash_ohlcv() -> pd.DataFrame:
    """Edge case — strong downtrend. Engines must produce BEARISH bias."""
    return _make_ohlcv(trend_pct_per_bar=-0.5, vol_pct=2.5)


@pytest.fixture(scope="session")
def trending_ohlcv() -> pd.DataFrame:
    """Strong uptrend. Engines must produce BULLISH bias."""
    return _make_ohlcv(trend_pct_per_bar=0.5, vol_pct=1.0)


@pytest.fixture(scope="session")
def tiny_ohlcv() -> pd.DataFrame:
    """Only 10 bars — too few for most engines. Used to test
    that engines return a graceful 'insufficient data' result
    instead of crashing."""
    return _make_ohlcv(n=10)


# ----------------------------------------------------------------------------
# FastAPI test client
# ----------------------------------------------------------------------------

@pytest.fixture(scope="session")
def client() -> TestClient:
    """TestClient with the actual app mounted. Used for endpoint smoke tests."""
    from app.main import app
    return TestClient(app)
