"""Professional backtester.

Replays the pipeline day-by-day against historical OHLCV and computes the
institutional-standard performance metrics:

    Returns           — total, annualised
    Sharpe ratio      — risk-adjusted return (rf = 6.5% INR default)
    Sortino ratio     — downside-only risk-adjusted
    Calmar ratio      — annual return / max drawdown
    Max drawdown      — worst peak-to-trough
    Win rate          — fraction of trades that closed positive
    Profit factor     — gross_profit / gross_loss
    R-multiple dist.  — distribution of trade outcomes in R-units
    Expectancy        — avg R per trade (the only metric that matters long-run)
    Turnover          — # of trades / period
    Avg holding bars  — how long the system stays in trades

The output is the only honest way to know whether the system has edge before
risking real capital. Run on the longest history available (3-5 years ideal).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal
import math

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Output container
# ---------------------------------------------------------------------------

@dataclass
class BacktestResult:
    symbol: str
    start: str
    end: str
    bars_tested: int
    trades: int
    win_rate_pct: float
    profit_factor: float
    expectancy_R: float
    avg_holding_bars: float
    total_return_pct: float
    annualised_return_pct: float
    sharpe: float
    sortino: float
    calmar: float
    max_drawdown_pct: float
    r_multiple_distribution: dict
    equity_curve: list[dict]
    trades_log: list[dict]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

ANNUALISATION = {
    "1d":  252,
    "1h":  252 * 6,
    "15m": 252 * 6 * 4,
    "5m":  252 * 6 * 12,
}


def _sharpe(returns: np.ndarray, rf_annual: float = 0.065,
            periods_per_year: int = 252) -> float:
    if returns.size < 2 or np.std(returns) == 0:
        return 0.0
    rf_per = rf_annual / periods_per_year
    excess = returns - rf_per
    return float(np.mean(excess) / np.std(excess) * math.sqrt(periods_per_year))


def _sortino(returns: np.ndarray, rf_annual: float = 0.065,
              periods_per_year: int = 252) -> float:
    if returns.size < 2:
        return 0.0
    rf_per = rf_annual / periods_per_year
    excess = returns - rf_per
    downside = excess[excess < 0]
    if downside.size == 0 or np.std(downside) == 0:
        return 0.0
    return float(np.mean(excess) / np.std(downside) * math.sqrt(periods_per_year))


def _max_drawdown(equity_curve: np.ndarray) -> float:
    if equity_curve.size == 0:
        return 0.0
    peak = np.maximum.accumulate(equity_curve)
    dd = (equity_curve - peak) / peak
    return float(-dd.min() * 100)


def _profit_factor(pnls: list[float]) -> float:
    gp = sum(p for p in pnls if p > 0)
    gl = -sum(p for p in pnls if p < 0)
    if gl == 0:
        return float("inf") if gp > 0 else 0.0
    return gp / gl


# ---------------------------------------------------------------------------
# Trade simulation
# ---------------------------------------------------------------------------

def _simulate_trades(df: pd.DataFrame, signals: list[dict],
                      atr_stop_mult: float = 1.5,
                      atr_target_mult: float = 2.5,
                      max_holding_bars: int = 20) -> list[dict]:
    """Walk forward through `signals` (list of dicts with bar_idx, direction,
    entry, atr) and simulate each trade against subsequent bars in `df`.

    Returns list of executed trades with pnl_R and pnl_pct.
    """
    trades = []
    for sig in signals:
        i = int(sig["bar_idx"])
        if i + 1 >= len(df):
            continue
        entry = float(sig.get("entry", df["close"].iloc[i]))
        atr = float(sig.get("atr", 0)) or float(df["high"].iloc[i] - df["low"].iloc[i])
        if atr <= 0:
            continue

        direction_long = sig["direction"] == "BULLISH"
        if direction_long:
            sl = entry - atr_stop_mult * atr
            tgt = entry + atr_target_mult * atr
        else:
            sl = entry + atr_stop_mult * atr
            tgt = entry - atr_target_mult * atr
        risk_per_unit = abs(entry - sl)

        # Walk forward
        exit_price = None
        exit_reason = None
        exit_bar = None
        for j in range(i + 1, min(i + 1 + max_holding_bars, len(df))):
            h = float(df["high"].iloc[j])
            l = float(df["low"].iloc[j])
            if direction_long:
                if l <= sl:
                    exit_price = sl; exit_reason = "STOP"; exit_bar = j; break
                if h >= tgt:
                    exit_price = tgt; exit_reason = "TARGET"; exit_bar = j; break
            else:
                if h >= sl:
                    exit_price = sl; exit_reason = "STOP"; exit_bar = j; break
                if l <= tgt:
                    exit_price = tgt; exit_reason = "TARGET"; exit_bar = j; break
        if exit_price is None:
            exit_price = float(df["close"].iloc[min(i + max_holding_bars, len(df) - 1)])
            exit_reason = "TIME"
            exit_bar = min(i + max_holding_bars, len(df) - 1)

        pnl_per_unit = (exit_price - entry) if direction_long else (entry - exit_price)
        pnl_R = pnl_per_unit / risk_per_unit if risk_per_unit > 0 else 0
        pnl_pct = pnl_per_unit / entry * 100 if entry > 0 else 0

        trades.append({
            "entry_bar": i,
            "exit_bar": exit_bar,
            "holding_bars": exit_bar - i,
            "direction": "LONG" if direction_long else "SHORT",
            "entry": round(entry, 2),
            "exit": round(exit_price, 2),
            "sl": round(sl, 2),
            "target": round(tgt, 2),
            "exit_reason": exit_reason,
            "pnl_R": round(pnl_R, 3),
            "pnl_pct": round(pnl_pct, 3),
        })
    return trades


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def backtest(symbol: str, df: pd.DataFrame, signals: list[dict],
              starting_capital: float = 100_000,
              risk_per_trade_pct: float = 1.0,
              timeframe: str = "1d",
              rf_annual: float = 0.065) -> BacktestResult:
    """Run a backtest.

    df       : OHLCV DataFrame with columns [open, high, low, close, volume]
               and a DatetimeIndex (or 'ts' column).
    signals  : list of {bar_idx, direction, entry?, atr?}
    """
    if df.empty or not signals:
        return BacktestResult(
            symbol=symbol, start="", end="", bars_tested=len(df),
            trades=0, win_rate_pct=0, profit_factor=0, expectancy_R=0,
            avg_holding_bars=0, total_return_pct=0, annualised_return_pct=0,
            sharpe=0, sortino=0, calmar=0, max_drawdown_pct=0,
            r_multiple_distribution={}, equity_curve=[], trades_log=[],
            notes=["No bars or no signals — nothing to test"],
        )

    trades = _simulate_trades(df, signals)
    if not trades:
        return BacktestResult(
            symbol=symbol, start=str(df.index[0]), end=str(df.index[-1]),
            bars_tested=len(df), trades=0, win_rate_pct=0, profit_factor=0,
            expectancy_R=0, avg_holding_bars=0, total_return_pct=0,
            annualised_return_pct=0, sharpe=0, sortino=0, calmar=0,
            max_drawdown_pct=0, r_multiple_distribution={},
            equity_curve=[], trades_log=[],
            notes=["No trades executed — signals may have been at end-of-history"],
        )

    pnls_R = [t["pnl_R"] for t in trades]
    pnls_pct = [t["pnl_pct"] for t in trades]
    wins = [p for p in pnls_R if p > 0]
    losses = [p for p in pnls_R if p < 0]
    win_rate = len(wins) / len(trades) * 100
    pf = _profit_factor(pnls_R)
    expectancy_R = float(np.mean(pnls_R)) if pnls_R else 0
    avg_hold = float(np.mean([t["holding_bars"] for t in trades]))

    # Build equity curve: each trade compounds risk_per_trade_pct × pnl_R
    risk_per_trade_inr = starting_capital * risk_per_trade_pct / 100
    equity = [starting_capital]
    for t in trades:
        new_equity = equity[-1] + t["pnl_R"] * risk_per_trade_inr
        equity.append(new_equity)
    equity = np.array(equity)
    total_return = (equity[-1] - starting_capital) / starting_capital * 100

    # Annualise — periods elapsed in years
    bars_elapsed = trades[-1]["exit_bar"] - trades[0]["entry_bar"]
    ppy = ANNUALISATION.get(timeframe, 252)
    years = max(bars_elapsed / ppy, 1 / 252)
    cagr = (((equity[-1] / starting_capital) ** (1 / years)) - 1) * 100 if years > 0 else 0

    # Convert equity to returns for Sharpe/Sortino
    returns = np.diff(equity) / equity[:-1]
    sharpe = _sharpe(returns, rf_annual, ppy)
    sortino = _sortino(returns, rf_annual, ppy)
    mdd = _max_drawdown(equity)
    calmar = cagr / mdd if mdd > 0 else 0

    # R-multiple histogram
    bins = [-3, -2, -1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2, 3, 5]
    hist, edges = np.histogram(pnls_R, bins=bins)
    r_dist = {f"{edges[i]:.1f}_{edges[i+1]:.1f}": int(hist[i]) for i in range(len(hist))}

    # Equity curve for charting (downsample if too long)
    step = max(1, len(equity) // 200)
    curve = [{"trade": i, "equity_inr": round(float(e), 2)} for i, e in enumerate(equity[::step])]

    return BacktestResult(
        symbol=symbol,
        start=str(df.index[0]),
        end=str(df.index[-1]),
        bars_tested=len(df),
        trades=len(trades),
        win_rate_pct=round(win_rate, 2),
        profit_factor=round(pf, 3),
        expectancy_R=round(expectancy_R, 3),
        avg_holding_bars=round(avg_hold, 1),
        total_return_pct=round(total_return, 2),
        annualised_return_pct=round(cagr, 2),
        sharpe=round(sharpe, 3),
        sortino=round(sortino, 3),
        calmar=round(calmar, 3),
        max_drawdown_pct=round(mdd, 2),
        r_multiple_distribution=r_dist,
        equity_curve=curve,
        trades_log=trades[:200],
        notes=[
            f"Risk per trade = {risk_per_trade_pct}% of starting capital",
            f"Stop = 1.5×ATR, Target = 2.5×ATR (R:R 1.67), max hold = 20 bars",
            "Expectancy_R > 0.2 is generally considered viable; > 0.5 is strong",
            "Sharpe > 1.0 is good; > 2.0 is excellent for retail-accessible strategies",
        ],
    )


# ---------------------------------------------------------------------------
# Signal generator wrapper — runs the pipeline at each bar to produce signals
# ---------------------------------------------------------------------------

def generate_signals_from_pipeline(df: pd.DataFrame, symbol: str,
                                    min_confidence: float = 60.0,
                                    lookback_bars: int = 50) -> list[dict]:
    """For each bar in df (starting at lookback_bars), run decision.aggregate
    on the rolling window and emit a signal when confidence crosses threshold.

    Heavy — designed for SWING/POSITIONAL daily backtests; intraday usage
    should subsample.
    """
    from app.engines import decision, technical
    signals = []
    last_signal_idx = -10
    for i in range(lookback_bars, len(df) - 1):
        window = df.iloc[:i + 1]
        try:
            sig = decision.aggregate(symbol=symbol, df=window, horizon="SWING")
        except Exception:
            continue
        # Throttle: at least 3 bars between signals
        if i - last_signal_idx < 3:
            continue
        if sig.get("signal") in ("BUY", "STRONG_BUY") and sig.get("confidence", 0) >= min_confidence:
            atr = sig.get("engines", {}).get("technical", {}).get("details", {}).get("atr14")
            signals.append({
                "bar_idx": i,
                "direction": "BULLISH",
                "entry": float(df["close"].iloc[i]),
                "atr": float(atr or 0),
                "confidence": sig["confidence"],
            })
            last_signal_idx = i
        elif sig.get("signal") in ("SELL", "STRONG_SELL") and sig.get("confidence", 100) <= 100 - min_confidence:
            atr = sig.get("engines", {}).get("technical", {}).get("details", {}).get("atr14")
            signals.append({
                "bar_idx": i,
                "direction": "BEARISH",
                "entry": float(df["close"].iloc[i]),
                "atr": float(atr or 0),
                "confidence": sig["confidence"],
            })
            last_signal_idx = i
    return signals
