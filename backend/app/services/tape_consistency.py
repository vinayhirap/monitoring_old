"""Tape-consistency check — reconcile recommendation direction with TODAY's
live price action and the current planetary hora.

The pipeline that generates picks (technical/SMC/Gann/Fibonacci/astro) runs
on daily bars and an astro snapshot. By the time the user sees the
recommendation, the intraday tape may have:
  • Already moved opposite to the rated direction (BULLISH pick down -1%)
  • Entered a hora whose bias contradicts the trade

Bug surfaced this: CIPLA/AXISBANK/LT all flagged BULLISH ACCUMULATE while
AXISBANK was down -0.98% on the day AND Mars hora (bearish) was active.
Showing those as "ACCUMULATE NOW" is misleading.

This service:
  1. Fetches today's LTP + day-change % for every pick (one batched broker
     call — efficient even for 50 picks)
  2. Compares pick direction vs day_change_pct → tape_status
  3. Compares pick direction vs current hora bias → hora_conflict
  4. Computes a `live_verdict` that DOWNGRADES the original verdict when
     the live tape disagrees, so the UI can show "WAIT — today's tape
     contradicts" instead of a confident-looking BUY

Critical design rule: NEVER UPGRADES a recommendation. Only downgrades.
A BULLISH pick can become WATCH/WAIT, but a WAIT pick stays WAIT — the
live tape can't manufacture confidence the pipeline didn't already have.
"""
from __future__ import annotations

from typing import Literal

from loguru import logger


# ----------------------------------------------------------------------------
# Thresholds — tunable; sensible defaults that minimise false positives
# ----------------------------------------------------------------------------

# Day-change % thresholds. A BULLISH pick is CONTRADICTED if the stock is
# down more than this; WEAK_ALIGNMENT if flat-to-slightly-down; ALIGNED otherwise.
_HARD_CONTRADICTION_PCT = 0.5    # |day_change| > 0.5% in opposite direction → CONTRADICTED
_WEAK_ALIGNMENT_PCT    = 0.1     # |day_change| < 0.1% in same direction    → WEAK
_BIG_MOVE_PCT          = 2.0     # |day_change| > 2% → "already moved" warning even if aligned

# Hora weight at/above which a contradicting hora forces a downgrade
_HORA_WEIGHT_FLOOR     = 0.6


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------

def assess_single(*,
                   direction: str,                    # BULLISH / BEARISH
                   confidence: float | None,          # 0..100
                   day_change_pct: float | None,
                   hora: dict | None) -> dict:
    """Per-pick tape-consistency assessment.

    Returns dict with:
      tape_status         : "ALIGNED" / "WEAK_ALIGNMENT" / "CONTRADICTED" / "STALE" / "OVEREXTENDED"
      hora_conflict       : True if current hora bias opposes the trade direction
                            (with weight >= _HORA_WEIGHT_FLOOR)
      live_verdict        : "PROCEED" / "WAIT" / "AVOID_NOW"
      live_label          : short user-facing label
      reasons             : list[str] — why the verdict was downgraded
    """
    reasons: list[str] = []
    tape_status: str = "STALE"
    hora_conflict = False

    direction_up = direction == "BULLISH"

    # ----- 1. Tape (live day-change %) check -----
    if day_change_pct is None:
        tape_status = "STALE"
        reasons.append("Live quote unavailable — verify on broker terminal before entry")
    else:
        # For BULLISH picks: positive day_change is aligned, negative is bad
        # For BEARISH picks: negative day_change is aligned, positive is bad
        signed_change = day_change_pct if direction_up else -day_change_pct
        if signed_change <= -_HARD_CONTRADICTION_PCT:
            tape_status = "CONTRADICTED"
            reasons.append(
                f"Stock is {abs(day_change_pct):.2f}% "
                f"{'down' if day_change_pct < 0 else 'up'} today — opposite to {direction} direction"
            )
        elif signed_change < _WEAK_ALIGNMENT_PCT:
            tape_status = "WEAK_ALIGNMENT"
            reasons.append(
                f"Tape is flat ({day_change_pct:+.2f}%) — direction not yet confirmed by price action"
            )
        elif abs(day_change_pct) >= _BIG_MOVE_PCT:
            tape_status = "OVEREXTENDED"
            reasons.append(
                f"Stock already moved {day_change_pct:+.2f}% today — entry chases the move; "
                f"R:R degrades vs the original entry level"
            )
        else:
            tape_status = "ALIGNED"

    # ----- 2. Current-hora conflict check -----
    if hora:
        hora_bias = (hora.get("bias") or "").lower()       # bullish / bearish / neutral
        hora_weight = float(hora.get("weight") or 0)
        if hora_weight >= _HORA_WEIGHT_FLOOR:
            if direction_up and hora_bias == "bearish":
                hora_conflict = True
                reasons.append(
                    f"Current hora is {hora.get('ruler', '?')} (BEARISH, weight {hora_weight}) "
                    f"— unfavorable for new longs. Consider waiting for next "
                    f"{hora.get('next_ruler', 'bullish')} window."
                )
            elif (not direction_up) and hora_bias == "bullish":
                hora_conflict = True
                reasons.append(
                    f"Current hora is {hora.get('ruler', '?')} (BULLISH, weight {hora_weight}) "
                    f"— unfavorable for new shorts. Consider waiting for next bearish window."
                )

    # ----- 3. Compute live verdict — never UP-rate, only down-rate -----
    if tape_status == "CONTRADICTED":
        live_verdict = "AVOID_NOW"
        live_label   = "Tape against — wait"
    elif tape_status == "OVEREXTENDED":
        live_verdict = "WAIT"
        live_label   = "Chased — wait for pullback"
    elif hora_conflict:
        live_verdict = "WAIT"
        live_label   = "Wrong hora — wait for window"
    elif tape_status == "WEAK_ALIGNMENT":
        live_verdict = "WAIT"
        live_label   = "Tape flat — wait for confirmation"
    elif tape_status == "ALIGNED":
        live_verdict = "PROCEED"
        live_label   = "Tape confirms"
    else:                                                  # STALE
        live_verdict = "PROCEED"        # don't block on stale quotes
        live_label   = "Live quote unavailable"

    return {
        "tape_status":      tape_status,
        "hora_conflict":    hora_conflict,
        "live_verdict":     live_verdict,
        "live_label":       live_label,
        "day_change_pct":   round(day_change_pct, 2) if day_change_pct is not None else None,
        "reasons":          reasons,
    }


