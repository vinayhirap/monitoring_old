"""NSE historical-data import endpoints.

Two ingestion modes:

  • POST /api/nse/scrape/{index}      — direct fetch from nseindia.com (fragile)
  • POST /api/nse/import-csv          — upload a manually downloaded CSV (reliable)
  • POST /api/nse/scrape-all          — bulk fetch every supported index
  • GET  /api/nse/indices             — list all supported NSE indices
"""
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query
from pydantic import BaseModel

from app.services import nse_importer

router = APIRouter()


@router.get("/indices", summary="List supported NSE indices with their internal symbols")
async def list_indices():
    return {
        "count": len(nse_importer.NSE_INDEX_MAP),
        "indices": [
            {"nse_name": name, **info}
            for name, info in nse_importer.NSE_INDEX_MAP.items()
        ],
        "note": (
            "Use the 'nse_name' string with the scrape endpoint. "
            "Data lands in ohlcv_bars table keyed by 'symbol'."
        ),
    }


@router.post(
    "/scrape/{nse_name:path}",
    summary="Scrape one index from nseindia.com (may fail from AWS IPs)",
)
async def scrape_one(
    nse_name: str,
    days_back: int = Query(365, ge=30, le=3650),
):
    """nse_name examples (URL-encode spaces as %20):
        NIFTY%2050
        NIFTY%20BANK
        NIFTY%20IT
        INDIA%20VIX

    If you get 'NSE blocked the request' → use the /import-csv endpoint with
    a manually-downloaded CSV instead.
    """
    try:
        res = nse_importer.scrape_index(nse_name, days_back=days_back)
        if "error" in res:
            raise HTTPException(400, res["error"])
        return res
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"NSE scrape failed: {e}")


@router.post(
    "/scrape-all",
    summary="Scrape all supported NSE indices (fragile from AWS — prefer /import-csv per index)",
)
async def scrape_all(
    days_back: int = Query(365, ge=30, le=3650),
    categories: str | None = Query(None, description="Comma-separated: broad,sectoral,smart-beta,volatility"),
):
    try:
        cats = [c.strip() for c in categories.split(",")] if categories else None
        return nse_importer.scrape_all_indices(days_back=days_back, only_categories=cats)
    except Exception as e:
        raise HTTPException(500, f"bulk scrape failed: {e}")


@router.post(
    "/import-csv",
    summary="Upload an NSE-format CSV and persist into ohlcv_bars (most reliable path)",
)
async def import_csv(
    file: UploadFile = File(..., description="CSV downloaded from nseindia.com historical-data page"),
    symbol: str = Form(..., description="Symbol to store as (e.g. NIFTY, BANKNIFTY)"),
):
    try:
        content = await file.read()
        text = content.decode("utf-8", errors="ignore")
        res = nse_importer.import_csv(text, symbol=symbol)
        if "error" in res:
            raise HTTPException(400, res["error"])
        return res
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"CSV import failed: {e}")
