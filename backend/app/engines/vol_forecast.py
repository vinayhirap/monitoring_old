"""Volatility forecast engine — sizes RISK, does not predict DIRECTION.

Why this exists
---------------
Walk-forward tests on 2 years of Nifty / Bank Nifty 5-minute bars found no
directional edge from price alone (hit rate ~51%, ~0 bps before costs).
Volatility, however, clusters and IS forecastable (HAR beat the naive
baseline on QLIKE: +24% Bank Nifty, +8% Nifty). So the measurable
improvement available is in stop distance and position size, not in
"which way".

What it does
------------
* Builds a daily realised-vol series from intraday bars (sum of squared
  log returns) or, when only daily bars exist, from the Parkinson
  high-low estimator.
* Drops short / partial sessions (e.g. Diwali Muhurat trading, half days)
  — a one-hour session looks like a calm day and would poison the forecast.
* Fits HAR-RV on log vol (yesterday, 5-day mean, 22-day mean).
* Blends HAR with an EWMA(0.94) forecast in log space. HAR alone lost to
  naive on MAE for Nifty, so the blend is the safer default.
* Builds the 80% interval from the EMPIRICAL quantiles of out-of-sample
  residuals, not a normal assumption (HAR's Nifty coverage was 86%
  against a target of 80%, i.e. too wide).
* `walk_forward_eval` re-measures all of this on your own data so the
  claim can be checked instead of trusted.

Everything is pure numpy/pandas. No network, no broker, no DB.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

_MIN_DAYS = 60            # need this many clean sessions to fit HAR
_EWMA_LAMBDA = 0.94
_EPS = 1e-8
_PARKINSON_K = 1.0 / (4.0 * math.log(2.0))


# ---------------------------------------------------------------------------
# Realised-vol series
# ---------------------------------------------------------------------------

def daily_rv_from_intraday(df: pd.DataFrame, *, min_bar_frac: float = 0.8
                           ) -> tuple[pd.Series, int]:
    """Daily realised vol (fraction, e.g. 0.008 = 0.8%) from intraday bars.

    df needs a DatetimeIndex and a `close` column. Sessions with fewer than
    `min_bar_frac` x the median bar count are dropped. Returns
    (rv_series, bars_per_day).
    """
    if df is None or len(df) < 100 or "close" not in df.columns:
        return pd.Series(dtype=float), 0
    close = df["close"].astype(float)
    close = close[close > 0]
    day = close.index.normalize()
    lr = np.log(close).diff()
    lr[day != pd.Series(day, index=close.index).shift(1).values] = np.nan  # no overnight
    counts = lr.groupby(day).count()
    if counts.empty:
        return pd.Series(dtype=float), 0
    bars = int(counts.median())
    keep = counts[counts >= max(5, int(bars * min_bar_frac))].index
    rv = np.sqrt((lr ** 2).groupby(day).sum())
    rv = rv[rv.index.isin(keep)]
    rv = rv[rv > 0]
    return rv, bars


def daily_rv_from_daily_ohlc(df: pd.DataFrame) -> pd.Series:
    """Parkinson high-low sigma per day (fraction). Needs high & low."""
    if df is None or len(df) < _MIN_DAYS or not {"high", "low"} <= set(df.columns):
        return pd.Series(dtype=float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    ok = (h > 0) & (l > 0) & (h >= l)
    s = np.sqrt(_PARKINSON_K * np.log(h[ok] / l[ok]) ** 2)
    return s[s > 0]


# ---------------------------------------------------------------------------
# Forecasting core
# ---------------------------------------------------------------------------

def _har_design(lv: np.ndarray, rv: np.ndarray):
    """Rows t=21..n-2: X from info up to t, y = log rv[t+1]."""
    n = len(lv)
    rows, ys = [], []
    for t in range(21, n - 1):
        m5 = math.log(rv[t - 4:t + 1].mean() + _EPS)
        m22 = math.log(rv[t - 21:t + 1].mean() + _EPS)
        rows.append((1.0, lv[t], m5, m22))
        ys.append(lv[t + 1])
    return np.array(rows), np.array(ys)


def _har_next(rv: np.ndarray, ridge: float = 1e-3) -> tuple[float, np.ndarray]:
    """Fit on all of rv, return (log forecast for next day, residuals)."""
    lv = np.log(rv + _EPS)
    X, y = _har_design(lv, rv)
    if len(y) < 20:
        raise ValueError("not enough history for HAR")
    A = X.T @ X + ridge * np.eye(X.shape[1])
    beta = np.linalg.solve(A, X.T @ y)
    res = y - X @ beta
    x_next = np.array([1.0, lv[-1],
                       math.log(rv[-5:].mean() + _EPS),
                       math.log(rv[-22:].mean() + _EPS)])
    return float(x_next @ beta), res


def _ewma_next(rv: np.ndarray, lam: float = _EWMA_LAMBDA) -> float:
    var = float(rv[0] ** 2)
    for r in rv[1:]:
        var = lam * var + (1 - lam) * float(r) ** 2
    return 0.5 * math.log(var + _EPS)


@dataclass
class VolForecast:
    ok: bool
    sigma_day_pct: float = 0.0          # 1-sigma move for next session, %
    range80_pct: tuple = (0.0, 0.0)     # empirical 80% interval on sigma, %
    sigma_30m_pct: float = 0.0          # 1-sigma over 6 intraday bars (~30 min)
    method: str = ""
    n_days: int = 0
    bars_per_day: int = 0
    dropped_short_sessions: int = 0
    blend_weight_har: float = 0.0
    regime: str = "NORMAL"              # LOW_VOL / NORMAL / HIGH_VOL vs own history
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["range80_pct"] = list(self.range80_pct)
        return d


_W_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)


def _trailing_oos(arr: np.ndarray, n_oos: int):
    """One-step-ahead HAR and EWMA log forecasts for the last n_oos days,
    each fitted only on data available at that time."""
    start = max(len(arr) - n_oos - 1, 60)
    har, ewm, act = [], [], []
    for t in range(start, len(arr) - 1):
        train = arr[:t + 1]
        h, _ = _har_next(train)
        har.append(h)
        ewm.append(_ewma_next(train))
        act.append(math.log(arr[t + 1] + _EPS))
    return np.array(har), np.array(ewm), np.array(act)


def select_weight(arr: np.ndarray, n_oos: int = 120) -> tuple[float, np.ndarray]:
    """Pick the HAR weight that minimised out-of-sample QLIKE on this
    symbol's own recent history, and return its OOS log errors (used for
    the empirical interval). Avoids hard-coding a blend that may not suit
    every instrument."""
    har, ewm, act = _trailing_oos(arr, n_oos)
    best_w, best_q, best_err = 0.5, float("inf"), None
    for w in _W_GRID:
        lf = w * har + (1 - w) * ewm
        q = float(np.mean([_qlike(math.exp(a_), math.exp(f_)) for a_, f_ in zip(act, lf)]))
        if q < best_q:
            best_w, best_q, best_err = w, q, act - lf
    return best_w, best_err


def forecast_from_rv(rv: pd.Series | np.ndarray, *, w_har: float | None = None,
                     bars_per_day: int = 0) -> VolForecast:
    """w_har=None (default) chooses the blend weight by walk-forward on the
    symbol's own history; pass a float to force one."""
    arr = np.asarray(rv, dtype=float)
    arr = arr[np.isfinite(arr) & (arr > 0)]
    if len(arr) < _MIN_DAYS + 40:
        return VolForecast(ok=False, n_days=len(arr),
                           warnings=[f"Need >= {_MIN_DAYS + 40} clean sessions, have {len(arr)}"])
    try:
        har_log, _ = _har_next(arr)
        ew_log = _ewma_next(arr)
        w, err = select_weight(arr)
        if w_har is not None:
            w = float(w_har)
            err = err  # interval still taken from OOS errors of the selected blend
    except Exception as e:                      # singular fit etc.
        return VolForecast(ok=False, n_days=len(arr), warnings=[f"HAR failed: {e}"])
    log_f = w * har_log + (1 - w) * ew_log
    sigma = math.exp(log_f)
    lo = math.exp(log_f + float(np.quantile(err, 0.10)))
    hi = math.exp(log_f + float(np.quantile(err, 0.90)))

    hist = np.log(arr[-250:] + _EPS)
    q_lo, q_hi = np.quantile(hist, [0.25, 0.75])
    regime = "HIGH_VOL" if log_f > q_hi else "LOW_VOL" if log_f < q_lo else "NORMAL"

    s30 = 0.0
    warns: list[str] = []
    if bars_per_day > 6:
        s30 = sigma * math.sqrt(6.0 / bars_per_day)
        warns.append("30-min sigma assumes flat intraday variance; the open and "
                     "close are usually more volatile than midday.")
    return VolForecast(
        ok=True, sigma_day_pct=round(sigma * 100, 3),
        range80_pct=(round(lo * 100, 3), round(hi * 100, 3)),
        sigma_30m_pct=round(s30 * 100, 3),
        method=f"HAR/EWMA blend (w_har={w}, chosen by walk-forward)", n_days=len(arr),
        bars_per_day=bars_per_day, blend_weight_har=w,
        regime=regime, warnings=warns,
    )