def enrich_picks(picks: list[dict], *,
                  hora: dict | None = None,
                  exchange: str = "NSE") -> list[dict]:
    """Enrich each pick dict with live LTP + day_change_pct + tape consistency
    fields. The pick dicts are returned in a NEW list — input is not mutated.

    Args:
      picks    : list of dicts each with at least {symbol, direction, confidence}
      hora     : current hora dict from hora.current_hora().to_dict()
      exchange : usually "NSE"

    Best-effort: batches one broker call for all symbols. On any failure
    (broker not authenticated, network error, missing tokens) returns the
    picks with `tape_status="STALE"` and `day_change_pct=None` — never
    raises, so a bad live quote never breaks the recommendations endpoint.
    """
    if not picks:
        return []

    # Batch-fetch quotes via the operator broker (uses one HTTP call regardless
    # of pick count). If it fails, we proceed with day_change_pct=None.
    quotes_by_symbol = _fetch_quotes_batched(picks, exchange)

    enriched = []
    for p in picks:
        sym = (p.get("symbol") or "").upper()
        quote = quotes_by_symbol.get(sym, {})
        ltp = quote.get("ltp")
        day_change_pct = quote.get("day_change_pct")
        assess = assess_single(
            direction=p.get("direction") or "BULLISH",
            confidence=p.get("confidence"),
            day_change_pct=day_change_pct,
            hora=hora,
        )
        out = dict(p)               # shallow copy — don't mutate input
        out.update({
            "live_ltp":       ltp,
            "day_change_pct": assess["day_change_pct"],
            "tape_status":    assess["tape_status"],
            "hora_conflict":  assess["hora_conflict"],
            "live_verdict":   assess["live_verdict"],
            "live_label":     assess["live_label"],
            "live_reasons":   assess["reasons"],
        })
        enriched.append(out)
    return enriched


# ----------------------------------------------------------------------------
# Quote fetching — operator broker, batched
# ----------------------------------------------------------------------------

def _fetch_quotes_batched(picks: list[dict], exchange: str) -> dict[str, dict]:
    """Returns {symbol: {ltp, day_change_pct}} for as many symbols as we can
    resolve. Symbols whose token can't be found are silently skipped.
    """
    out: dict[str, dict] = {}
    try:
        from app.brokers.angelone import broker_instance
        from app.services import instruments

        if not broker_instance.is_authenticated():
            return out

        # Resolve symbol → token
        tokens: list[str] = []
        token_to_symbol: dict[str, str] = {}
        for p in picks:
            sym = (p.get("symbol") or "").upper()
            if not sym:
                continue
            t = instruments.token_for(sym, exchange)
            if t:
                tokens.append(t)
                token_to_symbol[t] = sym

        if not tokens:
            return out

        # One batched call: mode=OHLC gives LTP + open + high + low + close (prev close)
        resp = broker_instance.quotes_batch(
            mode="OHLC", exchange_tokens={exchange: tokens})
        data = (resp or {}).get("data") or {}
        rows = data.get("fetched") or []
        for row in rows:
            token = str(row.get("symbolToken") or row.get("symboltoken") or "")
            sym = token_to_symbol.get(token)
            if not sym:
                continue
            ltp = _num(row.get("ltp"))
            prev_close = _num(row.get("close") or row.get("previousClose"))
            day_change_pct = None
            if ltp is not None and prev_close and prev_close > 0:
                day_change_pct = (ltp - prev_close) / prev_close * 100
            out[sym] = {"ltp": ltp, "day_change_pct": day_change_pct}
        return out

    except Exception as e:
        logger.debug("tape_consistency batched quote fetch failed: {}", e)
        return out


def _num(x) -> float | None:
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None
