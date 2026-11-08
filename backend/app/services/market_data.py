"""Market-data service.

Returns OHLCV dataframes. In LIVE_ONLY mode raises on any failure rather
than returning synthetic — see config.live_only.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import pandas as pd
from loguru import logger

from app.brokers.angelone import broker_instance
from app.config import settings
from app.engines.technical import synthetic_ohlcv
from app.services import instruments


class LiveDataUnavailable(Exception):
    """Raised in LIVE_ONLY mode when real candles can't be fetched."""


# ============================================================================
# In-memory request cache + per-symbol throttle
# Angel One rate-limits at roughly ~10 historical-candle calls/sec across the
# session. When 6 concurrent workers hit it on backfill + a frontend symbol
# page does its own polling, we exceed limits and get "Access denied" errors.
# Strategy:
#   • Cache successful results for 60 seconds in memory (fresh requests for
#     the same symbol/interval get the cached df, not a new Angel One call)
#   • Throttle to max 1 fetch per symbol per 5 seconds
#   • On rate-limit error, return the LAST KNOWN cached result if available
#     (stale > empty), and log a clear warning
# ============================================================================
import threading, time as _time

_request_cache: dict[tuple, tuple[float, "pd.DataFrame"]] = {}
_last_fetch_at: dict[tuple, float] = {}
_cache_lock = threading.Lock()
_REQUEST_CACHE_TTL_SEC = 60
_PER_SYMBOL_THROTTLE_SEC = 5


def _cache_key(symbol: str, exchange: str, interval: str) -> tuple:
    return (symbol.upper(), exchange.upper(), interval)


def _read_request_cache(key, max_age_sec: int = _REQUEST_CACHE_TTL_SEC):
    with _cache_lock:
        entry = _request_cache.get(key)
        if entry is None:
            return None
        ts, df = entry
        if _time.time() - ts > max_age_sec:
            return None
        return df


def _write_request_cache(key, df):
    with _cache_lock:
        _request_cache[key] = (_time.time(), df)
        # Cap cache size
        if len(_request_cache) > 500:
            oldest = sorted(_request_cache.items(), key=lambda kv: kv[1][0])[:50]
            for k, _ in oldest:
                _request_cache.pop(k, None)


def _read_stale_cache(key):
    """Return the cached df regardless of age — used when rate-limit forces
    us to return SOMETHING rather than 503."""
    with _cache_lock:
        entry = _request_cache.get(key)
        return entry[1] if entry else None


