"""NSE historical-data importer.

Two ingestion paths:

  1. Direct scraper — hits nseindia.com's `indicesHistory` API.
     Requires cookie session. Works ~70% of the time from non-AWS IPs,
     ~30% from AWS due to NSE's geo-IP filtering. Use as a fallback.

  2. CSV importer — accepts a manually-downloaded CSV from the NSE page
     and persists rows into ohlcv_bars. Most reliable; needs one manual
     download per index per date range.

Both paths write into the same `ohlcv_bars` table that the backfill engine
uses, so everything downstream (backtester, calibration, ML) consumes the
data transparently.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable

import pandas as pd
import httpx
from loguru import logger
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.database import SessionLocal, engine
from app.models.ohlcv_bar import OHLCVBar


# ---------------------------------------------------------------------------
# Known NSE indices — display names and the symbol we'll store as
# ---------------------------------------------------------------------------

NSE_INDEX_MAP: dict[str, dict] = {
    "NIFTY 50":              {"symbol": "NIFTY",       "category": "broad"},
    "NIFTY BANK":            {"symbol": "BANKNIFTY",   "category": "broad"},
    "NIFTY FINANCIAL SERVICES": {"symbol": "FINNIFTY", "category": "broad"},
    "NIFTY MIDCAP 100":      {"symbol": "MIDCPNIFTY",  "category": "broad"},
    "NIFTY NEXT 50":         {"symbol": "NIFTYNXT50",  "category": "broad"},
    "NIFTY 100":             {"symbol": "NIFTY100",    "category": "broad"},
    "NIFTY 500":             {"symbol": "NIFTY500",    "category": "broad"},
    "NIFTY IT":              {"symbol": "NIFTYIT",     "category": "sectoral"},
    "NIFTY AUTO":            {"symbol": "NIFTYAUTO",   "category": "sectoral"},
    "NIFTY PHARMA":          {"symbol": "NIFTYPHARMA", "category": "sectoral"},
    "NIFTY FMCG":            {"symbol": "NIFTYFMCG",   "category": "sectoral"},
    "NIFTY METAL":           {"symbol": "NIFTYMETAL",  "category": "sectoral"},
    "NIFTY REALTY":          {"symbol": "NIFTYREALTY", "category": "sectoral"},
    "NIFTY ENERGY":          {"symbol": "NIFTYENERGY", "category": "sectoral"},
    "NIFTY PSU BANK":        {"symbol": "NIFTYPSUBANK","category": "sectoral"},
    "NIFTY PRIVATE BANK":    {"symbol": "NIFTYPVTBANK","category": "sectoral"},
    "NIFTY ALPHA 50":        {"symbol": "NIFTYALPHA50","category": "smart-beta"},
    "INDIA VIX":             {"symbol": "INDIAVIX",    "category": "volatility"},
}


# ---------------------------------------------------------------------------
# DB upsert helper (shared with backfill.py — same idempotent pattern)
# ---------------------------------------------------------------------------

def _upsert(session, rows: list[dict]) -> int:
    if not rows:
        return 0
    dialect = engine.dialect.name
    if dialect == "postgresql":
        stmt = pg_insert(OHLCVBar.__table__).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "timeframe", "ts"],
            set_={k: getattr(stmt.excluded, k) for k in
                  ("open", "high", "low", "close", "volume", "source")},
        )
    elif dialect == "sqlite":
        stmt = sqlite_insert(OHLCVBar.__table__).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "timeframe", "ts"],
            set_={k: getattr(stmt.excluded, k) for k in
                  ("open", "high", "low", "close", "volume", "source")},
        )
    else:
        session.execute(OHLCVBar.__table__.insert(), rows)
        return len(rows)
    session.execute(stmt)
    return len(rows)


# ---------------------------------------------------------------------------
# Path 1 — Direct NSE scraper
# ---------------------------------------------------------------------------

class NSEScrapeError(Exception):
    pass


class _NSEClient:
    """One-time session that handles the cookie dance NSE requires."""
    BASE = "https://www.nseindia.com"
    HEADERS = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/reports-indices-historical-index-data",
        "Connection": "keep-alive",
    }

    def __init__(self):
        self.client = httpx.Client(timeout=30, follow_redirects=True, headers=self.HEADERS)
        self._initialised = False

    def _establish_session(self):
        # Two warm-up GETs to collect cookies — NSE rejects bare API calls
        try:
            self.client.get(f"{self.BASE}/")
            self.client.get(f"{self.BASE}/market-data/live-market-indices")
            self._initialised = True
        except Exception as e:
            raise NSEScrapeError(f"failed to establish NSE session: {e}")

    def fetch_index(self, nse_index_name: str,
                     from_date: date, to_date: date) -> list[dict]:
        if not self._initialised:
            self._establish_session()

        url = f"{self.BASE}/api/historical/indicesHistory"
        params = {
            "indexType": nse_index_name,
            "from": from_date.strftime("%d-%m-%Y"),
            "to":   to_date.strftime("%d-%m-%Y"),
        }
        r = self.client.get(url, params=params)
        if r.status_code in (401, 403):
            raise NSEScrapeError(
                f"NSE blocked the request (HTTP {r.status_code}). "
                f"Likely AWS IP filtering; use the CSV import path instead."
            )
        if r.status_code != 200:
            raise NSEScrapeError(f"NSE returned HTTP {r.status_code}: {r.text[:200]}")
        try:
            data = r.json()
        except Exception:
            raise NSEScrapeError(
                "NSE returned non-JSON (probably an HTML challenge page). "
                "Use the CSV import path instead."
            )
        # NSE response shape: {"data": {"indexCloseOnlineRecords": [...]}}
        rows = (data.get("data", {}) or {}).get("indexCloseOnlineRecords", [])
        return rows


def scrape_index(nse_index_name: str, days_back: int = 365) -> dict:
    """Scrape one NSE index and persist to ohlcv_bars.

    Returns: {scraped, inserted, errors}
    """
    if nse_index_name not in NSE_INDEX_MAP:
        return {"error": f"Unknown index '{nse_index_name}'. "
                          f"Available: {list(NSE_INDEX_MAP.keys())}"}
    info = NSE_INDEX_MAP[nse_index_name]
    to_date = date.today()
    from_date = to_date - timedelta(days=days_back)

    client = _NSEClient()
    # NSE caps a single request to ~1 year. Chunk into 365-day windows.
    cur = from_date
    all_rows: list[dict] = []
    chunk_errors: list[str] = []
    while cur < to_date:
        chunk_end = min(cur + timedelta(days=365), to_date)
        try:
            chunk = client.fetch_index(nse_index_name, cur, chunk_end)
            all_rows.extend(chunk)
        except NSEScrapeError as e:
            chunk_errors.append(f"{cur}–{chunk_end}: {e}")
        cur = chunk_end + timedelta(days=1)

    # Normalize to ohlcv_bars rows
    persist_rows: list[dict] = []
    for r in all_rows:
        try:
            # NSE returns timestamps as "DD-MMM-YYYY"
            ts = datetime.strptime(r["EOD_TIMESTAMP"], "%d-%b-%Y")
            persist_rows.append({
                "symbol":   info["symbol"],
                "timeframe": "ONE_DAY",
                "ts":       ts,
                "open":     float(r.get("EOD_OPEN_INDEX_VAL")  or 0),
                "high":     float(r.get("EOD_HIGH_INDEX_VAL")  or 0),
                "low":      float(r.get("EOD_LOW_INDEX_VAL")   or 0),
                "close":    float(r.get("EOD_CLOSE_INDEX_VAL") or 0),
                "volume":   0.0,                                  # NSE index data has no volume
                "source":   "nse_indices",
            })
        except Exception as e:
            logger.debug("nse parse row failed: {} ({})", e, r)

    inserted = 0
    if persist_rows:
        with SessionLocal() as sess:
            inserted = _upsert(sess, persist_rows)
            sess.commit()

    return {
        "index": nse_index_name,
        "stored_as_symbol": info["symbol"],
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "scraped_rows": len(all_rows),
        "inserted_rows": inserted,
        "chunk_errors": chunk_errors,
    }


# ---------------------------------------------------------------------------
# Path 2 — CSV importer (manually downloaded from NSE)
# ---------------------------------------------------------------------------

def import_csv(csv_text: str, symbol: str, source_label: str = "nse_csv") -> dict:
    """Parse an NSE-format CSV (as downloaded from the historical-data UI)
    and persist into ohlcv_bars.

    Accepted CSV formats (NSE varies them over time):
      • Date, Open, High, Low, Close, Shares Traded, Turnover
      • Date, Open, High, Low, Close       (some index CSVs lack volume)
    Dates accepted: "DD-Mon-YYYY", "DD/MM/YYYY", "YYYY-MM-DD".
    """
    rows: list[dict] = []
    skipped = 0

    reader = csv.DictReader(io.StringIO(csv_text))
    # Normalise headers — NSE uses inconsistent capitalisation / spacing
    field_map: dict[str, str] = {}
    if reader.fieldnames:
        for f in reader.fieldnames:
            fn = f.strip().lower()
            if fn in ("date", "trade date"):                 field_map["date"]   = f
            elif fn in ("open", "open index value"):         field_map["open"]   = f
            elif fn in ("high", "high index value"):         field_map["high"]   = f
            elif fn in ("low",  "low index value"):          field_map["low"]    = f
            elif fn in ("close", "close index value"):       field_map["close"]  = f
            elif fn in ("shares traded", "volume"):          field_map["volume"] = f

    required = {"date", "open", "high", "low", "close"}
    if not required.issubset(field_map.keys()):
        return {"error": f"CSV missing required columns. Need {required}, "
                          f"got headers {reader.fieldnames}"}

    for r in reader:
        try:
            ts_raw = r[field_map["date"]].strip()
            ts = _parse_date(ts_raw)
            if ts is None:
                skipped += 1
                continue
            rows.append({
                "symbol":   symbol.upper(),
                "timeframe": "ONE_DAY",
                "ts":       ts,
                "open":     _to_float(r[field_map["open"]]),
                "high":     _to_float(r[field_map["high"]]),
                "low":      _to_float(r[field_map["low"]]),
                "close":    _to_float(r[field_map["close"]]),
                "volume":   _to_float(r.get(field_map.get("volume", ""), "0") or "0"),
                "source":   source_label,
            })
        except Exception:
            skipped += 1

    inserted = 0
    if rows:
        with SessionLocal() as sess:
            inserted = _upsert(sess, rows)
            sess.commit()

    return {
        "symbol": symbol.upper(),
        "rows_parsed": len(rows),
        "rows_skipped": skipped,
        "rows_inserted": inserted,
        "earliest": min((r["ts"] for r in rows), default=None).isoformat() if rows else None,
        "latest":   max((r["ts"] for r in rows), default=None).isoformat() if rows else None,
    }


def _parse_date(s: str) -> datetime | None:
    formats = ["%d-%b-%Y", "%d-%B-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _to_float(s) -> float:
    if s is None:
        return 0.0
    try:
        return float(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Bulk scrape (multiple indices)
# ---------------------------------------------------------------------------

def scrape_all_indices(days_back: int = 365,
                        only_categories: list[str] | None = None) -> dict:
    """Scrape every known NSE index (or a subset by category)."""
    targets = NSE_INDEX_MAP.items()
    if only_categories:
        targets = [(k, v) for k, v in targets if v["category"] in only_categories]

    results = []
    for name, _info in targets:
        try:
            res = scrape_index(name, days_back=days_back)
            results.append(res)
        except Exception as e:
            results.append({"index": name, "error": str(e)})
    return {
        "scraped_count": len(results),
        "total_inserted": sum(r.get("inserted_rows", 0) for r in results),
        "results": results,
    }
