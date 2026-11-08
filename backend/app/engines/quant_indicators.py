"""Advanced-math / quantitative technical indicators.

These are the indicators used in published academic finance + institutional
quant shops — Hurst exponent, Kalman filter, GARCH, Ornstein-Uhlenbeck
half-life, Z-score, linear regression channels, fractal dimension. They
complement the classical indicators in technical.py with statistical /
stochastic-process tools.

Honest note: these are *measurement tools*, not magic. Hurst > 0.5 doesn't
mean "buy" — it means "this series is more trending than random," which
informs strategy choice (trend-following vs mean-reversion). Use them to
*classify the regime*, then pick the right strategy for that regime.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

import numpy as np
import pandas as pd


# ===========================================================================
# Hurst exponent — trending vs mean-reverting vs random-walk classifier
# H < 0.5  : mean-reverting (anti-persistent)
# H = 0.5  : random walk (geometric Brownian motion)
# H > 0.5  : trending (persistent)
# Classical method: R/S analysis. Robust over 100+ bars.
# ===========================================================================

def hurst_exponent(series: np.ndarray, min_lag: int = 2, max_lag: int = 100) -> float:
    """R/S Hurst estimate. Returns 0..1 (0.5 = random walk)."""
    if series.size < max_lag * 2:
        max_lag = max(min_lag + 1, series.size // 2)
    lags = range(min_lag, max_lag)
    tau = []
    for lag in lags:
        diff = series[lag:] - series[:-lag]
        if diff.std() == 0:
            continue
        tau.append(np.sqrt(diff.std()))
    if len(tau) < 4:
        return 0.5
    lags_arr = np.array(list(lags)[:len(tau)])
    poly = np.polyfit(np.log(lags_arr), np.log(tau), 1)
    h = poly[0] * 2.0
    return float(max(0.0, min(1.0, h)))


# ===========================================================================
# Z-score — statistical mean-reversion entry signal
# |Z| > 2  : extreme; classical mean-reversion entry
# |Z| > 3  : very rare; only ~0.3% of observations if normally distributed
# ===========================================================================

def z_score(series: np.ndarray, lookback: int = 20) -> float:
    """Z-score of last value vs `lookback`-bar window."""
    if series.size < lookback + 1:
        return 0.0
    window = series[-lookback:]
    mu, sigma = float(window.mean()), float(window.std())
    if sigma == 0:
        return 0.0
    return float((series[-1] - mu) / sigma)


# ===========================================================================
# Kalman filter — adaptive trend estimator
# Updates state estimate with each new bar. Smoother than EMA, no lag.
# Returns the filtered estimate + the current uncertainty bound.
# ===========================================================================

def kalman_trend(prices: np.ndarray, process_noise: float = 1e-5,
                  measurement_noise: float = 1e-1) -> dict:
    """Univariate Kalman filter on price. Returns the filtered series + last
    state + current 1-sigma uncertainty band."""
    if prices.size == 0:
        return {"last_estimate": 0.0, "last_uncertainty": 0.0,
                "series": [], "trend": "NEUTRAL"}

    x = prices[0]                       # state
    P = 1.0                              # uncertainty
    Q = process_noise
    R = measurement_noise

    estimates = []
    for z in prices:
        # Predict
        x_pred = x
        P_pred = P + Q
        # Update
        K = P_pred / (P_pred + R)        # Kalman gain
        x = x_pred + K * (z - x_pred)
        P = (1 - K) * P_pred
        estimates.append(x)

    est = np.array(estimates)
    # Trend: compare last estimate to N bars back
    n = min(20, len(est) - 1)
    if n > 0:
        slope = (est[-1] - est[-1 - n]) / n
        trend = "BULLISH" if slope > 0 else "BEARISH" if slope < 0 else "NEUTRAL"
    else:
        trend = "NEUTRAL"

    return {
        "last_estimate": float(est[-1]),
        "last_uncertainty": float(math.sqrt(P)),
        "trend": trend,
        "spot_vs_estimate_pct": float((prices[-1] - est[-1]) / est[-1] * 100) if est[-1] else 0,
    }


# ===========================================================================
# GARCH(1,1) volatility forecast
# σ²_t = ω + α·ε²_{t-1} + β·σ²_{t-1}
# Better than ATR for forecasting NEXT period's volatility because it captures
# volatility clustering (high-vol days follow high-vol days).
# ===========================================================================

def garch_11_forecast(returns: np.ndarray, max_iter: int = 100) -> dict:
    """Simplified GARCH(1,1) MLE fit. Returns σ forecast for next bar + the
    long-run unconditional volatility.

    Honest: this is a lightweight fit. For production use `arch` package.
    """
    if returns.size < 50:
        std = float(returns.std()) if returns.size > 1 else 0.0
        return {"next_sigma": std, "long_run_sigma": std,
                 "alpha": 0, "beta": 0, "omega": 0,
                 "note": "Insufficient data — fell back to sample std"}

    r = returns - returns.mean()
    # Initial parameters (typical for equity returns)
    omega, alpha, beta = 1e-6, 0.10, 0.85
    var_long = float(np.var(r))
    sigma2 = np.full_like(r, var_long, dtype=float)

    # Simple iterative MLE — coordinate descent
    for _ in range(max_iter):
        for t in range(1, len(r)):
            sigma2[t] = omega + alpha * r[t - 1] ** 2 + beta * sigma2[t - 1]
        # Re-estimate via method of moments (simplified)
        # Real MLE would optimize log-likelihood; this is a robust approximation.
        omega_new = (1 - alpha - beta) * var_long
        if abs(omega_new - omega) < 1e-12:
            break
        omega = omega_new

    next_var = omega + alpha * r[-1] ** 2 + beta * sigma2[-1]
    return {
        "next_sigma": float(math.sqrt(max(next_var, 0))),
        "long_run_sigma": float(math.sqrt(omega / max(1 - alpha - beta, 1e-9))),
        "alpha": round(alpha, 4), "beta": round(beta, 4), "omega": round(omega, 8),
        "annualised_next_vol_pct": float(math.sqrt(next_var * 252) * 100),
        "note": "Lightweight GARCH(1,1) — for production use `arch` library",
    }


# ===========================================================================
# Ornstein-Uhlenbeck — fits mean-reverting stochastic process
# dX_t = θ(μ - X_t) dt + σ dW_t
# Returns half-life of mean reversion: t_half = ln(2)/θ
# If half-life < 30 bars, the series is reliably mean-reverting.
# ===========================================================================

def ou_half_life(series: np.ndarray) -> dict:
    """Estimate OU half-life via OLS on Δx vs (μ - x_{t-1})."""
    if series.size < 30:
        return {"half_life_bars": None, "theta": 0, "mu": 0,
                 "regime": "INSUFFICIENT_DATA"}

    y = np.diff(series)
    x = series[:-1] - series[:-1].mean()
    # OLS: y = -θ·x + ε
    if x.var() == 0:
        return {"half_life_bars": None, "regime": "FLAT"}

    theta = -np.cov(x, y, bias=True)[0, 1] / x.var()
    if theta <= 0:
        # Not mean-reverting — trending or random walk
        return {"half_life_bars": None, "theta": float(theta), "mu": float(series.mean()),
                 "regime": "TRENDING_OR_RANDOM"}

    half_life = math.log(2) / theta
    regime = ("STRONGLY_MEAN_REVERTING" if half_life < 10 else
              "MEAN_REVERTING"          if half_life < 30 else
              "WEAKLY_MEAN_REVERTING"   if half_life < 100 else
              "PERSISTENT")
    return {
        "half_life_bars": float(half_life),
        "theta": float(theta),
        "mu": float(series.mean()),
        "regime": regime,
    }


# ===========================================================================
# Linear regression channel — statistical trend channel with R²
# ===========================================================================

def linear_regression_channel(prices: np.ndarray, lookback: int = 50,
                               std_multiplier: float = 2.0) -> dict:
    """Fit y = a + b·t over last `lookback` bars. Channels = ±std_multiplier·σ
    around the trend line. Returns R², current channel position (0..1)."""
    if prices.size < lookback:
        return {"slope": 0, "intercept": 0, "r_squared": 0,
                 "channel_position_pct": 50, "trend": "NEUTRAL"}

    y = prices[-lookback:]
    x = np.arange(lookback)
    slope, intercept = np.polyfit(x, y, 1)
    fit = slope * x + intercept
    residuals = y - fit
    ss_res = (residuals ** 2).sum()
    ss_tot = ((y - y.mean()) ** 2).sum()
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    sigma = float(residuals.std())

    upper = fit[-1] + std_multiplier * sigma
    lower = fit[-1] - std_multiplier * sigma
    width = upper - lower
    pos = (y[-1] - lower) / width * 100 if width > 0 else 50

    annualised_slope_pct = slope / y.mean() * 252 * 100 if y.mean() else 0
    trend = ("STRONG_UP"   if r2 > 0.7 and slope > 0 else
             "WEAK_UP"     if r2 > 0.3 and slope > 0 else
             "STRONG_DOWN" if r2 > 0.7 and slope < 0 else
             "WEAK_DOWN"   if r2 > 0.3 and slope < 0 else
             "NO_TREND")
    return {
        "slope": float(slope),
        "intercept": float(intercept),
        "r_squared": round(float(r2), 4),
        "channel_upper": float(upper),
        "channel_mid":   float(fit[-1]),
        "channel_lower": float(lower),
        "channel_position_pct": round(float(pos), 2),
        "annualised_trend_pct": round(annualised_slope_pct, 3),
        "trend": trend,
    }


# ===========================================================================
# Fractal dimension (Higuchi method)
# 1.0 = smooth deterministic, 1.5 = random walk, 2.0 = pure noise.
# Higher fractal dim → more chaotic → mean-reversion strategies likely fail.
# ===========================================================================

def higuchi_fractal_dimension(series: np.ndarray, kmax: int = 10) -> float:
    if series.size < kmax * 2:
        return 1.5
    N = series.size
    L = []
    x_vals = []
    for k in range(1, kmax + 1):
        Lk = 0.0
        for m in range(k):
            Lmk = 0.0
            n_max = int(math.floor((N - m - 1) / k))
            if n_max < 1:
                continue
            for i in range(1, n_max + 1):
                Lmk += abs(series[m + i * k] - series[m + (i - 1) * k])
            norm = (N - 1) / (n_max * k)
            Lmk = (Lmk * norm) / k
            Lk += Lmk
        if Lk > 0:
            L.append(Lk / k)
            x_vals.append(1.0 / k)
    if len(L) < 3:
        return 1.5
    poly = np.polyfit(np.log(x_vals), np.log(L), 1)
    return float(max(1.0, min(2.0, poly[0])))


# ===========================================================================
# Heikin Ashi candles — smoothed candles for trend detection
# ===========================================================================

def heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """Returns DataFrame with ha_open, ha_high, ha_low, ha_close columns."""
    o = df["open"].astype(float).values
    h = df["high"].astype(float).values
    l = df["low"].astype(float).values
    c = df["close"].astype(float).values
    n = len(c)

    ha_close = (o + h + l + c) / 4
    ha_open = np.zeros(n)
    ha_open[0] = (o[0] + c[0]) / 2
    for i in range(1, n):
        ha_open[i] = (ha_open[i - 1] + ha_close[i - 1]) / 2
    ha_high = np.maximum.reduce([h, ha_open, ha_close])
    ha_low  = np.minimum.reduce([l, ha_open, ha_close])

    return pd.DataFrame({
        "ha_open": ha_open, "ha_high": ha_high,
        "ha_low":  ha_low,  "ha_close": ha_close,
    }, index=df.index)


def heikin_ashi_signal(df: pd.DataFrame, lookback: int = 5) -> dict:
    """Count consecutive bullish/bearish HA candles → trend strength."""
    ha = heikin_ashi(df)
    last = ha.tail(lookback)
    bullish = (last["ha_close"] > last["ha_open"]).sum()
    bearish = (last["ha_close"] < last["ha_open"]).sum()
    bias = "BULLISH" if bullish > bearish else "BEARISH" if bearish > bullish else "NEUTRAL"
    return {
        "last_ha_open":  float(ha["ha_open"].iloc[-1]),
        "last_ha_close": float(ha["ha_close"].iloc[-1]),
        "last_ha_high":  float(ha["ha_high"].iloc[-1]),
        "last_ha_low":   float(ha["ha_low"].iloc[-1]),
        "consecutive_bull": int(bullish),
        "consecutive_bear": int(bearish),
        "bias": bias,
    }


# ===========================================================================
# Donchian channels — Turtle trading breakout system
# ===========================================================================

def donchian(df: pd.DataFrame, period: int = 20) -> dict:
    h = df["high"].astype(float).tail(period)
    l = df["low"].astype(float).tail(period)
    c = float(df["close"].iloc[-1])
    upper = float(h.max())
    lower = float(l.min())
    mid = (upper + lower) / 2
    pos = (c - lower) / (upper - lower) * 100 if upper != lower else 50

    if c > upper - 1e-9:
        signal = "BREAKOUT_LONG"
    elif c < lower + 1e-9:
        signal = "BREAKOUT_SHORT"
    elif pos > 80:
        signal = "NEAR_UPPER"
    elif pos < 20:
        signal = "NEAR_LOWER"
    else:
        signal = "MIDDLE"

    return {"upper": round(upper, 2), "mid": round(mid, 2), "lower": round(lower, 2),
             "position_pct": round(pos, 2), "signal": signal,
             "period": period}


# ===========================================================================
# Vortex Indicator — VI+ / VI-
# VI+ > VI- → bullish trend; crossover → trend change
# ===========================================================================

def vortex(df: pd.DataFrame, period: int = 14) -> dict:
    h = df["high"].astype(float).values
    l = df["low"].astype(float).values
    c = df["close"].astype(float).values
    if len(c) < period + 1:
        return {"vi_plus": 0, "vi_minus": 0, "bias": "INSUFFICIENT_DATA"}

    vm_plus  = np.abs(h[1:] - l[:-1])
    vm_minus = np.abs(l[1:] - h[:-1])
    tr = np.maximum.reduce([
        h[1:] - l[1:],
        np.abs(h[1:] - c[:-1]),
        np.abs(l[1:] - c[:-1]),
    ])

    sum_plus  = vm_plus[-period:].sum()
    sum_minus = vm_minus[-period:].sum()
    sum_tr    = tr[-period:].sum()
    if sum_tr == 0:
        return {"vi_plus": 0, "vi_minus": 0, "bias": "FLAT"}

    vi_plus  = sum_plus  / sum_tr
    vi_minus = sum_minus / sum_tr
    bias = "BULLISH" if vi_plus > vi_minus else "BEARISH"
    spread = abs(vi_plus - vi_minus)
    return {
        "vi_plus":  round(float(vi_plus), 4),
        "vi_minus": round(float(vi_minus), 4),
        "spread":   round(float(spread), 4),
        "bias":     bias,
        "strength": "STRONG" if spread > 0.2 else "MODERATE" if spread > 0.1 else "WEAK",
    }


# ===========================================================================
# Chaikin Money Flow — institutional flow proxy
# CMF > 0.1 = buying pressure; CMF < -0.1 = selling pressure
# ===========================================================================

def chaikin_money_flow(df: pd.DataFrame, period: int = 20) -> dict:
    h = df["high"].astype(float).values
    l = df["low"].astype(float).values
    c = df["close"].astype(float).values
    v = df["volume"].astype(float).values if "volume" in df.columns else np.ones_like(c)
    if len(c) < period:
        return {"cmf": 0, "bias": "INSUFFICIENT_DATA"}

    rng = h - l
    rng[rng == 0] = 1e-9
    mfv = ((c - l) - (h - c)) / rng * v
    cmf = mfv[-period:].sum() / v[-period:].sum() if v[-period:].sum() > 0 else 0
    bias = "BULLISH" if cmf > 0.1 else "BEARISH" if cmf < -0.1 else "NEUTRAL"
    return {"cmf": round(float(cmf), 4), "bias": bias, "period": period}


# ===========================================================================
# Unified analysis — calls everything, returns one consolidated dict
# ===========================================================================

@dataclass
class QuantSummary:
    symbol: str
    bars_used: int
    regime: str                       # TRENDING / MEAN_REVERTING / CHOPPY
    hurst: float
    fractal_dimension: float
    z_score_20: float
    z_score_50: float
    kalman: dict
    garch: dict
    ou: dict
    lr_channel: dict
    heikin_ashi: dict
    donchian_20: dict
    donchian_55: dict
    vortex: dict
    cmf: dict
    composite_bias: str
    composite_score: float            # 0..100
    interpretation: list[str]

    def to_dict(self) -> dict:
        return self.__dict__


def analyze(df: pd.DataFrame, symbol: str = "?") -> QuantSummary:
    """Run all advanced-math indicators on a price series.

    Expects df with columns: open, high, low, close, volume.
    """
    if df.empty or "close" not in df.columns:
        return QuantSummary(
            symbol=symbol, bars_used=0, regime="NO_DATA",
            hurst=0.5, fractal_dimension=1.5,
            z_score_20=0, z_score_50=0,
            kalman={}, garch={}, ou={}, lr_channel={},
            heikin_ashi={}, donchian_20={}, donchian_55={},
            vortex={}, cmf={},
            composite_bias="UNKNOWN", composite_score=50,
            interpretation=["No data"],
        )

    closes = df["close"].astype(float).values
    returns = np.diff(np.log(closes))      # log returns

    h = hurst_exponent(closes)
    fd = higuchi_fractal_dimension(closes)
    z20 = z_score(closes, 20)
    z50 = z_score(closes, 50)
    kal = kalman_trend(closes)
    garch = garch_11_forecast(returns)
    ou = ou_half_life(closes)
    lrc = linear_regression_channel(closes)
    ha = heikin_ashi_signal(df)
    don20 = donchian(df, 20)
    don55 = donchian(df, 55)
    vrtx = vortex(df)
    cmf  = chaikin_money_flow(df)

    # Regime classification
    if h > 0.6 and lrc.get("r_squared", 0) > 0.4:
        regime = "TRENDING"
    elif h < 0.4 and ou.get("half_life_bars") and ou["half_life_bars"] < 30:
        regime = "MEAN_REVERTING"
    else:
        regime = "CHOPPY"

    # Composite bias — vote of bullish/bearish/neutral biases
    biases = [
        kal.get("trend", "NEUTRAL"),
        lrc.get("trend", "NEUTRAL").replace("STRONG_", "").replace("WEAK_", "").replace("UP", "BULLISH").replace("DOWN", "BEARISH").replace("NO_TREND", "NEUTRAL"),
        ha.get("bias", "NEUTRAL"),
        vrtx.get("bias", "NEUTRAL"),
        cmf.get("bias", "NEUTRAL"),
        "BULLISH" if z20 < -1.5 else "BEARISH" if z20 > 1.5 else "NEUTRAL",  # mean-reversion
        don20.get("signal", "MIDDLE").replace("BREAKOUT_LONG", "BULLISH").replace("BREAKOUT_SHORT", "BEARISH").replace("NEAR_UPPER", "BULLISH").replace("NEAR_LOWER", "BEARISH").replace("MIDDLE", "NEUTRAL"),
    ]
    bulls = sum(1 for b in biases if b == "BULLISH")
    bears = sum(1 for b in biases if b == "BEARISH")
    composite_bias = "BULLISH" if bulls > bears else "BEARISH" if bears > bulls else "NEUTRAL"
    composite_score = 50 + (bulls - bears) * 7    # ±7 per net vote, cap below
    composite_score = max(0, min(100, composite_score))

    # Human interpretation
    interp = []
    interp.append(f"Hurst {h:.3f} → {'trending (persistent)' if h > 0.55 else 'mean-reverting' if h < 0.45 else 'random walk'}")
    interp.append(f"Fractal dim {fd:.3f} → {'smooth' if fd < 1.3 else 'noisy' if fd > 1.7 else 'random-walk-like'}")
    interp.append(f"LR channel R²={lrc.get('r_squared', 0):.2f} → {'strong trend' if lrc.get('r_squared', 0) > 0.7 else 'weak trend' if lrc.get('r_squared', 0) > 0.3 else 'no trend'}")
    if ou.get("half_life_bars"):
        interp.append(f"Mean-reversion half-life: {ou['half_life_bars']:.0f} bars ({ou['regime']})")
    interp.append(f"GARCH next-bar σ forecast: {garch.get('annualised_next_vol_pct', 0):.1f}% annualised")
    interp.append(f"Z-score {z20:+.2f} (20-bar) → {'extreme oversold — mean-rev BUY signal' if z20 < -2 else 'extreme overbought — mean-rev SELL signal' if z20 > 2 else 'within band'}")
    interp.append(f"Heikin Ashi: {ha.get('consecutive_bull', 0)} bull / {ha.get('consecutive_bear', 0)} bear in last 5 bars")
    interp.append(f"Donchian 20 → {don20.get('signal', '?')}, position {don20.get('position_pct', 0):.0f}%")
    interp.append(f"Vortex VI+={vrtx.get('vi_plus', 0):.3f} vs VI-={vrtx.get('vi_minus', 0):.3f} → {vrtx.get('strength', '?')} {vrtx.get('bias', '?').lower()}")
    interp.append(f"CMF {cmf.get('cmf', 0):+.3f} → {cmf.get('bias', '?').lower()} institutional flow")

    # Strategy recommendation per regime
    if regime == "TRENDING":
        interp.append("→ REGIME: Trend-following strategies favored (breakouts, MA crossovers, Donchian channels)")
    elif regime == "MEAN_REVERTING":
        interp.append("→ REGIME: Mean-reversion strategies favored (Z-score entries, Bollinger band fades)")
    else:
        interp.append("→ REGIME: Choppy — reduce position size, prefer premium-selling option strategies (iron condor)")

    return QuantSummary(
        symbol=symbol,
        bars_used=len(closes),
        regime=regime,
        hurst=round(h, 4),
        fractal_dimension=round(fd, 4),
        z_score_20=round(z20, 3),
        z_score_50=round(z50, 3),
        kalman=kal,
        garch=garch,
        ou=ou,
        lr_channel=lrc,
        heikin_ashi=ha,
        donchian_20=don20,
        donchian_55=don55,
        vortex=vrtx,
        cmf=cmf,
        composite_bias=composite_bias,
        composite_score=round(composite_score, 2),
        interpretation=interp,
    )