def get_ohlcv(symbol: str, exchange: str = "NSE", interval: str = "ONE_DAY",
              periods: int = 250, symbol_token: str | None = None,
              use_cache: bool = True) -> pd.DataFrame:
    """Return OHLCV dataframe with columns: open, high, low, close, volume.

    Read order:
      1. In-memory request cache (60-sec freshness window)
      2. Local ohlcv_bars DB cache (long-term, hours)
      3. Angel One historical API (if broker authenticated AND not throttled)
      4. Stale in-memory cache (if rate-limited)
      5. Raise LiveDataUnavailable (LIVE_ONLY=true) OR synthetic fallback (paper)
    """
    live_only = settings.live_only
    key = _cache_key(symbol, exchange, interval)

    # ---- 1. In-memory short-term cache (handles request bursts) ----
    if use_cache:
        fresh = _read_request_cache(key)
        if fresh is not None and len(fresh) >= min(periods, 30):
            return fresh.tail(periods)

    # ---- 2. Long-term DB cache from the backfill table ----
    if use_cache:
        try:
            from app.services.backfill import read_cached
            interval_short = {"ONE_DAY": "1d", "ONE_HOUR": "1h",
                              "FIFTEEN_MINUTE": "15m", "FIVE_MINUTE": "5m"}.get(interval, interval)
            cached = read_cached(symbol, interval=interval_short, periods=periods)
            if cached is not None and len(cached) >= min(periods, 30):
                _write_request_cache(key, cached)
                return cached
        except Exception as e:
            logger.debug("cache read failed for {}: {}", symbol, e)

    if not broker_instance.is_authenticated():
        if live_only:
            raise LiveDataUnavailable(
                f"LIVE_ONLY=true and broker not authenticated. "
                f"Fix Angel One login at /settings or check backend startup log."
            )
        return synthetic_ohlcv(symbol, periods=periods)

    token = symbol_token or instruments.token_for(symbol, exchange)
    if not token:
        if live_only:
            raise LiveDataUnavailable(
                f"No instrument token for {exchange}/{symbol} in scrip master. "
                f"Try POST /api/market/instruments/refresh to redownload it."
            )
        return synthetic_ohlcv(symbol, periods=periods)

    # ---- 3. Per-symbol throttle ----
    now_ts = _time.time()
    with _cache_lock:
        last_at = _last_fetch_at.get(key, 0)
        elapsed = now_ts - last_at
    if elapsed < _PER_SYMBOL_THROTTLE_SEC:
        # Too soon since last fetch — try stale cache instead of hitting Angel One
        stale = _read_stale_cache(key)
        if stale is not None:
            logger.debug("Throttle hit for {} ({}s elapsed) — serving stale cache",
                          symbol, round(elapsed, 1))
            return stale.tail(periods)
        # No stale cache to serve, brief sleep to space the request
        _time.sleep(max(0.1, _PER_SYMBOL_THROTTLE_SEC - elapsed))

    # ---- 4. Live fetch — with bounded retry on TRANSIENT errors only ----
    #
    # Transient = network blip, generic 5xx, timeout. These benefit from
    # a quick exponential backoff retry.
    #
    # NOT retried (would be counterproductive):
    #   • Rate-limit errors — retrying just makes the rate-limit worse.
    #     Serve stale cache or raise instead.
    #   • Auth errors — won't fix themselves.
    #   • "No data" empty responses — handled separately below.
    to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=periods + 30)
    data = None
    last_err: Exception | None = None
    TRANSIENT_MARKERS = (
        "connection reset", "timed out", "timeout", "temporarily unavailable",
        "bad gateway", "502", "503", "504", "remote disconnected",
        "max retries exceeded",
    )
    RATE_LIMIT_MARKERS = (
        "access denied", "exceeding access rate", "too many requests", "429",
    )
    AUTH_MARKERS = (
        "unauthorized", "401", "invalid session", "session expired",
    )

    for attempt in range(3):    # at most 3 tries → 0s, 0.5s, 1.5s
        try:
            data = broker_instance.candles(
                exchange=exchange, symbol_token=token, interval=interval,
                fromdate=from_dt.strftime("%Y-%m-%d %H:%M"),
                todate=to_dt.strftime("%Y-%m-%d %H:%M"),
            )
            with _cache_lock:
                _last_fetch_at[key] = _time.time()
            last_err = None
            break    # success
        except Exception as e:
            last_err = e
            err_msg = str(e).lower()
            is_rate_limit = any(m in err_msg for m in RATE_LIMIT_MARKERS)
            is_auth      = any(m in err_msg for m in AUTH_MARKERS)
            is_transient = any(m in err_msg for m in TRANSIENT_MARKERS)
            if is_rate_limit or is_auth:
                break    # don't retry — would make it worse / never recover
            if not is_transient or attempt == 2:
                break    # exhausted retries OR non-transient unknown error
            # Exponential backoff: 0.5s, 1.5s
            sleep_for = 0.5 * (3 ** attempt)
            logger.info("Transient fetch error on {} (attempt {}/3): {} — retry in {:.1f}s",
                         symbol, attempt + 1, e, sleep_for)
            _time.sleep(sleep_for)

    if last_err is not None:
        e = last_err
        err_msg = str(e).lower()
        is_rate_limit = any(m in err_msg for m in RATE_LIMIT_MARKERS)
        if is_rate_limit:
            stale = _read_stale_cache(key)
            if stale is not None:
                logger.warning("Rate-limited fetching {} — serving stale cache (age {}s)",
                                symbol, round(_time.time() - _request_cache[key][0], 1))
                return stale.tail(periods)
            if live_only:
                raise LiveDataUnavailable(
                    f"Angel One rate-limited on {symbol} AND no cache available. "
                    f"Run POST /api/backfill/run for this symbol, or wait 60s and retry."
                )
        # Transient + retries exhausted, or non-transient (auth, etc.) — try stale
        # as a last-resort before failing or going synthetic.
        stale = _read_stale_cache(key)
        if stale is not None:
            logger.warning("Live fetch failed for {} after retries — serving stale cache: {}",
                            symbol, e)
            return stale.tail(periods)
        if live_only:
            raise LiveDataUnavailable(
                f"Angel One candle fetch failed for {symbol}: {e}"
            )
        logger.warning("Live candles failed for {} ({}): {} — synthetic fallback",
                        symbol, exchange, e)
        return synthetic_ohlcv(symbol, periods=periods)

    if not data:
        # Try stale cache before failing
        stale = _read_stale_cache(key)
        if stale is not None:
            return stale.tail(periods)
        if live_only:
            raise LiveDataUnavailable(
                f"Angel One returned no candles for {symbol}/{exchange}/{interval}. "
                f"Market may be closed or token mismatched."
            )
        return synthetic_ohlcv(symbol, periods=periods)

    df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp")
    result = df.tail(periods)
    _write_request_cache(key, result)
    return result


