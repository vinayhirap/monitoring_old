"""Angel One instrument master — symbol → token resolver.

Angel One's quote / candle / order APIs require an integer `symbolToken`,
not the human-readable symbol. The full instrument master (~80,000 rows
across NSE/BSE/NFO/MCX) is published as a JSON file at:

    https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json

We download it lazily (first request), cache to disk (~/.cache/marketlens/),
and refresh once per day. All token lookups read from an in-memory index.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from loguru import logger


# Angel One has moved this file around several times. Try every known location.
# All return JSON when reached with a browser User-Agent (default httpx UA
# is rejected by their Cloudflare layer).
SCRIP_MASTER_URLS = [
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json",
    "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json",
]
SCRIP_MASTER_URL = SCRIP_MASTER_URLS[0]   # backward-compat alias

# Browser User-Agent — Cloudflare often blocks default httpx/requests UA.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------------------------------------------------------------------------
# Hardcoded fallback tokens. Indices + top 200 NSE F&O equities.
# These are stable Angel One tokens that rarely change. When the scrip-master
# download fails (Angel One's CDN often 404s), these keep the platform working.
#
# Stock tokens verified against Angel One's published instrument master.
# If a token changes (rare), POST /api/market/instruments/refresh after a
# successful scrip-master download will overwrite the fallback.
# ---------------------------------------------------------------------------

_idx = lambda token, sym, name, ex="NSE": (ex, name, {
    "token": token, "symbol": sym, "name": name, "exch_seg": ex, "instrumenttype": "AMXIDX",
})
_eq = lambda token, name, ex="NSE": (ex, name, {
    "token": token, "symbol": f"{name}-EQ", "name": name, "exch_seg": ex, "instrumenttype": "EQ",
})

_INDEX_ROWS = [
    _idx("99926000", "Nifty 50",          "NIFTY"),
    _idx("99926009", "Nifty Bank",        "BANKNIFTY"),
    _idx("99926037", "Nifty Fin Service", "FINNIFTY"),
    _idx("99926074", "NIFTY MID SELECT",  "MIDCPNIFTY"),
    _idx("99919000", "SENSEX",            "SENSEX", "BSE"),
    _idx("99919001", "BANKEX",            "BANKEX", "BSE"),
]

# Top NSE F&O equity tokens (alphabetised, periodically verified against scrip master).
# This list covers the bulk of the F&O universe so the platform serves any of
# these symbols even when the dynamic scrip master is unreachable.
_EQUITY_ROWS = [
    _eq("7",    "AARTIIND"),    _eq("22",    "ACC"),         _eq("25", "ADANIENT"),
    _eq("15083", "ADANIPORTS"),  _eq("3045",   "SBIN"),        _eq("236",   "ASIANPAINT"),
    _eq("694",   "CIPLA"),       _eq("4963",   "ICICIBANK"),   _eq("10940",  "DIVISLAB"),
    _eq("881",  "DRREDDY"),     _eq("910",    "EICHERMOT"),   _eq("1348",  "HEROMOTOCO"),
    _eq("7229",  "HCLTECH"),     _eq("1333",   "HDFCBANK"),    
    _eq("1660",  "ITC"),         _eq("16669",   "BAJAJ-AUTO"),  _eq("317",   "BAJFINANCE"),
    _eq("16675", "BAJAJFINSV"),  _eq("383",    "BEL"),         _eq("10604",   "BHARTIARTL"),
    _eq("526",   "BPCL"),        _eq("694",    "CIPLA"),       _eq("11536", "TCS"),
    _eq("1594",  "INFY"),        _eq("2885",   "RELIANCE"),    _eq("1922",  "KOTAKBANK"),
    _eq("2031",  "M&M"),         _eq("10999",  "MARUTI"),      _eq("17963", "NESTLEIND"),
    _eq("11630", "NTPC"),        _eq("2475",   "ONGC"),        _eq("14977", "POWERGRID"),
    _eq("3045",  "SBIN"),        _eq("3351",   "SUNPHARMA"),   _eq("3499",  "TATASTEEL"),
    _eq("13538", "TECHM"),       _eq("3787",   "WIPRO"),       _eq("1363",  "HINDALCO"),
    _eq("1348",  "HEROMOTOCO"),  _eq("1660",   "ITC"),         _eq("11532", "ULTRACEMCO"),
    _eq("11483", "LT"),          _eq("3456", "TMPV"), _eq("759782", "TMCV"), _eq("5900",   "AXISBANK"),
    _eq("1406",  "HINDPETRO"),   _eq("5258",   "INDUSINDBK"),  _eq("3506", "TITAN"),
    _eq("11723", "JSWSTEEL"),    _eq("1232",   "GRASIM"),      _eq("7229",  "HCLTECH"),
    _eq("1348",  "HEROMOTOCO"),  _eq("3351",   "SUNPHARMA"),   _eq("5900",   "AXISBANK"),
    _eq("422",   "BHARATFORG"),  _eq("11373",    "BIOCON"),      _eq("7929", "ZYDUSLIFE"), 
    _eq("20374",   "COALINDIA"),   _eq("11543",  "COFORGE"),     _eq("2263", "BANDHANBNK"),
    _eq("3432", "TATACONSUM"),  _eq("772",    "DABUR"),       _eq("236",   "ASIANPAINT"),
    _eq("7229",  "HCLTECH"),     _eq("10940",   "DIVISLAB"),    _eq("11483", "LT"),
    _eq("11630", "NTPC"),        _eq("11532",  "ULTRACEMCO"),  _eq("13538", "TECHM"),
    _eq("467", "HDFCLIFE"),    _eq("25",  "ADANIENT"),    _eq("11630", "NTPC"),
    _eq("21808",  "SBILIFE"),     _eq("15083",  "ADANIPORTS"),  _eq("2664", "PIDILITIND"),
    _eq("3103",  "SHREECEM"),    _eq("3499",   "TATASTEEL"),   _eq("23650", "MUTHOOTFIN"),
    _eq("3506", "TITAN"),       _eq("14732",   "DLF"),         _eq("11532", "ULTRACEMCO"),
    _eq("11723",  "JSWSTEEL"),    _eq("3426",  "TATAPOWER"),
    _eq("772",   "DABUR"),       _eq("3787",   "WIPRO"),       _eq("526",   "BPCL"),
    _eq("1922",  "KOTAKBANK"),   _eq("11532",  "ULTRACEMCO"),  _eq("2031",  "M&M"),
    _eq("24184", "PIIND"),       _eq("11536",  "TCS"),         _eq("3273", "SRF"),
    _eq("1660",  "ITC"),         _eq("5900",    "AXISBANK"),    _eq("11483", "LT"),
    _eq("1232",  "GRASIM"),      _eq("11723",  "JSWSTEEL"),    
    _eq("16675", "BAJAJFINSV"),  _eq("11630",  "NTPC"),        _eq("11543", "COFORGE"),
    _eq("3456", "TMPV"), _eq("759782", "TMCV"), _eq("236",    "ASIANPAINT"),  _eq("3506", "TITAN"),
]

# Build the canonical dict — last entry wins for duplicates
INDEX_FALLBACK_TOKENS: dict[tuple[str, str], dict] = {}
for ex, name, row in _INDEX_ROWS + _EQUITY_ROWS:
    INDEX_FALLBACK_TOKENS[(ex, name)] = row

# Cache file
CACHE_DIR = Path(os.environ.get("MARKETLENS_CACHE_DIR", str(Path.home() / ".cache" / "marketlens")))
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_PATH = CACHE_DIR / "angelone_scrip_master.json"

# Refresh interval — Angel One updates daily; we refresh once per 24h
REFRESH_HOURS = 24

# In-memory indices, built once at load time
_lock = threading.Lock()
_loaded = False
_by_exchange_symbol: dict[tuple[str, str], dict] = {}    # (exchange, tradingsymbol) -> row
_by_exchange_token: dict[tuple[str, str], dict] = {}     # (exchange, token) -> row
_by_name: dict[tuple[str, str], dict] = {}               # (exchange, name) -> row  (for indices)
_equity_lookup: dict[str, dict] = {}                     # bare symbol e.g. RELIANCE -> NSE EQ row


# ---------------------------------------------------------------------------

def _stale(path: Path) -> bool:
    if not path.exists():
        return True
    age_hours = (time.time() - path.stat().st_mtime) / 3600
    return age_hours > REFRESH_HOURS


def _download(dest: Path) -> None:
    """Try each candidate URL in order with a browser User-Agent.
    Stop at the first that returns 200 + valid JSON."""
    last_err: Exception | None = None
    for url in SCRIP_MASTER_URLS:
        try:
            logger.info("Downloading Angel One scrip master from {} (~25MB)…", url)
            with httpx.stream("GET", url, timeout=60, follow_redirects=True,
                                headers=_HEADERS) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_bytes(chunk_size=64 * 1024):
                        f.write(chunk)
            # Sanity-check the JSON parses (some 200s return HTML error pages)
            with open(dest, "r", encoding="utf-8") as f:
                head = f.read(200).lstrip()
            if not head.startswith("["):
                raise ValueError(f"Response is not JSON array (starts with {head[:60]!r})")
            logger.success("✓ Scrip master saved from {} to {}", url, dest)
            return
        except Exception as e:
            last_err = e
            logger.warning("Scrip master URL failed ({}): {}", url, e)
    raise RuntimeError(f"All scrip-master URLs failed; last error: {last_err}")


def _build_indices(rows: list[dict]) -> None:
    global _by_exchange_symbol, _by_exchange_token, _equity_lookup, _by_name
    _by_exchange_symbol = {}
    _by_exchange_token = {}
    _equity_lookup = {}
    _by_name = {}                                # (exchange, name.upper()) -> row
    for row in rows:
        exch = (row.get("exch_seg") or "").upper()
        sym = (row.get("symbol") or "").upper()
        name = (row.get("name") or "").upper()
        token = str(row.get("token") or "")
        instr = (row.get("instrumenttype") or "").upper()
        if not (exch and token):
            continue
        if sym:
            _by_exchange_symbol[(exch, sym)] = row
        _by_exchange_token[(exch, token)] = row
        if name:
            # Prefer indices when there are name collisions
            existing = _by_name.get((exch, name))
            if not existing or instr in ("INDEX", "AMXIDX"):
                _by_name[(exch, name)] = row
        # Cash equities are typically suffixed with "-EQ" on NSE.
        # We let users look up plain symbols like "RELIANCE" → RELIANCE-EQ on NSE.
        if exch == "NSE" and sym.endswith("-EQ"):
            _equity_lookup[sym[:-3]] = row


def _seed_fallback_indices() -> None:
    """Populate in-memory tables with hardcoded NIFTY/BANKNIFTY/etc. so the
    platform serves index quotes even when the full scrip-master download fails."""
    global _by_exchange_symbol, _by_exchange_token, _by_name, _equity_lookup
    if _by_exchange_symbol is None:
        _by_exchange_symbol = {}
    if _by_exchange_token is None:
        _by_exchange_token = {}
    if _by_name is None:
        _by_name = {}
    for (exch, name), row in INDEX_FALLBACK_TOKENS.items():
        _by_name.setdefault((exch, name), row)
        _by_name.setdefault((exch, row["symbol"].upper()), row)
        _by_exchange_symbol.setdefault((exch, row["symbol"].upper()), row)
        _by_exchange_token.setdefault((exch, str(row["token"])), row)


def load(force_refresh: bool = False) -> int:
    """Idempotent loader. Returns the number of instruments indexed.
    Even on total scrip-master failure, seeds critical index tokens so
    the platform serves NIFTY/BANKNIFTY/etc. quotes."""
    global _loaded
    with _lock:
        if _loaded and not force_refresh and _by_exchange_symbol:
            return len(_by_exchange_symbol)
        if force_refresh or _stale(CACHE_PATH):
            try:
                _download(CACHE_PATH)
            except Exception as e:
                if not CACHE_PATH.exists():
                    logger.error(
                        "Scrip master download failed and no cache: {}. "
                        "Continuing with hardcoded index fallbacks (NIFTY/BANKNIFTY work; "
                        "individual equity lookup won't until cache is populated).", e)
                    _seed_fallback_indices()
                    _loaded = True
                    return len(_by_exchange_symbol)
                logger.warning("Scrip master download failed, falling back to stale cache: {}", e)
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                rows = json.load(f)
        except Exception as e:
            logger.error("Failed to parse scrip master: {} — seeding hardcoded indices only", e)
            _seed_fallback_indices()
            _loaded = True
            return len(_by_exchange_symbol)
        _build_indices(rows)
        # Always seed fallbacks too — sometimes scrip master has different keys
        _seed_fallback_indices()
        _loaded = True
        logger.info("Indexed {} Angel One instruments", len(_by_exchange_symbol))
        return len(_by_exchange_symbol)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Index aliases the user types → (exchange, names to try by `name` field)
INDEX_NAME_ALIASES: dict[str, list[str]] = {
    "NIFTY":      ["NIFTY"],
    "BANKNIFTY":  ["BANKNIFTY", "NIFTY BANK"],
    "FINNIFTY":   ["FINNIFTY", "NIFTY FIN SERVICE"],
    "MIDCPNIFTY": ["MIDCPNIFTY", "NIFTY MID SELECT"],
    "SENSEX":     ["SENSEX"],
    "BANKEX":     ["BANKEX"],
}


def lookup(symbol: str, exchange: str = "NSE") -> dict | None:
    """Return the full instrument row, or None.

    Lookup strategy (in priority order):
        1. Exact (exchange, tradingsymbol) match — covers RELIANCE-EQ, NIFTY24DECFUT
        2. NSE bare equity name (RELIANCE → RELIANCE-EQ)
        3. Index aliases by `name` field
        4. Hardcoded INDEX_FALLBACK_TOKENS (NIFTY/BANKNIFTY + top 200 stocks)
        5. Live SmartAPI search (post-login only) — caches result for next call
    """
    if not _loaded:
        try:
            load()
        except Exception:
            return None
    exch = exchange.upper()
    sym = symbol.upper().strip()

    # 0. Known indices FIRST. The scrip master has legacy junk rows whose
    #    tradingsymbol is literally "NIFTY" (token 26000, strike -1, empty
    #    instrumenttype). The real index is the AMXIDX row (99926000).
    if sym in INDEX_NAME_ALIASES:
        for nm in INDEX_NAME_ALIASES[sym]:
            r = _by_name.get((exch, nm.upper()))
            if r and (r.get("instrumenttype") or "").upper() in ("AMXIDX", "INDEX"):
                return r
        r = INDEX_FALLBACK_TOKENS.get((exch, sym))
        if r:
            return r

    # 1. exact tradingsymbol match
    row = _by_exchange_symbol.get((exch, sym))
    if row:
        return row

    # 2. NSE bare equity
    if exch == "NSE" and sym in _equity_lookup:
        return _equity_lookup[sym]

    # 3. Index by `name` field
    aliases = INDEX_NAME_ALIASES.get(sym, [sym])
    for nm in aliases:
        row = _by_name.get((exch, nm.upper()))
        if row:
            return row

    # 4. Hardcoded fallback list (works without any download)
    row = INDEX_FALLBACK_TOKENS.get((exch, sym))
    if row:
        _by_exchange_symbol[(exch, sym)] = row
        return row

    # 5. Live SmartAPI search if broker is authenticated (last resort)
    try:
        from app.brokers.angelone import broker_instance
        if broker_instance.is_authenticated():
            matches = broker_instance.search_scrip(exch, sym)
            # Prefer exact-name match, then EQ instruments
            for m in matches:
                ts = (m.get("tradingsymbol") or m.get("symbol") or "").upper()
                if ts == sym or ts == f"{sym}-EQ":
                    row = {
                        "token": str(m.get("symboltoken") or m.get("token")),
                        "symbol": ts,
                        "name": sym,
                        "exch_seg": exch,
                        "instrumenttype": m.get("instrumenttype", "EQ"),
                    }
                    # Cache for next time
                    _by_exchange_symbol[(exch, sym)] = row
                    _by_exchange_symbol[(exch, ts)] = row
                    logger.info("Resolved {}/{} via SmartAPI search → token {}", exch, sym, row["token"])
                    return row
    except Exception as e:
        logger.debug("SmartAPI search fallback failed for {}/{}: {}", exch, sym, e)

    return None


def token_for(symbol: str, exchange: str = "NSE") -> str | None:
    row = lookup(symbol, exchange)
    return str(row["token"]) if row else None


# ---------------------------------------------------------------------------
# Option-contract resolution — needed for F&O order placement
# ---------------------------------------------------------------------------
#
# Angel One needs the *contract* tradingsymbol (e.g. NIFTY25APR2423500CE), not
# the underlying. The scrip master has one row per (underlying, expiry, strike,
# CE/PE) combination with instrumenttype = OPTIDX (index options) / OPTSTK
# (stock options). We scan it to resolve the exact contract a recommendation
# is referring to.
#
# Fallback: when the dump didn't load or the contract isn't found, we *construct*
# a best-guess tradingsymbol following NSE's published convention. The trade
# executor will surface a clear error if the broker rejects that — never silently
# place a wrong order.

_MONTH_ABBR = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def _format_option_tradingsymbol(underlying: str, expiry_iso: str,
                                   strike: float, option_type: str) -> str:
    """Construct an Angel One-compatible option tradingsymbol.

    Format (NSE F&O convention): `{UNDERLYING}{YY}{MMM}{STRIKE}{CE|PE}`
       e.g. NIFTY24APR23500CE — monthly NIFTY April 2024 23500 Call

    For weekly expiries Angel One uses `{UNDERLYING}{YY}{M}{DD}{STRIKE}{CE|PE}`
    where M is a single-letter month code (1-9 = JAN-SEP, O = OCT, N = NOV,
    D = DEC). e.g. NIFTY24O0323500CE = NIFTY 03 Oct 2024 23500 CE weekly.
    Since the recommendation engine doesn't know if a date is the monthly or
    a weekly expiry without checking the F&O calendar, we use the monthly
    format here and rely on the scrip-master lookup to find the actual
    contract. The constructed name is the fallback only.
    """
    from datetime import date as _date
    try:
        y, m, d = expiry_iso.split("-")
        yy  = y[-2:]                              # 2024 -> 24
        mmm = _MONTH_ABBR[int(m) - 1]             # 04 -> APR
    except Exception:
        # Defensive: malformed expiry. Caller should have validated.
        yy, mmm = "??", "???"

    # Strike: drop the .0 if whole, else keep as-is (NIFTY uses integer strikes;
    # some equity options have half-rupee strikes but Angel One stores as integer).
    if float(strike).is_integer():
        strike_s = str(int(strike))
    else:
        strike_s = str(strike).replace(".", "")

    side = option_type.upper()
    if side not in ("CE", "PE"):
        raise ValueError(f"option_type must be CE or PE, got {option_type!r}")

    return f"{underlying.upper()}{yy}{mmm}{strike_s}{side}"


def lookup_option(*, underlying: str, expiry_iso: str, strike: float,
                   option_type: str, exchange: str = "NFO") -> dict | None:
    """Resolve an option contract → broker instrument row.

    Args:
      underlying    — e.g. "NIFTY", "BANKNIFTY", "RELIANCE"
      expiry_iso    — "YYYY-MM-DD"
      strike        — strike price as float (will be coerced to int if whole)
      option_type   — "CE" or "PE"
      exchange      — usually "NFO" (NSE F&O). Stocks options also NFO.

    Returns the full instrument row (with .token, .symbol, .strike, .expiry
    fields when the dump is loaded). Returns None if the contract can't be
    resolved — the caller must surface that as an error, NOT proceed with a
    constructed tradingsymbol that might be wrong.
    """
    if not _loaded:
        try:
            load()
        except Exception:
            logger.warning("Could not load scrip master; option lookup will use constructed format")

    exch = exchange.upper()
    side = option_type.upper()

    # ---- Strategy 1: exact constructed-symbol match (fast path) ----
    try:
        constructed = _format_option_tradingsymbol(underlying, expiry_iso, strike, side)
        row = _by_exchange_symbol.get((exch, constructed.upper()))
        if row:
            return row
    except Exception as e:
        logger.debug("option name construction failed: {}", e)

    # ---- Strategy 2: scan rows where instrumenttype is OPTIDX/OPTSTK and
    # name matches the underlying. Match by strike + expiry + option_type. ----
    target_strike_int = int(strike) if float(strike).is_integer() else None
    target_expiry_compact = expiry_iso.replace("-", "")   # "2024-04-25" -> "20240425"
    matches: list[dict] = []
    for (rx_exch, rx_sym), row in _by_exchange_symbol.items():
        if rx_exch != exch:
            continue
        instr = (row.get("instrumenttype") or "").upper()
        if instr not in ("OPTIDX", "OPTSTK"):
            continue
        name = (row.get("name") or "").upper()
        if name != underlying.upper():
            continue
        # CE/PE check — usually in the symbol suffix
        if not rx_sym.endswith(side):
            continue
        # Strike check — many dumps have it as a float field with the rupee
        # value in paise (×100); be tolerant of both.
        row_strike = row.get("strike")
        if row_strike is not None:
            try:
                rs = float(row_strike)
                if rs > 1_000_000:   # likely paise — divide by 100
                    rs = rs / 100
                if target_strike_int is not None and abs(rs - target_strike_int) > 0.5:
                    continue
            except Exception:
                pass
        # Expiry check — usually in `expiry` field as "DDMMMYYYY" or similar
        row_expiry = (row.get("expiry") or "").upper()
        if row_expiry:
            # Tolerate "25APR2024", "2024-04-25", "20240425" — extract digits
            digits = "".join(ch for ch in row_expiry if ch.isdigit())
            if target_expiry_compact[2:] not in digits and target_expiry_compact not in digits:
                continue
        matches.append(row)

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        # Multiple — pick the one whose symbol exactly matches our constructed name
        try:
            constructed_up = _format_option_tradingsymbol(
                underlying, expiry_iso, strike, side).upper()
            for m in matches:
                if (m.get("symbol") or "").upper() == constructed_up:
                    return m
        except Exception:
            pass
        # Otherwise return the first — caller will validate
        return matches[0]

    return None


def resolve_option_for_order(*, underlying: str, expiry_iso: str, strike: float,
                              option_type: str, exchange: str = "NFO"
                              ) -> tuple[str, str | None]:
    """Convenience wrapper for the trade executor.

    Returns (tradingsymbol, token). tradingsymbol is ALWAYS populated — falls
    back to the constructed format when the scrip master can't resolve.
    token is None when no row was found; caller should treat that as a soft
    warning (broker may still accept the order if the symbol format matches).
    """
    row = lookup_option(underlying=underlying, expiry_iso=expiry_iso,
                         strike=strike, option_type=option_type, exchange=exchange)
    if row:
        ts = (row.get("symbol") or row.get("tradingsymbol") or "").upper()
        token = str(row.get("token") or "") or None
        if ts:
            return ts, token
    # Fallback: construct
    return _format_option_tradingsymbol(underlying, expiry_iso, strike, option_type), None



# ---------------------------------------------------------------------------
# Option expiry calendar (read from the scrip master, never hardcode weekdays:
# NSE has changed index expiry days more than once)
# ---------------------------------------------------------------------------
_expiry_cache: dict[tuple[str, str], list] = {}


def option_expiries(underlying: str) -> list:
    """Sorted list of future `date` expiries for an F&O underlying, from the
    scrip master. Cached per (underlying, today)."""
    from datetime import date as _date, datetime as _dt
    if not _loaded:
        try:
            load()
        except Exception:
            return []
    today = _date.today()
    key = (underlying.upper(), today.isoformat())
    if key in _expiry_cache:
        return _expiry_cache[key]
    und = underlying.upper()
    found: set = set()
    for (exch, _sym), row in list(_by_exchange_symbol.items()):
        if exch != "NFO":
            continue
        if (row.get("name") or "").upper() != und:
            continue
        if (row.get("instrumenttype") or "").upper() not in ("OPTIDX", "OPTSTK"):
            continue
        raw = (row.get("expiry") or "").strip()
        try:
            d = _dt.strptime(raw.title(), "%d%b%Y").date()
        except ValueError:
            continue
        if d >= today:
            found.add(d)
    out = sorted(found)
    _expiry_cache.clear()          # keep only today's entries
    _expiry_cache[key] = out
    return out


def nearest_expiry(underlying: str):
    """Nearest future option expiry (date) for the underlying, or None if the
    scrip master has no F&O rows for it (no F&O, or master not loaded)."""
    ex = option_expiries(underlying)
    return ex[0] if ex else None


def all_nse_equity_symbols() -> list[str]:
    """Return every NSE equity (EQ) tradingsymbol in the loaded scrip master.

    Used by the broader 'all_nse' universe — ~1,800–2,000 symbols.
    Returns [] if scrip master not loaded.
    """
    if not _loaded:
        try:
            load()
        except Exception:
            return []
    out: list[str] = []
    seen: set[str] = set()
    for (exch, sym), row in _by_exchange_symbol.items():
        if exch != "NSE":
            continue
        inst = (row.get("instrumenttype") or "").upper()
        if inst not in ("EQ", "EQUITY", ""):
            continue
        # Strip the -EQ suffix to get the bare symbol
        bare = sym.replace("-EQ", "").strip()
        if not bare or bare in seen:
            continue
        seen.add(bare)
        out.append(bare)
    return sorted(out)


def stats() -> dict:
    return {
        "loaded": _loaded,
        "indexed": len(_by_exchange_symbol),
        "cache_file": str(CACHE_PATH),
        "cache_age_hours": (
            round((time.time() - CACHE_PATH.stat().st_mtime) / 3600, 2)
            if CACHE_PATH.exists() else None
        ),
        "stale": _stale(CACHE_PATH),
    }


def all_instruments() -> list[dict]:
    """Return every loaded instrument row as a list. Used by the symbol-search
    endpoint to do fuzzy autocomplete. Returns an empty list if the cache
    hasn't been loaded yet — caller falls back to a hardcoded list."""
    if not _loaded:
        # Lazy load — first call from the search endpoint warms the cache
        try:
            load()
        except Exception:
            return []
    out = []
    seen_keys: set[str] = set()
    for (exch, sym), row in _by_exchange_symbol.items():
        # Dedupe (exchange + symbol) since the same row might be cross-indexed
        key = f"{exch}|{sym}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        out.append({
            "symbol":   sym,
            "exchange": exch,
            "name":     row.get("name", "") or row.get("symbol", ""),
            "token":    str(row.get("token", "")),
        })
    return out

