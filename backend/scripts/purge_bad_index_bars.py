"""Delete cached index candles that were stored under the wrong token."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from sqlalchemy import delete
from app.database import SessionLocal
from app.models.ohlcv_bar import OHLCVBar
SYMS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"]
with SessionLocal() as db:
    res = db.execute(delete(OHLCVBar).where(OHLCVBar.symbol.in_(SYMS)))
    db.commit()
    print(f"Deleted {res.rowcount} cached index bars")
