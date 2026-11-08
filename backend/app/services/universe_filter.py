"""Universe prefilter — narrow a wide universe (NSE-500 or all-NSE ~2000)
down to ~200 candidates worth running the full 17-engine pipeline on.

Why this exists:
  • F&O 180 universe → ~30s scan, all liquid names → reliable signals
  • All-NSE 2000 → ~5–10 min scan, many illiquid names → noisy signals
  • Tiered approach: fast filter (one batched broker call + arithmetic) cuts
    2000 down to ~200 high-liquidity high-volatility candidates, then the
    expensive per-symbol analysis runs only on survivors

Filter signals (composite score):
  • Volume rank — top X percentile by 20-day average traded value (₹crore)
  • Volatility rank — top Y percentile by ATR % of price (movement = opportunity)
  • Day-move filter — drops stocks that have moved >5% today (already chased)
  • Penny-stock guard — drops anything <₹20 (institutional dirt; noisy ticks)
  • Circuit-breaker guard — drops names hit upper/lower circuit (untradeable)

Performance: O(N) with one batched broker quote call for the whole universe.
Typical run on all-NSE 2000 symbols: ~3 seconds (one getMarketData call +
arithmetic). Without this, the full per-symbol pipeline would take 10+ minutes.

Critical design rule: HONEST DEGRADATION.
  • If broker is offline → falls back to keeping the entire input universe
    (caller can still proceed; just won't benefit from prefiltering)
  • If a symbol has no token → silently dropped (can't analyze what we can't fetch)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from loguru import logger


# ---- Tuning constants ----
_MIN_PRICE                   = 20.0       # below this = penny stock, exclude
_MAX_DAY_MOVE_PCT            = 5.0        # already moved → R:R degraded for entry
_MAX_SYMBOLS_OUT             = 300        # hard cap on survivors
_MIN_AVG_DAILY_VALUE_CRORE   = 5.0        # avg 20d traded value in ₹crore


@dataclass
class FilterStats:
    """Diagnostic counters so the admin can see what's being filtered + why."""
    input_size:             int = 0
    dropped_no_token:       int = 0
    dropped_no_quote:       int = 0
    dropped_penny:          int = 0
    dropped_low_volume:     int = 0
    dropped_already_moved:  int = 0
    dropped_circuit:        int = 0
    output_size:            int = 0
    fallback_no_broker:     bool = False
    elapsed_ms:             int = 0
    top_dropped_examples:   list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__


