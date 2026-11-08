# check_fallback_tokens.py -- run from D:\Project\monitoring_old
# Validates every _eq("token","SYMBOL") in instruments.py against the live Angel One scrip master.
# Default: report only. --apply: fix wrong tokens in place (missing symbols are only reported).
import json, re, sys, pathlib, urllib.request as u

APPLY = "--apply" in sys.argv
ROOT = pathlib.Path(__file__).resolve().parent
P = ROOT / "backend/app/services/instruments.py"
URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"

d = json.load(u.urlopen(URL, timeout=120))
sym2tok = {x["symbol"][:-3]: x["token"] for x in d if x["exch_seg"] == "NSE" and x["symbol"].endswith("-EQ")}
tok2sym = {v: k for k, v in sym2tok.items()}

src = P.read_text(encoding="utf-8")
pat = re.compile(r'_eq\(\s*"(\d+)"\s*,\s*"([^"]+)"\s*\)')

ok = wrong = missing = 0
fixes = {}
for m in pat.finditer(src):
    tok, sym = m.group(1), m.group(2)
    live = sym2tok.get(sym)
    if live is None:
        missing += 1
        print(f"  MISSING     {sym:<14} token={tok:<7} (not in NSE-EQ master; token now maps to {tok2sym.get(tok, '?')})")
    elif live != tok:
        wrong += 1
        fixes[(tok, sym)] = live
        print(f"  WRONG TOKEN {sym:<14} file={tok:<7} live={live}")
    else:
        ok += 1

print(f"\nOK={ok}  WRONG={wrong}  MISSING={missing}")

if APPLY and fixes:
    def rep(m):
        key = (m.group(1), m.group(2))
        if key in fixes:
            return m.group(0).replace(f'"{key[0]}"', f'"{fixes[key]}"', 1)
        return m.group(0)
    P.write_text(pat.sub(rep, src), encoding="utf-8", newline="")
    print(f"Wrote {len(fixes)} token fix(es). MISSING symbols need manual edits (renamed/merged/delisted).")
elif fixes:
    print("Report only. Re-run with --apply to fix the WRONG TOKEN lines.")
