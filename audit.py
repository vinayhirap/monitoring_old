"""MarketLens full audit - hits every API route over HTTP and scores accuracy.

Run from D:\\Project\\monitoring_old (backend must be running):
    backend\\.venv\\Scripts\\python.exe audit.py                  # safe: GETs + read-only POSTs
    backend\\.venv\\Scripts\\python.exe audit.py --deep           # also runs ML train + backfill (slow)
Login: set env ML_EMAIL / ML_PASSWORD, or you will be prompted.
Never calls order / payment / telegram / twitter / delete routes.
"""
import argparse, datetime as dt, getpass, json, math, os, sys, time
import httpx

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://localhost:8000")
ap.add_argument("--deep", action="store_true")
ap.add_argument("--timeout", type=int, default=150)
args = ap.parse_args()
BASE = args.base.rstrip("/")
TODAY = dt.date.today().isoformat()
NOW = dt.datetime.now().isoformat(timespec="seconds")

def hr(t): print("\n" + "=" * 8, t, "=" * 8)
c = httpx.Client(base_url=BASE, timeout=args.timeout)
report = {"asof": NOW, "routes": [], "checks": [], "accuracy": []}

def short(r):
    try:
        j = r.json(); d = j.get("detail", j) if isinstance(j, dict) else j
        return (json.dumps(d) if not isinstance(d, str) else d)[:110]
    except Exception:
        return r.text[:110].replace("\n", " ")

# ---------------------------------------------------------------- 1. health
hr("1. BACKEND HEALTH")
try:
    h = c.get("/api/health", params={"detailed": "true"}).json()
    print("status:", h.get("status"))
    for k, v in (h.get("subsystems") or {}).items():
        print(f"  {k:14s} ok={v.get('ok')}  {({x:y for x,y in v.items() if x!='ok'})}")
except Exception as e:
    print("BACKEND NOT REACHABLE:", e); sys.exit(2)

# ---------------------------------------------------------------- 2. login
hr("2. LOGIN")
email = os.getenv("ML_EMAIL") or input("MarketLens login email: ").strip()
pw = os.getenv("ML_PASSWORD") or getpass.getpass("MarketLens password: ")
tok = None
r = c.post("/api/auth/login", data={"username": email, "password": pw})
if r.status_code == 200:
    tok = r.json()["access_token"]; c.headers["Authorization"] = f"Bearer {tok}"
    print("login OK, role:", r.json().get("user", {}).get("role"))
else:
    print("LOGIN FAILED", r.status_code, short(r), "-> continuing unauthenticated (many routes will 401)")

# ---------------------------------------------------------------- 3. broker / mode
hr("3. BROKER + MODE")
b = c.get("/api/broker/status").json()
print(json.dumps(b))
if not b.get("authenticated"): print("!! broker NOT authenticated -> data is synthetic/stale")
if b.get("paper_mode"): print("!! PAPER MODE is ON")

# ---------------------------------------------------------------- 4. route sweep
hr("4. ROUTE SWEEP (every route in /openapi.json)")
spec = c.get("/openapi.json").json()
SKIP_WORDS = ("order", "payment", "razorpay", "telegram", "twitter", "logout", "disconnect",
              "totp-now", "delete", "/ws", "execute", "square-off", "squareoff", "webhook",
              "signup", "password", "invite", "bulk", "/me/connect", "subscribe", "checkout")
SAMPLE = {"symbol": "RELIANCE", "ticker": "RELIANCE", "sym": "RELIANCE", "symbols": "NIFTY,RELIANCE",
          "q": "RELI", "query": "RELI", "exchange": "NSE", "horizon": "SWING", "interval": "ONE_DAY",
          "price": 24986, "spot": 24986, "days": 30, "limit": 10, "lookback": 180, "min_conf": 65,
          "min_confidence": 65, "quick": "true", "periods": 100, "anchor_date": TODAY, "date": TODAY,
          "asof": NOW, "capital": 100000, "timeframe": "ONE_DAY", "name": "nifty50", "universe": "nifty50",
          "expiry": TODAY, "levels": 8, "n": 10, "top": 10}
