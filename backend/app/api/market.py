"""Market-data passthrough endpoints."""
from fastapi import APIRouter, HTTPException
from loguru import logger

from app.brokers.angelone import broker_instance
from app.services import instruments
from app.services.market_data import get_ohlcv

router = APIRouter()


# Index lookup keys (display + symbol). Tokens resolved at runtime from the
# Angel One scrip master to avoid hardcoded staleness.
INDEX_LOOKUP = {
    "NIFTY":     {"exchange": "NSE", "display": "NIFTY 50"},
    "BANKNIFTY": {"exchange": "NSE", "display": "BANK NIFTY"},
    "FINNIFTY":  {"exchange": "NSE", "display": "FIN NIFTY"},
    "SENSEX":    {"exchange": "BSE", "display": "SENSEX"},
}


@router.get("/instruments/status", summary="Angel One scrip-master cache status")
def instruments_status():
    return instruments.stats()


@router.post("/instruments/refresh", summary="Force-refresh the Angel One scrip-master cache")
def instruments_refresh():
    n = instruments.load(force_refresh=True)
    return {"reloaded": True, "indexed": n}


@router.get("/search", summary="Symbol search — autocomplete-friendly")
def search_instruments(q: str, exchange: str = "", limit: int = 20):
    """Fuzzy-prefix search over the scrip master. Returns top `limit`
    matches ordered by:
      1. Exact symbol match first
      2. Prefix match second
      3. Substring match third (in symbol or company name)
    Filter by exchange (NSE / BSE / NFO / MCX) when supplied.
    """
    q = (q or "").strip().upper()
    if len(q) < 1:
        return {"query": q, "results": []}

    # Reuse the scrip-master in-memory map
    try:
        all_rows = instruments.all_instruments()       # if exposed
    except (AttributeError, Exception):
        all_rows = []

    if not all_rows:
        # Fallback — common Indian symbol list. Better than returning empty.
        FALLBACK = [
            ("NIFTY",     "NSE", "NIFTY 50 INDEX"),
            ("BANKNIFTY", "NSE", "BANK NIFTY INDEX"),
            ("FINNIFTY",  "NSE", "FIN NIFTY INDEX"),
            ("SENSEX",    "BSE", "BSE SENSEX"),
            ("RELIANCE",  "NSE", "RELIANCE INDUSTRIES"),
            ("TCS",       "NSE", "TATA CONSULTANCY SERVICES"),
            ("HDFCBANK",  "NSE", "HDFC BANK"),
            ("INFY",      "NSE", "INFOSYS"),
            ("ICICIBANK", "NSE", "ICICI BANK"),
            ("SBIN",      "NSE", "STATE BANK OF INDIA"),
            ("ITC",       "NSE", "ITC LIMITED"),
            ("LT",        "NSE", "LARSEN AND TOUBRO"),
            ("KOTAKBANK", "NSE", "KOTAK MAHINDRA BANK"),
            ("AXISBANK",  "NSE", "AXIS BANK"),
            ("HINDUNILVR","NSE", "HINDUSTAN UNILEVER"),
            ("BAJFINANCE","NSE", "BAJAJ FINANCE"),
            ("WIPRO",     "NSE", "WIPRO LIMITED"),
            ("MARUTI",    "NSE", "MARUTI SUZUKI"),
            ("ASIANPAINT","NSE", "ASIAN PAINTS"),
            ("TATASTEEL", "NSE", "TATA STEEL"),
            ("COALINDIA", "NSE", "COAL INDIA"),
            ("ONGC",      "NSE", "OIL AND NATURAL GAS"),
            ("NTPC",      "NSE", "NTPC LIMITED"),
            ("POWERGRID", "NSE", "POWER GRID CORP"),
        ]
        all_rows = [{"symbol": s, "exchange": e, "name": n} for s, e, n in FALLBACK]

    def score(row: dict) -> int:
        """Lower is better — sort ascending."""
        sym = (row.get("symbol") or "").upper()
        name = (row.get("name") or "").upper()
        if sym == q: return 0
        if sym.startswith(q): return 1
        if q in sym: return 2
        if name.startswith(q): return 3
        if q in name: return 4
        return 99

    if exchange:
        all_rows = [r for r in all_rows if (r.get("exchange") or "").upper() == exchange.upper()]

    scored = [(score(r), r) for r in all_rows]
    scored = [(s, r) for s, r in scored if s < 99]
    scored.sort(key=lambda t: (t[0], (t[1].get("symbol") or "")))

    results = [
        {
            "symbol":   r.get("symbol"),
            "exchange": r.get("exchange") or "NSE",
            "name":     r.get("name") or "",
            "token":    str(r.get("token") or ""),
        }
        for _, r in scored[:limit]
    ]
    return {"query": q, "results": results, "count": len(results)}