# ---------------------------------------------------------------------------
# Live option chain fetcher (Angel One optionGreek endpoint)
# ---------------------------------------------------------------------------

def get_option_chain(symbol: str, expiry, only_around_atm: int = 11) -> list[dict]:
    """Return a list of chain rows for one underlying + expiry, in the shape
    the rest of the app expects:
        [{strike, ce_oi, pe_oi, ce_iv, pe_iv, ce_ltp, pe_ltp,
          ce_delta, pe_delta, ce_gamma, pe_gamma,
          ce_theta, pe_theta, ce_vega, pe_vega}, ...]

    expiry: date object or "DDMMMYY" string.
    only_around_atm: keep this many strikes around the ATM (centred) to keep
    the payload reasonable.

    Returns [] if the broker isn't authenticated or the call fails.
    Raises LiveDataUnavailable in LIVE_ONLY mode if the call fails.
    """
    if not broker_instance.is_authenticated():
        if settings.live_only:
            raise LiveDataUnavailable("Broker not authenticated for option chain")
        return []

    # Normalize expiry to Angel One's "DDMMMYY" format
    from datetime import date as _date
    if isinstance(expiry, _date):
        expiry_str = expiry.strftime("%d%b%y").upper()
    else:
        expiry_str = str(expiry).upper()

    try:
        rows = broker_instance.option_greeks(name=symbol, expiry=expiry_str)
    except Exception as e:
        if settings.live_only:
            raise LiveDataUnavailable(f"option_greeks failed: {e}")
        logger.warning("option_greeks live fetch failed: {}", e)
        return []

    if not rows:
        return []

    # Group rows by strike — Angel One returns one row per (strike, optionType)
    by_strike: dict[float, dict] = {}
    for r in rows:
        try:
            strike = float(r.get("strikePrice", 0) or 0)
        except Exception:
            continue
        if strike <= 0:
            continue
        opt_type = (r.get("optionType") or "").upper()
        d = by_strike.setdefault(strike, {"strike": strike})
        prefix = "ce_" if opt_type == "CE" else "pe_" if opt_type == "PE" else None
        if prefix is None:
            continue
        # Angel One's keys vary slightly across builds — accept multiple spellings.
        d[f"{prefix}oi"]    = _as_float(r.get("opnInterest") or r.get("openInterest") or 0)
        d[f"{prefix}iv"]    = _as_float(r.get("impliedVolatility") or 0)
        d[f"{prefix}ltp"]   = _as_float(r.get("ltp") or 0)
        d[f"{prefix}delta"] = _as_float(r.get("delta") or 0)
        d[f"{prefix}gamma"] = _as_float(r.get("gamma") or 0)
        d[f"{prefix}theta"] = _as_float(r.get("theta") or 0)
        d[f"{prefix}vega"]  = _as_float(r.get("vega") or 0)
        d[f"{prefix}volume"]= _as_float(r.get("tradeVolume") or 0)

    chain = list(by_strike.values())
    chain.sort(key=lambda c: c["strike"])

    # Trim to `only_around_atm` strikes around the ATM
    if chain and only_around_atm > 0:
        ce_ltps = [c.get("ce_ltp", 0) for c in chain]
        pe_ltps = [c.get("pe_ltp", 0) for c in chain]
        # ATM proxy: strike where CE LTP ≈ PE LTP (smallest abs difference)
        try:
            diffs = [(i, abs(ce_ltps[i] - pe_ltps[i])) for i in range(len(chain))]
            atm_idx = min(diffs, key=lambda x: x[1])[0]
        except Exception:
            atm_idx = len(chain) // 2
        lo = max(0, atm_idx - only_around_atm // 2)
        hi = min(len(chain), lo + only_around_atm)
        chain = chain[lo:hi]

    return chain


def _as_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0
