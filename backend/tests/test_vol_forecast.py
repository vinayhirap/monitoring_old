"""Tests for the volatility forecast engine and its stop-loss integration."""
import numpy as np
import pandas as pd
import pytest

from app.engines import vol_forecast as vf
from app.engines.stop_loss_engine import compute


def _clustered_rv(n=500, seed=1):
    rng = np.random.default_rng(seed)
    lv = np.zeros(n)
    lv[0] = np.log(0.008)
    for t in range(1, n):
        lv[t] = np.log(0.008) * 0.2 + 0.8 * lv[t - 1] + rng.normal(0, 0.25)
    return np.exp(lv)


def _intraday(days=120, bars=74, short_day=None, seed=2):
    rng = np.random.default_rng(seed)
    idx, px, p = [], [], 20000.0
    for d in range(days):
        day = pd.Timestamp("2025-01-01") + pd.tseries.offsets.BDay(d)
        n = 12 if d == short_day else bars
        for b in range(n):
            idx.append(day + pd.Timedelta(hours=9, minutes=15 + 5 * b))
            p *= np.exp(rng.normal(0, 0.0009))
            px.append(p)
    return pd.DataFrame({"close": px}, index=pd.DatetimeIndex(idx))


def test_forecast_positive_and_interval_ordered():
    f = vf.forecast_from_rv(_clustered_rv())
    assert f.ok and f.sigma_day_pct > 0
    assert f.range80_pct[0] < f.sigma_day_pct * 1.5
    assert f.range80_pct[0] < f.range80_pct[1]


def test_too_little_history_not_ok():
    assert not vf.forecast_from_rv(_clustered_rv(30)).ok


def test_short_session_is_dropped():
    df = _intraday(short_day=50)
    rv, bars = vf.daily_rv_from_intraday(df)
    assert bars in (73, 74)
    assert pd.Timestamp("2025-01-01") + pd.tseries.offsets.BDay(50) not in rv.index
    out = vf.forecast(df)
    assert out.ok and out.dropped_short_sessions == 1
    assert out.sigma_30m_pct > 0


def test_har_beats_naive_on_clustered_vol():
    ev = vf.walk_forward_eval(_clustered_rv(600), w_har=1.0)
    assert ev["ok"]
    assert ev["models"]["har"]["vs_naive_pct"] > 0
    assert 70 <= ev["blend_80pct_coverage"] <= 90


def test_auto_weight_prefers_har_when_vol_changes_fast():
    arr = _clustered_rv(600)
    w, err = vf.select_weight(arr)
    assert w >= 0.75 and len(err) > 50


def test_stop_distance_scales_with_sqrt_horizon():
    full = vf.stop_distance_pct(1.0, horizon_frac=1.0, k=1.5)
    quarter = vf.stop_distance_pct(1.0, horizon_frac=0.25, k=1.5)
    assert quarter == pytest.approx(full / 2)


def test_sl_engine_adds_volfc_candidate_and_stays_backward_compatible():
    base = compute(entry=100, direction="BULLISH", atr=2.0)
    r = compute(entry=100, direction="BULLISH", atr=2.0, vol_sigma_pct=1.2)
    assert any(c["method"] == "VOLFC" for c in r.candidates)
    assert r.recommended_sl < 100 and base.recommended_sl < 100


def test_sl_engine_warns_when_stop_inside_noise():
    r = compute(entry=100, direction="BEARISH", atr=0.2, swing_low=90,
                swing_high=100.5, vol_sigma_pct=3.0)
    assert any("noise" in w.lower() or "sigma" in w.lower() for w in r.warnings)