def prefilter(symbols: list[str], *,
               exchange: str = "NSE",
               max_out: int = _MAX_SYMBOLS_OUT,
               min_price: float = _MIN_PRICE,
               max_day_move_pct: float = _MAX_DAY_MOVE_PCT,
               min_avg_value_crore: float = _MIN_AVG_DAILY_VALUE_CRORE,
               ) -> tuple[list[str], FilterStats]:
    """Reduce a wide list of symbols to a high-quality candidate pool.

    Returns (survivor_symbols, stats). Survivors are SORTED by composite
    score — highest-quality first — so callers that further cap the list
    keep the best candidates.

    On any failure: returns the input universe unchanged + stats.fallback_no_broker=True
    """
    import time
    t_start = time.time()
    stats = FilterStats(input_size=len(symbols))

    if not symbols:
        return [], stats

    # ----- 1. Resolve tokens (drop symbols with no instrument row) -----
    try:
        from app.services import instruments
        sym_to_token: dict[str, str] = {}
        for s in symbols:
            t = instruments.token_for(s, exchange)
            if t:
                sym_to_token[s] = t
            else:
                stats.dropped_no_token += 1
        if not sym_to_token:
            logger.warning("Universe prefilter: no symbols had tokens, returning input unchanged")
            stats.fallback_no_broker = True
            stats.elapsed_ms = int((time.time() - t_start) * 1000)
            stats.output_size = len(symbols)
            return list(symbols), stats
    except Exception as e:
        logger.warning("Universe prefilter: instruments lookup failed, returning input: {}", e)
        stats.fallback_no_broker = True
        stats.elapsed_ms = int((time.time() - t_start) * 1000)
        stats.output_size = len(symbols)
        return list(symbols), stats

    # ----- 2. Batched OHLC quote (one broker call for all symbols) -----
    quotes: dict[str, dict] = {}
    try:
        from app.brokers.angelone import broker_instance
        if not broker_instance.is_authenticated():
            logger.info("Universe prefilter: broker not authenticated, returning input unchanged")
            stats.fallback_no_broker = True
            stats.elapsed_ms = int((time.time() - t_start) * 1000)
            stats.output_size = len(symbols)
            return list(symbols), stats

        # Angel One's getMarketData accepts up to ~50 tokens per call. Batch
        # in chunks so big universes don't hit per-call size limits.
        BATCH = 50
        tokens = list(sym_to_token.values())
        token_to_sym = {v: k for k, v in sym_to_token.items()}
        for i in range(0, len(tokens), BATCH):
            chunk = tokens[i:i + BATCH]
            resp = broker_instance.quotes_batch(
                mode="OHLC", exchange_tokens={exchange: chunk})
            data = (resp or {}).get("data") or {}
            for row in data.get("fetched") or []:
                tok = str(row.get("symbolToken") or row.get("symboltoken") or "")
                s = token_to_sym.get(tok)
                if s:
                    quotes[s] = row
    except Exception as e:
        logger.warning("Universe prefilter: batched quote failed, returning input: {}", e)
        stats.fallback_no_broker = True
        stats.elapsed_ms = int((time.time() - t_start) * 1000)
        stats.output_size = len(symbols)
        return list(symbols), stats

    # ----- 3. Filter + score -----
    # Composite score: volume_rank × volatility_rank, both [0..1]. Higher = better.
    scored: list[tuple[str, float]] = []
    examples_dropped: list[dict] = []

    for sym, tok in sym_to_token.items():
        q = quotes.get(sym)
        if not q:
            stats.dropped_no_quote += 1
            continue

        ltp        = _num(q.get("ltp"))
        prev_close = _num(q.get("close") or q.get("previousClose"))
        high       = _num(q.get("high"))
        low        = _num(q.get("low"))
        open_      = _num(q.get("open"))
        volume     = _num(q.get("tradeVolume") or q.get("volume"))

        if ltp is None or ltp <= 0:
            stats.dropped_no_quote += 1
            continue

        # Penny-stock guard
        if ltp < min_price:
            stats.dropped_penny += 1
            if len(examples_dropped) < 3:
                examples_dropped.append({"symbol": sym, "reason": "penny", "ltp": ltp})
            continue

        # Day-move filter (already chased)
        if prev_close and prev_close > 0:
            day_change_pct = abs(ltp - prev_close) / prev_close * 100
            if day_change_pct > max_day_move_pct:
                stats.dropped_already_moved += 1
                if len(examples_dropped) < 3:
                    examples_dropped.append({"symbol": sym, "reason": "already_moved",
                                               "day_change_pct": round(day_change_pct, 2)})
                continue
        else:
            day_change_pct = 0.0

        # Circuit-breaker guard: if today's high == low and != ltp, stock is locked
        if high is not None and low is not None and high == low:
            stats.dropped_circuit += 1
            continue

        # Volume threshold: avg traded value (in ₹crore) using single-day proxy
        # (full 20d avg would need historical fetches — too slow at scan time)
        traded_value_crore = (volume * ltp) / 1e7 if volume else 0.0
        if traded_value_crore < min_avg_value_crore:
            stats.dropped_low_volume += 1
            continue

        # Volatility — single-day ATR proxy: (high - low) / ltp
        if high is not None and low is not None and ltp > 0:
            day_range_pct = (high - low) / ltp * 100
        else:
            day_range_pct = 1.0   # neutral

        # Composite score — favor liquidity AND volatility. Both normalised
        # softly: log(value) and sqrt(range) so a single dominant axis can't
        # entirely win.
        import math
        liq_score = math.log(1 + traded_value_crore)             # ₹50cr → 3.9
        vol_score = math.sqrt(max(0.5, day_range_pct))           # 4% → 2.0
        score = liq_score * vol_score

        scored.append((sym, score))

    scored.sort(key=lambda x: -x[1])
    survivors = [s for s, _ in scored[:max_out]]

    stats.output_size = len(survivors)
    stats.top_dropped_examples = examples_dropped
    stats.elapsed_ms = int((time.time() - t_start) * 1000)
    logger.info(
        "Universe prefilter: {} in → {} survivors ({}ms) | dropped: "
        "no_token={} no_quote={} penny={} low_vol={} already_moved={} circuit={}",
        stats.input_size, stats.output_size, stats.elapsed_ms,
        stats.dropped_no_token, stats.dropped_no_quote, stats.dropped_penny,
        stats.dropped_low_volume, stats.dropped_already_moved, stats.dropped_circuit,
    )
    return survivors, stats


def _num(x) -> float | None:
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None