POST_OK = {
    "/api/gann/square9": {"price": 24986, "levels": 8},
    "/api/gann/time-cycles": {"anchor_date": TODAY},
    "/api/exit/evaluate": {"symbol": "RELIANCE", "side": "LONG", "entry_price": 1300, "qty": 10,
                           "entry_date": (dt.date.today() - dt.timedelta(days=7)).isoformat(),
                           "current_stop": 1250, "trail_atr_mult": 1.5, "profit_target_atr_mult": 4, "max_days": 30},
    "/api/analysis/full": {"symbol": "RELIANCE", "exchange": "NSE", "horizon": "SWING", "capital": 100000},
}
if args.deep:
    POST_OK["/api/ml/train"] = {"history_bars": 400, "horizon_bars": 5}

def fill(path, params):
    q = {}
    for p in params:
        n = p["name"]; s = p.get("schema", {})
        if p["in"] == "path":
            path = path.replace("{" + n + "}", "1" if s.get("type") == "integer" else ("GOLD" if "/commodities/" in path else str(SAMPLE.get(n, "RELIANCE"))))
        elif p.get("required"):
            v = s.get("default", SAMPLE.get(n))
            if v is None:
                v = {"integer": 10, "number": 100, "boolean": "false"}.get(s.get("type"), "NIFTY")
            q[n] = v
    return path, q

rows = []
for path, ops in sorted(spec["paths"].items()):
    for method, op in ops.items():
        method = method.upper()
        if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"): continue
        tag = f"{method:4s} {path}"
        if any(w in path.lower() for w in SKIP_WORDS):
            rows.append((tag, "SKIP", 0, "dangerous/mutating by design")); continue
        body = None
        if method != "GET":
            if path in POST_OK: body = POST_OK[path]
            elif path == "/api/backfill/run" and args.deep:
                body = None
            else:
                rows.append((tag, "SKIP", 0, "mutating - not auto-tested")); continue
        p2, q = fill(path, op.get("parameters", []))
        if path == "/api/backfill/run": q = {"symbols": "NIFTY,RELIANCE"}
        t0 = time.time()
        try:
            r = c.request(method, p2, params=q, json=body)
            ms = int((time.time() - t0) * 1000); sc = r.status_code
            if 200 <= sc < 300: st = "OK"
            elif sc in (402, 403): st = "GATED"
            elif sc == 401: st = "AUTH"
            elif sc in (400, 404, 405, 422): st = "PARAM?"
            elif sc == 409: st = "SETUP"
            elif sc == 429: st = "RATE"
            elif sc == 503: st = "NO-LIVE-DATA"
            else: st = "FAIL"
            rows.append((tag, st, ms, "" if st == "OK" else f"{sc} {short(r)}"))
        except Exception as e:
            rows.append((tag, "FAIL", int((time.time() - t0) * 1000), f"{type(e).__name__}: {e}"[:110]))

order = {"SETUP": 4, "FAIL": 0, "NO-LIVE-DATA": 1, "AUTH": 2, "PARAM?": 3, "RATE": 4, "GATED": 5, "SKIP": 6, "OK": 7}
for tag, st, ms, note in sorted(rows, key=lambda x: order[x[1]]):
    if st != "OK": print(f"[{st:12s}] {ms:6d}ms {tag}  {note}")
cnt = {}
for r_ in rows: cnt[r_[1]] = cnt.get(r_[1], 0) + 1
slow = [(t, m) for t, s, m, _ in rows if s == "OK" and m > 8000]
print("\nSUMMARY:", cnt, "| total routes:", len(rows))
if slow: print("SLOW (>8s):", slow)
report["routes"] = rows

