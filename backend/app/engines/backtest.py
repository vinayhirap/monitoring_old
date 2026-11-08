"""Walk-forward backtester.

For each historical bar in the lookback window, computes the decision
engine score using ONLY data up to that bar, simulates entries when the
signal qualifies, and tracks exits via stop / target / time-stop.

Reports honest stats:
  • hit_rate (winning trades / total trades)
  • avg_win, avg_loss, profit_factor, expectancy
  • max drawdown
  • per-trade list + equity curve

This is the ONLY honest way to discuss "accuracy" of a multi-engine signal.
Numbers depend heavily on data window, slippage assumptions, and lookback —
the report includes those parameters so results are reproducible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import pandas as pd
import numpy as np

from app.engines import technical, smc


@dataclass
class Trade:
    entry_date: str
    exit_date: str
    direction: str           # LONG / SHORT
    entry: float
    exit: float
    stop: float
    target: float
    bars_held: int
    pnl_pct: float
    outcome: str             # WIN / LOSS / TIMEOUT
    confidence_at_entry: float

    def to_dict(self) -> dict:
        return self.__dict__


@dataclass
class BacktestReport:
    symbol: str
    lookback_bars: int
    warmup_bars: int
    confidence_threshold: float
    atr_sl_mult: float
    atr_target_mult: float
    max_bars_held: int

    trades: list[dict] = field(default_factory=list)

    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    timeouts: int = 0
    hit_rate: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    profit_factor: float = 0.0
    expectancy_pct: float = 0.0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    equity_curve: list[dict] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        return self.__dict__


def _local_score(df: pd.DataFrame) -> tuple[float, str]:
    """Lightweight confluence score for backtests — technical + SMC only.
    Astro/numerology are *current-time* signals and would be the same value
    across all historical bars in a single backtest run, so they're excluded.
    """
    tech = technical.analyze(df)
    smc_res = smc.analyze(df)
    combined = 0.6 * tech.score + 0.4 * smc_res.score
    if combined >= 60:
        sig = "BUY"
    elif combined <= 40:
        sig = "SELL"
    else:
        sig = "NEUTRAL"
    return combined, sig


def run(
    symbol: str,
    df: pd.DataFrame,
    lookback_bars: int = 180,
    warmup_bars: int = 60,
    confidence_threshold: float = 65.0,
    atr_sl_mult: float = 1.5,
    atr_target_mult: float = 3.0,
    max_bars_held: int = 15,
    cooldown_bars: int = 3,
) -> BacktestReport:
    """Walk-forward backtest.

    df must have columns: open, high, low, close, volume (lowercase)
    and at least lookback_bars + warmup_bars rows.
    """
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    n = len(df)
    if n < lookback_bars + warmup_bars:
        return BacktestReport(
            symbol=symbol,
            lookback_bars=lookback_bars,
            warmup_bars=warmup_bars,
            confidence_threshold=confidence_threshold,
            atr_sl_mult=atr_sl_mult,
            atr_target_mult=atr_target_mult,
            max_bars_held=max_bars_held,
            note=f"Insufficient data: have {n}, need {lookback_bars + warmup_bars}",
        )

    start = n - lookback_bars
    trades: list[Trade] = []
    in_position = False
    next_eligible = start
    current_trade: dict | None = None

    for i in range(start, n):
        bar = df.iloc[i]
        date = str(df.index[i].date()) if hasattr(df.index[i], "date") else str(df.index[i])

        # If in a position, check stop/target/timeout
        if in_position and current_trade is not None:
            ct = current_trade
            high, low = float(bar["high"]), float(bar["low"])
            close = float(bar["close"])
            bars_held = i - ct["entry_i"]

            exited = None
            exit_price = None
            outcome = None
            if ct["direction"] == "LONG":
                if low <= ct["stop"]:
                    exit_price, outcome = ct["stop"], "LOSS"
                    exited = True
                elif high >= ct["target"]:
                    exit_price, outcome = ct["target"], "WIN"
                    exited = True
            else:  # SHORT
                if high >= ct["stop"]:
                    exit_price, outcome = ct["stop"], "LOSS"
                    exited = True
                elif low <= ct["target"]:
                    exit_price, outcome = ct["target"], "WIN"
                    exited = True

            if not exited and bars_held >= max_bars_held:
                exit_price = close
                pnl = (close - ct["entry"]) if ct["direction"] == "LONG" else (ct["entry"] - close)
                outcome = "TIMEOUT" if abs(pnl / ct["entry"]) < 0.01 else ("WIN" if pnl > 0 else "LOSS")
                exited = True

            if exited:
                pnl_pct = ((exit_price - ct["entry"]) / ct["entry"] * 100) if ct["direction"] == "LONG" \
                          else ((ct["entry"] - exit_price) / ct["entry"] * 100)
                trades.append(Trade(
                    entry_date=ct["entry_date"], exit_date=date,
                    direction=ct["direction"], entry=ct["entry"], exit=exit_price,
                    stop=ct["stop"], target=ct["target"],
                    bars_held=bars_held, pnl_pct=round(pnl_pct, 3),
                    outcome=outcome, confidence_at_entry=ct["confidence"],
                ))
                in_position = False
                current_trade = None
                next_eligible = i + cooldown_bars

        # Look for new entry
        if not in_position and i >= next_eligible:
            window = df.iloc[:i + 1]
            try:
                conf, sig = _local_score(window)
            except Exception:
                continue
            if conf >= confidence_threshold and sig in ("BUY", "SELL"):
                tech_res = technical.analyze(window)
                atr_val = tech_res.indicators["atr14"]
                if atr_val <= 0:
                    continue
                entry = float(bar["close"])
                if sig == "BUY":
                    stop = entry - atr_sl_mult * atr_val
                    target = entry + atr_target_mult * atr_val
                    direction = "LONG"
                else:
                    stop = entry + atr_sl_mult * atr_val
                    target = entry - atr_target_mult * atr_val
                    direction = "SHORT"
                current_trade = {
                    "entry_i": i, "entry_date": date, "entry": entry,
                    "stop": stop, "target": target, "direction": direction,
                    "confidence": round(conf, 2),
                }
                in_position = True

    # Stats
    report = BacktestReport(
        symbol=symbol,
        lookback_bars=lookback_bars,
        warmup_bars=warmup_bars,
        confidence_threshold=confidence_threshold,
        atr_sl_mult=atr_sl_mult,
        atr_target_mult=atr_target_mult,
        max_bars_held=max_bars_held,
        trades=[t.to_dict() for t in trades],
        total_trades=len(trades),
    )

    if trades:
        wins = [t for t in trades if t.outcome == "WIN"]
        losses = [t for t in trades if t.outcome == "LOSS"]
        timeouts = [t for t in trades if t.outcome == "TIMEOUT"]
        report.wins = len(wins)
        report.losses = len(losses)
        report.timeouts = len(timeouts)
        decisive = len(wins) + len(losses)
        report.hit_rate = round(len(wins) / decisive * 100, 2) if decisive else 0.0
        report.avg_win_pct = round(np.mean([t.pnl_pct for t in wins]), 3) if wins else 0.0
        report.avg_loss_pct = round(np.mean([t.pnl_pct for t in losses]), 3) if losses else 0.0
        gross_win = sum(t.pnl_pct for t in wins)
        gross_loss = abs(sum(t.pnl_pct for t in losses))
        report.profit_factor = round(gross_win / gross_loss, 3) if gross_loss else float("inf")
        report.expectancy_pct = round(np.mean([t.pnl_pct for t in trades]), 3)
        report.total_return_pct = round(sum(t.pnl_pct for t in trades), 3)

        # Equity curve & drawdown
        equity = 100.0
        peak = equity
        max_dd = 0.0
        curve = []
        for t in trades:
            equity *= (1 + t.pnl_pct / 100)
            peak = max(peak, equity)
            dd = (peak - equity) / peak * 100
            max_dd = max(max_dd, dd)
            curve.append({"date": t.exit_date, "equity": round(equity, 3), "drawdown_pct": round(dd, 3)})
        report.equity_curve = curve
        report.max_drawdown_pct = round(max_dd, 3)

    report.note = (
        "Backtest uses technical + SMC only (astro/numerology are realtime layers "
        "and contribute equally across all historical bars in any single run). "
        "Slippage and commissions are not modeled. Hit-rate is computed on decisive "
        "(WIN+LOSS) trades only; TIMEOUTs are excluded from the ratio but counted "
        "in total return."
    )
    return report
