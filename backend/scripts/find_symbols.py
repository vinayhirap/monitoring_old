import json, sys, urllib.request as u
URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
Q = {
    "ICICIPRULI": ["ICICI PRU", "ICICIPRU"],
    "LTIM": ["LTIMINDTREE", "LTIM", "LTM"],
    "TATAMOTORS": ["TATA MOTORS", "TATAMOTORS", "TMPV", "TMCV"],
}
d = json.load(u.urlopen(URL, timeout=120))
eq = [x for x in d if x["exch_seg"] == "NSE" and x["symbol"].endswith("-EQ")]
for old, keys in Q.items():
    print(f"\n== {old} ==")
    seen = set()
    for x in eq:
        hay = (x["symbol"] + " " + x.get("name", "")).upper()
        if any(k in hay for k in keys) and x["symbol"] not in seen:
            seen.add(x["symbol"])
            print(f"  {x['symbol']:<18} name={x.get('name','')!r:<28} token={x['token']}")
