"""Advanced+ analysis endpoints: multi-timeframe + sector heatmap."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import APIRouter, HTTPException, Query
from loguru import logger

from app.engines import mtf, decision
from app.services.market_data import get_ohlcv
from app.services.universe import SECTORS, sector_of

router = APIRouter()


@router.get("/mtf/{symbol}", summary="Multi-timeframe (Daily / Weekly / Monthly) agreement")
def multi_timeframe(symbol: str, periods: int = Query(500, ge=200, le=2000)):
    try:
        df = get_ohlcv(symbol.upper(), periods=periods)
        return {"symbol": symbol.upper(), **mtf.analyze(df)}
    except Exception as e:
        raise HTTPException(500, f"mtf failed: {e}")


# --- Sector heatmap: background compute + cache ----------------------------
import threading
import time

_HEATMAP_TTL_SEC = 15 * 60
_HEATMAP_WAIT_SEC = 20
_hm_lock = threading.Lock()
_hm_state: dict = {"data": None, "at": 0.0, "running": False, "error": None}
_hm_done = threading.Event()


def _has_token(sym: str) -> bool:
    """True if the symbol is in the scrip master (no network call)."""
    try:
        from app.services import instruments
        eq = getattr(instruments, "_equity_lookup", None)
        if not eq or not getattr(instruments, "_loaded", False):
            return True            # master not loaded yet: do not skip anything
        return sym.upper() in eq
    except Exception:
        return True


def _compute_heatmap(parallel: int) -> dict:
    def _score_one(sym: str):
        try:
            df = get_ohlcv(sym, periods=200)
            r = decision.aggregate(symbol=sym, df=df)
            return sym, r["signal"], r["confidence"]
        except Exception as e:
            logger.debug("sector heatmap {} failed: {}", sym, e)
            return sym, "ERROR", 0

    by_sector: dict[str, list[str]] = {}
    skipped: list[str] = []
    for sector_name, symbols in SECTORS.items():
        ok = []
        for s in symbols:
            if _has_token(s):
                ok.append(s)
            elif s not in skipped:
                skipped.append(s)
        by_sector[sector_name] = ok
    unique = sorted({s for v in by_sector.values() for s in v})

    scores: dict[str, tuple] = {}
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = {pool.submit(_score_one, s): s for s in unique}
        for fut in as_completed(futures):
            try:
                sym, sig, conf = fut.result()
            except Exception:
                continue
            scores[sym] = (sig, conf)

    errors = sorted(s for s, (sig, _) in scores.items() if sig == "ERROR")
    sector_data = []
    for sector_name, symbols in by_sector.items():
        bulls = bears = neutral = count = 0
        total_conf = 0.0
        top = []
        for sym in symbols:
            if sym not in scores or scores[sym][0] == "ERROR":
                continue
            sig, conf = scores[sym]
            if sig in ("BUY", "STRONG_BUY"):
                bulls += 1
            elif sig in ("SELL", "STRONG_SELL"):
                bears += 1
            else:
                neutral += 1
            total_conf += conf
            count += 1
            top.append({"symbol": sym, "signal": sig, "confidence": conf})
        top.sort(key=lambda x: -x["confidence"])
        sector_data.append({
            "sector": sector_name,
            "count": count,
            "bulls": bulls, "bears": bears, "neutral": neutral,
            "net_bias": bulls - bears,
            "avg_confidence": round(total_conf / max(1, count), 2),
            "top_3": top[:3],
        })
    sector_data.sort(key=lambda s: -s["net_bias"])
    return {"sectors": sector_data, "total_sectors": len(sector_data),
            "skipped_symbols": skipped, "errors": errors,
            "computed_at": time.strftime("%Y-%m-%d %H:%M:%S")}


def _hm_worker(parallel: int) -> None:
    try:
        data = _compute_heatmap(parallel)
        with _hm_lock:
            _hm_state.update(data=data, at=time.time(), error=None)
        logger.info("sector heatmap computed: {} sectors, {} skipped, {} errors",
                    data["total_sectors"], len(data["skipped_symbols"]), len(data["errors"]))
    except Exception as e:
        logger.exception("sector heatmap compute crashed")
        with _hm_lock:
            _hm_state["error"] = f"{type(e).__name__}: {e}"
    finally:
        with _hm_lock:
            _hm_state["running"] = False
        _hm_done.set()


def _hm_start(parallel: int) -> None:
    with _hm_lock:
        if _hm_state["running"]:
            return
        _hm_state["running"] = True
        _hm_done.clear()
    threading.Thread(target=_hm_worker, args=(parallel,),
                     name="sector-heatmap", daemon=True).start()


@router.get("/sectors/heatmap", summary="Sector rotation heatmap - bullish vs bearish stock counts per sector")
def sector_heatmap(parallel: int = Query(4, ge=1, le=16),
                   refresh: bool = Query(False, description="force a background recompute")):
    """Runs decision.aggregate on every constituent of every sector and counts
    bullish vs bearish. ~180 symbols through the full engine takes minutes, so
    it is computed in a background thread and cached for 15 minutes; a request
    never blocks longer than ~20 s. Symbols missing from the scrip master are
    skipped and listed in `skipped_symbols`; symbols whose data fetch failed are
    listed in `errors` and are NOT counted as neutral.
    """
    now = time.time()
    with _hm_lock:
        data, at = _hm_state["data"], _hm_state["at"]
    if data is not None and not refresh and now - at < _HEATMAP_TTL_SEC:
        return {**data, "cached": True, "age_sec": int(now - at)}

    _hm_start(parallel)
    if data is None:
        _hm_done.wait(timeout=_HEATMAP_WAIT_SEC)
        with _hm_lock:
            data, at = _hm_state["data"], _hm_state["at"]
            err = _hm_state["error"]
        if data is None:
            return {"sectors": [], "total_sectors": 0, "status": "computing",
                    "detail": "first computation in progress - retry in a minute",
                    "error": err}
    return {**data, "cached": True, "stale": True, "age_sec": int(time.time() - at)}