@router.get("/sanity-audit",
             summary="Bulk scan a list of symbols and report which ones have SUSPECT pricing")
def sanity_audit(symbols: str = "NIFTY,BANKNIFTY,RELIANCE,TCS,HDFCBANK,INFY,ICICIBANK,SBIN,COALINDIA,ITC",
                         exchange: str = "NSE"):
    """Scans the symbol list, runs the 3-way price sanity check on each,
    returns the SUSPECT ones first. Use this proactively (cron, manual
    button in admin) to catch data issues across the universe BEFORE
    users hit them.

    Default symbol list is the most-watched NIFTY 50 names. For full
    universe scans, pass `symbols=ALL` (slower; scans active watchlists +
    F&O participants).
    """
    from app.services.market_data import get_ohlcv, LiveDataUnavailable
    from app.services.price_sanity import check as sanity_check

    if symbols.strip().upper() == "ALL":
        # Pull from active watchlist + recent signals universe
        try:
            from app.database import SessionLocal
            from app.models.watchlist import WatchlistItem
            from app.models.signals_journal import SignalJournalEntry
            from datetime import datetime, timedelta
            cutoff = datetime.utcnow() - timedelta(days=7)
            with SessionLocal() as db:
                wl = {w.symbol for w in db.query(WatchlistItem).all()}
                sg = {r.symbol for r in db.query(SignalJournalEntry)
                                            .filter(SignalJournalEntry.emitted_at >= cutoff).all()}
            symbol_list = sorted(wl | sg)
        except Exception as e:
            logger.warning("Universe expansion failed: {} — using default list", e)
            symbol_list = symbols.split(",")
    else:
        symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]

    suspect = []
    ok      = []
    errors  = []
    for sym in symbol_list:
        try:
            df = get_ohlcv(sym, exchange=exchange, periods=30)
            report = sanity_check(sym, df, exchange=exchange).to_dict()
            row = {"symbol": sym, "verdict": report["verdict"],
                    "candle_close": report.get("candle_close"),
                    "broker_ltp": report.get("broker_ltp"),
                    "discrepancy_pct": report.get("discrepancy_pct"),
                    "last_bar_age_days": report.get("last_bar_age_days"),
                    "reasons": report.get("reasons", [])[:2]}
            if report["verdict"] == "SUSPECT":
                suspect.append(row)
            else:
                ok.append(row)
        except LiveDataUnavailable as e:
            errors.append({"symbol": sym, "error": f"data unavailable: {e}"})
        except Exception as e:
            errors.append({"symbol": sym, "error": str(e)})

    suspect.sort(key=lambda r: r.get("discrepancy_pct") or 0, reverse=True)

    return {
        "scanned":       len(symbol_list),
        "suspect_count": len(suspect),
        "ok_count":      len(ok),
        "error_count":   len(errors),
        "suspect":       suspect,
        "ok":            ok,
        "errors":        errors,
        "next_action":   ("Run /api/market/instruments/refresh, then re-audit"
                            if suspect else "No data integrity issues detected"),
    }


@router.get("/diagnose/{symbol}",
             summary="Per-symbol data-integrity diagnostic — walks each step from "
                     "scrip-master lookup → OHLCV fetch → LTP cross-check and reports "
                     "exactly where (if anywhere) the data goes wrong.")
