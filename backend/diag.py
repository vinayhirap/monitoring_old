import json, os
from app.services import instruments as I
print("token_for:", I.token_for("NIFTY", "NSE"))
print("lookup   :", I.lookup("NIFTY", "NSE"))
rows = json.load(open(os.path.expanduser("~/.cache/marketlens/angelone_scrip_master.json"), encoding="utf-8"))
for x in rows:
    if x["exch_seg"] == "NSE" and x["symbol"].upper() in ("NIFTY", "NIFTY 50") or x["name"].upper() in ("NIFTY", "NIFTY 50") and x["exch_seg"] == "NSE":
        print(x)
