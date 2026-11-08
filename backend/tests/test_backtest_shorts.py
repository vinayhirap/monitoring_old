import numpy as np, pandas as pd
from app.engines import backtest


def _downtrend(n=320, seed=4):
    rng = np.random.default_rng(seed)
    p = 200 * np.exp(np.cumsum(rng.normal(-0.004, 0.012, n)))
    idx = pd.bdate_range("2024-01-01", periods=n)
    return pd.DataFrame({"open": p, "high": p * 1.006, "low": p * 0.994,
                         "close": p, "volume": 1e6}, index=idx)


def test_backtest_can_take_short_trades():
    r = backtest.run("X", _downtrend(), lookback_bars=240, warmup_bars=60,
                     confidence_threshold=60)
    dirs = {t["direction"] for t in r.trades}
    assert "SHORT" in dirs, f"no SHORT trades were possible: {dirs}"