def forecast(df: pd.DataFrame, *, intraday: Optional[bool] = None,
             w_har: float | None = None) -> VolForecast:
    """Forecast next-session vol from an OHLC dataframe (intraday or daily)."""
    if df is None or len(df) == 0:
        return VolForecast(ok=False, warnings=["empty dataframe"])
    if intraday is None:
        intraday = (isinstance(df.index, pd.DatetimeIndex) and len(df) > 200
                    and df.index.normalize().nunique() < len(df) / 3)
    dropped = 0
    if intraday:
        rv, bars = daily_rv_from_intraday(df)
        total_days = df.index.normalize().nunique()
        dropped = max(0, total_days - len(rv))
    else:
        rv, bars = daily_rv_from_daily_ohlc(df), 0
    out = forecast_from_rv(rv, w_har=w_har, bars_per_day=bars)
    out.dropped_short_sessions = dropped
    return out


# ---------------------------------------------------------------------------
# Walk-forward evaluation (so the claims can be re-measured on real data)
# ---------------------------------------------------------------------------

def _qlike(actual: float, fc: float) -> float:
    r = (actual ** 2 + _EPS) / (fc ** 2 + _EPS)
    return r - math.log(r) - 1.0


def walk_forward_eval(rv: pd.Series | np.ndarray, *, min_train: int = 120,
                      w_har: float = 0.5, min_err_for_interval: int = 40) -> dict:
    """Expanding-window one-step-ahead test vs naive / 20d mean / EWMA.

    Returns mean QLIKE (lower is better), improvement vs naive in %, MAE of
    sigma in bps, and coverage of the blend's empirical 80% interval. The
    interval at each step uses ONLY the blend's past out-of-sample errors,
    i.e. what was knowable at forecast time.
    """
    a = np.asarray(rv, dtype=float)
    a = a[np.isfinite(a) & (a > 0)]
    if len(a) < min_train + 60:
        return {"ok": False, "reason": f"need >= {min_train + 60} sessions, have {len(a)}"}
    names = ["har", "blend", "naive", "mean20", "ewma"]
    q = {n: [] for n in names}
    mae = {n: [] for n in names}
    cover, errs = [], []
    for t in range(min_train, len(a) - 1):
        train, actual = a[:t + 1], a[t + 1]
        har_log, _ = _har_next(train)
        ew_log = _ewma_next(train)
        bl_log = w_har * har_log + (1 - w_har) * ew_log
        fc = {"har": math.exp(har_log), "blend": math.exp(bl_log),
              "naive": float(train[-1]), "mean20": float(train[-20:].mean()),
              "ewma": math.exp(ew_log)}
        for n in names:
            q[n].append(_qlike(actual, fc[n]))
            mae[n].append(abs(actual - fc[n]))
        if len(errs) >= min_err_for_interval:
            lo = math.exp(bl_log + float(np.quantile(errs, 0.10)))
            hi = math.exp(bl_log + float(np.quantile(errs, 0.90)))
            cover.append(lo <= actual <= hi)
        errs.append(math.log(actual + _EPS) - bl_log)
    base = float(np.mean(q["naive"]))
    out = {"ok": True, "oos_days": len(q["naive"]), "models": {}}
    for n in names:
        m = float(np.mean(q[n]))
        out["models"][n] = {
            "qlike": round(m, 4),
            "vs_naive_pct": round((base - m) / base * 100, 1) if base else 0.0,
            "mae_sigma_bps": round(float(np.mean(mae[n])) * 1e4, 1),
        }
    out["blend_80pct_coverage"] = round(float(np.mean(cover)) * 100, 1) if cover else None
    return out


# ---------------------------------------------------------------------------
# Sizing helpers
# ---------------------------------------------------------------------------

def stop_distance_pct(sigma_pct: float, *, horizon_frac: float = 1.0,
                      k: float = 1.0) -> float:
    """Stop distance in % = k x sigma over the holding horizon.

    horizon_frac is the share of one session you expect to hold
    (0.25 ~ a couple of hours). Variance scales with time so sigma scales
    with sqrt(horizon_frac).
    """
    return max(0.0, k * sigma_pct * math.sqrt(max(horizon_frac, 0.0)))