# ---------------------------------------------------------------- 5. data truth
hr("5. PRICE INTEGRITY (candle vs broker LTP, per symbol)")
bad = 0
for s in ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN",
          "ITC", "LT", "AXISBANK", "KOTAKBANK", "BHARTIARTL", "HCLTECH", "DIVISLAB", "DLF", "MARUTI", "TITAN"]:
    ex = "BSE" if s == "SENSEX" else "NSE"
    r = c.get(f"/api/market/diagnose/{s}", params={"exchange": ex})
    if r.status_code != 200: print(f"  {s:11s} diagnose -> {r.status_code} {short(r)}"); bad += 1; continue
    j = r.json(); st4 = [x for x in j.get("steps", []) if x["step"].startswith("4")]
    d = (st4[0]["details"] if st4 else {}) or {}
    ok = j.get("overall_ok")
    if not ok: bad += 1
    print(f"  {s:11s} ok={ok!s:5s} token={d.get('instrument_token')} candle={d.get('candle_close')} "
          f"ltp={d.get('broker_ltp')} diff%={d.get('discrepancy_pct')} age_d={d.get('last_bar_age_days')}")
print("symbols with integrity problems:", bad)

# ---------------------------------------------------------------- 6. accuracy
hr("6. ACCURACY - is there a measurable edge?")
def wilson(k, n, z=1.96):
    if n == 0: return (0, 0)
    p = k / n; d = 1 + z * z / n
    ctr = (p + z * z / (2 * n)) / d; w = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (ctr - w, ctr + w)
def binom_p(k, n):  # exact two-sided vs p=0.5
    if n == 0: return 1.0
    pk = [math.comb(n, i) / 2 ** n for i in range(n + 1)]
    return min(1.0, sum(x for x in pk if x <= pk[k] + 1e-15))
def judge(name, k, n):
    lo, hi = wilson(k, n); p = binom_p(k, n)
    if n < 30: v = "INCONCLUSIVE (n<30)"
    elif p >= 0.05: v = "NO PROVEN EDGE (indistinguishable from coin flip)"
    elif k / n > 0.5: v = "STATISTICALLY ABOVE 50% (still check costs/regime)"
    else: v = "STATISTICALLY BELOW 50% (worse than random)"
    print(f"  {name:34s} {k}/{n} = {100*k/max(n,1):5.1f}%  95%CI [{100*lo:4.1f},{100*hi:4.1f}]  p={p:.3f}  -> {v}")
    report["accuracy"].append({"name": name, "k": k, "n": n, "p": p, "verdict": v})

for s in ("NIFTY", "BANKNIFTY", "RELIANCE", "TCS"):
    r = c.get(f"/api/astro-lab/measure/{s}")
    if r.status_code == 200:
        j = r.json(); judge(f"astro-only direction {s}", j.get("n_correct", 0), j.get("n_predictions", 0))
    r = c.get(f"/api/calibration/quick/{s}")
    if r.status_code == 200:
        j = r.json(); n = j.get("n_predictions", 0); acc = j.get("overall_accuracy", 0)
        acc = acc / 100 if acc > 1 else acc
        judge(f"engine direction (calib) {s}", round(acc * n), n)
        print(f"      brier={j.get('brier_score')} (0.25=coin flip; lower better)  calibrated={j.get('is_calibrated')}  "
              f"rating={j.get('rating')}  overconfidence_pp={j.get('avg_overconfidence_pp')}")
    r = c.get(f"/api/backtest/run/{s}", params={"lookback": 250, "min_conf": 65})
    if r.status_code == 200:
        j = r.json(); w, l = j.get("wins", 0), j.get("losses", 0)
        judge(f"backtest T1-before-SL {s}", w, w + l)
        print(f"      trades={j.get('total_trades')} PF={j.get('profit_factor')} expectancy%={j.get('expectancy_pct')} "
              f"maxDD%={j.get('max_drawdown_pct')}  (no slippage/brokerage/tax modelled)")
r = c.get("/api/astro-lab/per-engine/NIFTY")
if r.status_code == 200:
    print("  per-engine hit-rates on NIFTY (150 bars):")
    for e in r.json().get("engine_hit_rates_sorted", []):
        judge(f"   engine {e.get('engine')}", e.get("n_correct", 0), e.get("n_predictions", 0))

hr("DONE")
print("Full table saved to audit_report.json")
json.dump(report, open("audit_report.json", "w"), indent=1, default=str)