def diagnose_symbol(symbol: str, exchange: str = "NSE", periods: int = 50):
    """Use this when a symbol's price looks wrong on the UI. The output
    tells you exactly which layer is broken:

      • Scrip-master miss          → POST /api/market/instruments/refresh
      • Broker LTP returns nothing → broker session issue / wrong segment
      • Candle close vs LTP mismatch → stale cache or wrong instrument
      • Last bar from days ago      → run backfill for this symbol
    """
    from app.services.market_data import get_ohlcv, LiveDataUnavailable
    from app.services.price_sanity import check as sanity_check

    sym = symbol.upper().strip()
    steps: list[dict] = []

    # Step 1 — scrip-master lookup
    try:
        row = instruments.lookup(sym, exchange)
        if row:
            steps.append({"step": "1. scrip-master lookup",
                            "ok": True,
                            "details": {"token": str(row.get("token") or "?"),
                                          "name": str(row.get("name") or "?"),
                                          "exchange": exchange}})
        else:
            steps.append({"step": "1. scrip-master lookup",
                            "ok": False,
                            "fix": "Symbol not in scrip master. POST /api/market/instruments/refresh "
                                    "then retry. If still missing, check exchange (NSE vs BSE vs NFO)."})
    except Exception as e:
        steps.append({"step": "1. scrip-master lookup", "ok": False, "fix": str(e)})

    # Step 2 — broker auth
    steps.append({
        "step": "2. broker authenticated",
        "ok": broker_instance.is_authenticated(),
        "fix": "Hit /api/broker/diagnose to find why login isn't working"
               if not broker_instance.is_authenticated() else None,
    })

    # Step 3 — broker LTP quote
    broker_ltp = None
    if broker_instance.is_authenticated() and steps[0]["ok"]:
        try:
            token = (instruments.lookup(sym, exchange) or {}).get("token")
            q = broker_instance.quote(exchange, sym, str(token))
            data = (q.get("data") or {}) if isinstance(q, dict) else {}
            broker_ltp = data.get("ltp")
            steps.append({"step": "3. broker quote() LTP", "ok": broker_ltp is not None,
                            "details": {"ltp": broker_ltp,
                                          "open": data.get("open"),
                                          "high": data.get("high"),
                                          "low":  data.get("low"),
                                          "close": data.get("close")},
                            "fix": "Broker returned no LTP — wrong segment or symbol mid-suspension"
                                   if broker_ltp is None else None})
        except Exception as e:
            steps.append({"step": "3. broker quote() LTP", "ok": False, "fix": str(e)})
    else:
        steps.append({"step": "3. broker quote() LTP", "ok": False,
                       "fix": "Skipped — fix prior steps first"})

    # Step 4 — OHLCV fetch + sanity check
    try:
        df = get_ohlcv(sym, exchange=exchange, periods=periods)
        sanity = sanity_check(sym, df, exchange=exchange)
        steps.append({
            "step": "4. OHLCV fetch + sanity",
            "ok":   sanity.verdict == "OK",
            "details": sanity.to_dict(),
            "fix":  ("Stale cache or wrong instrument. "
                       "POST /api/market/instruments/refresh, then run backfill: "
                       f"POST /api/backfill/run?symbols={sym}"
                       if sanity.verdict == "SUSPECT" else None),
        })
    except LiveDataUnavailable as e:
        steps.append({"step": "4. OHLCV fetch + sanity", "ok": False,
                       "fix": f"Live data unavailable: {e}"})
    except Exception as e:
        steps.append({"step": "4. OHLCV fetch + sanity", "ok": False, "fix": str(e)})

    all_ok = all(s["ok"] for s in steps)
    return {
        "symbol": sym, "exchange": exchange,
        "overall_ok": all_ok,
        "summary": "data integrity OK" if all_ok
                   else f"first failure: {next((s['step'] for s in steps if not s['ok']), '?')}",
        "steps": steps,
    }


@router.get("/ohlcv/{symbol}", summary="OHLCV history (paper-safe)")
def ohlcv(symbol: str, exchange: str = "NSE", periods: int = 250):
    try:
        df = get_ohlcv(symbol, exchange=exchange, periods=periods)
        df = df.reset_index().rename(columns={df.index.name or "index": "timestamp"})
        return {
            "symbol": symbol,
            "exchange": exchange,
            "periods": len(df),
            "data": df.assign(timestamp=lambda x: x["timestamp"].astype(str)).to_dict(orient="records"),
        }
    except Exception as e:
        raise HTTPException(500, f"ohlcv failed: {e}")


def _resolve_index(sym: str, exchange: str) -> tuple[str | None, str | None]:
    """Find (tradingsymbol, token) for an index from the scrip master."""
    row = instruments.lookup(sym, exchange)
    if row:
        return row.get("symbol"), str(row.get("token"))
    return None, None


def _paper_quote(sym: str, exchange: str, display: str) -> dict:
    """Synthetic last-close + day-change for paper mode."""
    try:
        df = get_ohlcv(sym, exchange=exchange, periods=5)
        last_close = float(df["close"].iloc[-1])
        prev_close = float(df["close"].iloc[-2]) if len(df) > 1 else last_close
        change = last_close - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0
        return {
            "symbol": sym, "display": display,
            "price": round(last_close, 2),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
            "is_live": False,
        }
    except Exception as e:
        return {"symbol": sym, "display": display, "error": str(e), "is_live": False}


