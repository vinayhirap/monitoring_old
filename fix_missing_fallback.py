# fix_missing_fallback.py -- run from D:\Project\monitoring_old (dry run unless --apply)
import json, re, sys, pathlib, urllib.request as u

APPLY = "--apply" in sys.argv
ROOT = pathlib.Path(__file__).resolve().parent
P = ROOT / "backend/app/services/instruments.py"
URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"

# old symbol -> new symbols (None = remove; HDFC merged into HDFCBANK, ICICIPRULI not listed)
RENAMES = {
    "TATAMOTORS": ["TMPV", "TMCV"],
    "CADILAHC": ["ZYDUSLIFE"],
    "HDFC": None,
    "ICICIPRULI": None,
}

d = json.load(u.urlopen(URL, timeout=120))
tok = {x["symbol"][:-3]: x["token"] for x in d if x["exch_seg"] == "NSE" and x["symbol"].endswith("-EQ")}

s = P.read_text(encoding="utf-8")
total = 0
for old, new in RENAMES.items():
    pat = re.compile(r'_eq\(\s*"\d+"\s*,\s*"%s"\s*\)\s*,?[ \t]*' % re.escape(old))
    n = len(pat.findall(s))
    if not n:
        print(f"  NONE      {old}")
        continue
    if new is None:
        s = pat.sub("", s)
        print(f"  REMOVED   {old} x{n}")
    else:
        missing = [x for x in new if x not in tok]
        if missing:
            print(f"  SKIP      {old}: {missing} not in live master (edit manually)")
            continue
        rep = " ".join(f'_eq("{tok[x]}", "{x}"),' for x in new) + " "
        s = pat.sub(rep, s)
        print(f"  REPLACED  {old} x{n} -> {[(x, tok[x]) for x in new]}")
    total += n

if APPLY and total:
    P.write_text(s, encoding="utf-8", newline="")
print(f"\n{'Wrote' if APPLY else 'DRY RUN -'} {total} edit(s)." + ("" if APPLY else " Re-run with --apply."))
