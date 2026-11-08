"""Apply the 3 pieces of marketlens-fixes-3 that `git apply --3way` skipped.
Run from D:\\Project\\monitoring_old :   backend\\.venv\\Scripts\\python.exe apply_rest.py
Idempotent: safe to run twice. Preserves BOM and line endings."""
import re, pathlib, sys

root = pathlib.Path(__file__).resolve().parent

def rw(path, fn):
    p = root / path
    raw = p.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    crlf = "\r\n" in text
    text = text.replace("\r\n", "\n")
    new = fn(text)
    if new is None:
        return False
    if crlf: new = new.replace("\n", "\r\n")
    p.write_bytes((b"\xef\xbb\xbf" if bom else b"") + new.encode("utf-8"))
    return True

# 1. instruments.lookup: indices first
BLOCK = '''
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
'''
def f1(t):
    if "0. Known indices FIRST" in t:
        print("instruments.py: already patched"); return None
    m = re.search(r"(def lookup\(.*?\n)(.*?)(    sym = symbol\.upper\(\)\.strip\(\)\n)", t, re.S)
    if not m:
        print("instruments.py: ANCHOR NOT FOUND - send me the lookup() function"); sys.exit(1)
    i = m.end()
    print("instruments.py: patched"); return t[:i] + BLOCK + t[i:]
rw("backend/app/services/instruments.py", f1)

# 2. Star import
def f2(t):
    m = re.search(r"import\s*\{([^}]*)\}\s*from\s*[\"']lucide-react[\"']", t)
    if not m: print("SimpleRecommendation: no lucide import found"); sys.exit(1)
    if re.search(r"\bStar\b", m.group(1)):
        print("SimpleRecommendation: already has Star"); return None
    body = m.group(1).rstrip()
    if not body.endswith(","): body += ","
    new = m.group(0).replace(m.group(1), body + " Star,\n")
    print("SimpleRecommendation: patched"); return t.replace(m.group(0), new, 1)
rw("frontend/components/SimpleRecommendation.tsx", f2)

# 3. purge script
sp = root / "backend/scripts/purge_bad_index_bars.py"
sp.parent.mkdir(exist_ok=True)
sp.write_text('''"""Delete cached index candles that were stored under the wrong token."""
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
''', encoding="utf-8")
print("purge_bad_index_bars.py: written")