@router.get("/indices", summary="Live prices for headline indices (NIFTY / BANKNIFTY / FINNIFTY / SENSEX)")
def indices():
    """Returns headline-index quotes for the global header ticker.

    LIVE  : single batch call via SmartAPI getMarketData(LTP) — efficient.
    PAPER : derives from deterministic synthetic OHLCV per symbol.
    """
    is_live = broker_instance.is_authenticated()
    out: list[dict] = []

    # ---------- PAPER mode ----------
    if not is_live:
        for sym, meta in INDEX_LOOKUP.items():
            out.append(_paper_quote(sym, meta["exchange"], meta["display"]))
        return {"indices": out, "live": False,
                 "note": "PAPER mode. Set ANGELONE_* in .env and restart backend for live prices."}

    # ---------- LIVE mode — single batch call ----------
    # Build {exchange: [tokens]} and remember the (sym, token) mapping for later
    exchange_tokens: dict[str, list[str]] = {}
    sym_to_meta: dict[tuple[str, str], dict] = {}   # (exchange, token) -> {sym, display, tradingsymbol}

    for sym, meta in INDEX_LOOKUP.items():
        ts, token = _resolve_index(sym, meta["exchange"])
        if not token:
            out.append({"symbol": sym, "display": meta["display"],
                         "error": f"token not in scrip master ({meta['exchange']}/{sym})",
                         "is_live": False})
            continue
        exchange_tokens.setdefault(meta["exchange"], []).append(token)
        sym_to_meta[(meta["exchange"], token)] = {
            "sym": sym, "display": meta["display"], "tradingsymbol": ts,
        }

    if not exchange_tokens:
        return {"indices": out, "live": True, "warning": "no index tokens resolved"}

    # Single batch call
    try:
        batch = broker_instance.quotes_batch(mode="LTP", exchange_tokens=exchange_tokens)
    except Exception as e:
        logger.warning("batch indices fetch failed → falling back to paper: {}", e)
        for sym, meta in INDEX_LOOKUP.items():
            out.append(_paper_quote(sym, meta["exchange"], meta["display"]))
        return {"indices": out, "live": True, "warning": f"live batch failed: {e}"}

    if not isinstance(batch, dict) or not batch.get("status"):
        msg = batch.get("message") if isinstance(batch, dict) else str(batch)
        logger.warning("getMarketData returned non-success: {}", msg)
        for sym, meta in INDEX_LOOKUP.items():
            out.append(_paper_quote(sym, meta["exchange"], meta["display"]))
        return {"indices": out, "live": True, "warning": f"SmartAPI: {msg}"}

    # Map the batch result back to our index list
    # getMarketData LTP returns: { data: { fetched: [ {exchange, tradingSymbol, symbolToken, ltp, close, ...}, ... ] } }
    fetched = ((batch.get("data") or {}).get("fetched") or [])
    by_token: dict[tuple[str, str], dict] = {}
    for row in fetched:
        ex = (row.get("exchange") or "").upper()
        tk = str(row.get("symbolToken") or row.get("symboltoken") or "")
        by_token[(ex, tk)] = row

    for sym, meta in INDEX_LOOKUP.items():
        ts, token = _resolve_index(sym, meta["exchange"])
        if not token:
            continue       # already handled above
        q = by_token.get((meta["exchange"], token))
        if not q:
            out.append({"symbol": sym, "display": meta["display"], "is_live": False,
                         "error": "no LTP returned for this token (market closed?)"})
            continue
        ltp = float(q.get("ltp") or 0)
        close_prev = float(q.get("close") or 0)
        change = ltp - close_prev if close_prev else 0
        change_pct = (change / close_prev * 100) if close_prev else 0
        out.append({
            "symbol": sym, "display": meta["display"],
            "price": round(ltp, 2),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
            "is_live": True,
            "high": q.get("high"), "low": q.get("low"), "open": q.get("open"),
        })

    return {"indices": out, "live": True}


@router.get("/quote/{symbol}", summary="LTP for a single instrument")
def quote(symbol: str, exchange: str = "NSE"):
    """One-shot LTP call for any symbol — falls back to last-close in paper mode."""
    if not broker_instance.is_authenticated():
        df = get_ohlcv(symbol, exchange=exchange, periods=2)
        last = float(df["close"].iloc[-1])
        return {"symbol": symbol, "exchange": exchange, "ltp": last, "is_live": False}
    row = instruments.lookup(symbol, exchange)
    if not row:
        raise HTTPException(404, f"instrument not found: {exchange}/{symbol}")
    try:
        q = broker_instance.quote(exchange, row["symbol"], str(row["token"]))
        data = (q.get("data") or {}) if isinstance(q, dict) else {}
        return {"symbol": symbol, "exchange": exchange,
                 "ltp": float(data.get("ltp") or 0),
                 "open": data.get("open"), "high": data.get("high"),
                 "low": data.get("low"), "close": data.get("close"),
                 "is_live": True, "raw": data}
    except Exception as e:
        raise HTTPException(500, f"quote failed: {e}")
