# download_intraday.py -- pull intraday candle history from Angel One into a SEPARATE db (intraday_bars.db)
# so intraday_lab.py has enough data. Does not touch marketlens.db.
#
# Run from D:\Project\monitoring_old, with the backend STOPPED (avoids session clashes):
#   backend\.venv\Scripts\python.exe download_intraday.py                         # NIFTY+BANKNIFTY 5-min, 2 years
#   backend\.venv\Scripts\python.exe download_intraday.py --symbols NIFTY --years 1
#   backend\.venv\Scripts\python.exe download_intraday.py --interval FIFTEEN_MINUTE
#   backend\.venv\Scripts\python.exe download_intraday.py --selftest              # offline test, no login
# Then:
#   backend\.venv\Scripts\python.exe intraday_lab.py --db intraday_bars.db
#
# Credentials are read from backend\.env (ANGELONE_API_KEY, ANGELONE_CLIENT_CODE, ANGELONE_PASSWORD,
# ANGELONE_TOTP_SECRET). They are never printed; log redaction is loaded before SmartApi.
import argparse, importlib.util, os, pathlib, sqlite3, sys, time
from datetime import datetime, timedelta
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent
DB = ROOT / "intraday_bars.db"

INDEX = {  # symbol -> (exchange, token); tokens match your audit output
    "NIFTY": ("NSE", "99926000"),
    "BANKNIFTY": ("NSE", "99926009"),
    "FINNIFTY": ("NSE", "99926037"),
    "SENSEX": ("BSE", "99919000"),
}
CHUNK_DAYS = {"ONE_MINUTE": 25, "FIVE_MINUTE": 90, "FIFTEEN_MINUTE": 180, "THIRTY_MINUTE": 180, "ONE_HOUR": 360}


def load_redaction():
    p = ROOT / "backend" / "app" / "services" / "log_redact.py"
    if p.exists():
        spec = importlib.util.spec_from_file_location("log_redact_standalone", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)        # installs the filter on import


def read_env():
    env = {}
    for p in (ROOT / "backend" / ".env", ROOT / ".env"):
        if p.exists():
            for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def login(env):
    load_redaction()
    try:
        from SmartApi import SmartConnect
    except ImportError:
        from SmartApi.smartConnect import SmartConnect
    import pyotp
    need = ["ANGELONE_API_KEY", "ANGELONE_CLIENT_CODE", "ANGELONE_PASSWORD", "ANGELONE_TOTP_SECRET"]
    miss = [k for k in need if not env.get(k)]
    if miss:
        sys.exit(f"Missing in backend\\.env: {miss}")
    api = SmartConnect(api_key=env["ANGELONE_API_KEY"])
    r = api.generateSession(env["ANGELONE_CLIENT_CODE"], env["ANGELONE_PASSWORD"],
                            pyotp.TOTP(env["ANGELONE_TOTP_SECRET"]).now())
    if not r or not r.get("status"):
        sys.exit(f"Angel One login failed: {(r or {}).get('message', 'no response')}")
    print("Angel One login OK")
    return api


def resolve(symbol):
    if symbol.upper() in INDEX:
        return INDEX[symbol.upper()]
    import json, urllib.request as u
    d = json.load(u.urlopen("https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json", timeout=120))
    for x in d:
        if x["exch_seg"] == "NSE" and x["symbol"] == f"{symbol.upper()}-EQ":
            return "NSE", x["token"]
    sys.exit(f"Cannot resolve {symbol}")


def fetch(api, exch, token, interval, start, end, tries=4):
    params = {"exchange": exch, "symboltoken": token, "interval": interval,
              "fromdate": start.strftime("%Y-%m-%d %H:%M"), "todate": end.strftime("%Y-%m-%d %H:%M")}
    for k in range(tries):
        try:
            r = api.getCandleData(params)
            if r and r.get("status") and r.get("data"):
                return r["data"]
            if r and r.get("status"):
                return []
        except Exception:
            pass
        time.sleep(1.5 * (k + 1))
    return None  # failed after retries


def init_db():
    con = sqlite3.connect(DB)
    con.execute("""create table if not exists ohlcv_bars(
        symbol text, exchange text, interval text, timestamp text,
        open real, high real, low real, close real, volume real,
        primary key(symbol, exchange, interval, timestamp))""")
    return con


def save(con, symbol, exch, interval, rows):
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None).dt.strftime("%Y-%m-%d %H:%M:%S")
    recs = [(symbol, exch, interval, *r) for r in df.itertuples(index=False, name=None)]
    cur = con.executemany("insert or ignore into ohlcv_bars values(?,?,?,?,?,?,?,?,?)", recs)
    con.commit()
    return cur.rowcount


def download(api, symbols, interval, years, pause):
    con = init_db()
    chunk = CHUNK_DAYS.get(interval, 90)
    for sym in symbols:
        exch, token = resolve(sym)
        end = datetime.now()
        stop = end - timedelta(days=int(years * 365))
        empties, total = 0, 0
        print(f"\n{sym} {interval}: going back to {stop.date()} in {chunk}-day windows")
        while end > stop and empties < 3:
            start = max(end - timedelta(days=chunk), stop)
            rows = fetch(api, exch, token, interval, start, end)
            if rows is None:
                print(f"   {start.date()} -> {end.date()}: FAILED after retries (rate limit/timeouts) - stopping {sym}")
                break
            if rows:
                total += save(con, sym, exch, interval, rows)
                empties = 0
            else:
                empties += 1
            print(f"   {start.date()} -> {end.date()}: {len(rows)} bars")
            end = start - timedelta(minutes=1)
            time.sleep(pause)
        print(f"   {sym}: saved {total} new bars")
    con.close()


class FakeApi:   # offline self-test: 5-min sessions on weekdays
    def getCandleData(self, p):
        import numpy as np
        s = datetime.strptime(p["fromdate"], "%Y-%m-%d %H:%M")
        e = datetime.strptime(p["todate"], "%Y-%m-%d %H:%M")
        rows, d, px = [], s.replace(hour=0, minute=0), 20000.0
        rng = np.random.default_rng(int(s.timestamp()) % 1000)
        while d <= e:
            if d.weekday() < 5:
                t = d.replace(hour=9, minute=15)
                for _ in range(75):
                    o = px
                    px *= 1 + rng.normal(0, 0.0007)
                    rows.append([t.strftime("%Y-%m-%dT%H:%M:%S+05:30"), o, max(o, px), min(o, px), px, 0])
                    t += timedelta(minutes=5)
            d += timedelta(days=1)
        return {"status": True, "data": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=["NIFTY", "BANKNIFTY"])
    ap.add_argument("--interval", default="FIVE_MINUTE")
    ap.add_argument("--years", type=float, default=2.0)
    ap.add_argument("--pause", type=float, default=0.6, help="seconds between requests (rate limit)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        global DB
        DB = ROOT / "intraday_selftest.db"      # never mix fake data into the real db
        download(FakeApi(), a.symbols, a.interval, 0.25, 0.0)
    else:
        download(login(read_env()), a.symbols, a.interval, a.years, a.pause)
    print(f"\nDone. Now run:  backend\\.venv\\Scripts\\python.exe intraday_lab.py --db {DB.name}")


if __name__ == "__main__":
    main()
