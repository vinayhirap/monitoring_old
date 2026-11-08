# intraday_lab.py -- honest walk-forward test on the INTRADAY bars already cached in your backend DB.
#
# Run from D:\Project\monitoring_old:
#   backend\.venv\Scripts\python.exe intraday_lab.py --list           # what bars do I have?
#   backend\.venv\Scripts\python.exe intraday_lab.py                  # test every symbol/interval with enough days
#   backend\.venv\Scripts\python.exe intraday_lab.py --symbols NIFTY CRUDEOIL --horizon 6 --cost-bps 3
#   backend\.venv\Scripts\python.exe intraday_lab.py --synthetic      # self-test of the harness
#
# Rules: features use only data up to the decision bar; target = return over the next H bars
# (same session only, flat overnight); expanding walk-forward refit by day; costs on every
# position change plus the end-of-day exit; verdict needs n>=200 trades, CI above 50%,
# p below a Bonferroni threshold, positive net return AND net Sharpe > 0.5.
import argparse, math, os, sqlite3, sys
import numpy as np
import pandas as pd

TS = ["timestamp", "ts", "datetime", "bar_time", "time", "date", "dt"]
SYM = ["symbol", "ticker"]
INT = ["interval", "timeframe", "tf"]
EXC = ["exchange", "exch"]


# ----------------------------------------------------------------- data
def pick(cols, cands):
    low = {c.lower(): c for c in cols}
    for c in cands:
        if c in low:
            return low[c]
    return None


def load_db(path):
    con = sqlite3.connect(path)
    names = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
    tbl = next((n for n in names if "ohlcv" in n.lower()), None)
    if not tbl:
        sys.exit(f"No ohlcv table in {path}. Tables: {names}")
    df = pd.read_sql_query(f"select * from {tbl}", con)
    con.close()
    cols = list(df.columns)
    m = {"ts": pick(cols, TS), "sym": pick(cols, SYM), "int": pick(cols, INT), "exc": pick(cols, EXC)}
    need = {k: pick(cols, [k]) for k in ("open", "high", "low", "close")}
    if not m["ts"] or not m["sym"] or None in need.values():
        sys.exit(f"Could not map columns of {tbl}: {cols}\nTell me these column names and I will adapt the script.")
    vol = pick(cols, ["volume", "vol"])
    t = df[m["ts"]]
    if pd.api.types.is_numeric_dtype(t):
        unit = "ms" if t.dropna().astype(float).abs().median() > 1e11 else "s"
        ts = pd.to_datetime(t, unit=unit, errors="coerce")
    else:
        ts = pd.to_datetime(t, errors="coerce")
    out = pd.DataFrame({
        "ts": ts,
        "symbol": df[m["sym"]].astype(str),
        "exchange": df[m["exc"]].astype(str) if m["exc"] else "",
        "interval": df[m["int"]].astype(str) if m["int"] else "UNKNOWN",
        "open": df[need["open"]].astype(float), "high": df[need["high"]].astype(float),
        "low": df[need["low"]].astype(float), "close": df[need["close"]].astype(float),
        "volume": df[vol].astype(float) if vol else 0.0,
    }).dropna(subset=["ts", "open", "high", "low", "close"])
    sets = {}
    for (s, e, i), g in out.groupby(["symbol", "exchange", "interval"]):
        g = g.drop_duplicates("ts").sort_values("ts").set_index("ts")
        sets[(s, e, i)] = g[["open", "high", "low", "close", "volume"]]
    return sets


def synthetic_sets(kind, days=320, bars=75, seed=1):
    rng = np.random.default_rng(seed)
    rows, drift = [], 0.0
    price = 20000.0
    for d in range(days):
        day = pd.Timestamp("2025-01-01") + pd.tseries.offsets.BDay(d)
        ts = pd.date_range(day + pd.Timedelta(hours=9, minutes=15), periods=bars, freq="5min")
        for t in ts:
            if kind == "edge":
                drift = 0.97 * drift + rng.normal(0, 0.00012)
            r = rng.normal(0, 0.0007) + (drift if kind == "edge" else 0.0)
            o = price
            price *= 1 + r
            rows.append((t, o, max(o, price) * 1.0002, min(o, price) * 0.9998, price, rng.integers(1000, 5000)))
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"]).set_index("ts")
    return {(f"SYNTH-{kind.upper()}", "NSE", "FIVE_MINUTE"): df}


# ----------------------------------------------------------------- features
def build(df, H):
    d = df.copy()
    d["day"] = d.index.normalize()
    g = d.groupby("day", sort=False)
    d["bar"] = g.cumcount()
    d["nbars"] = g["close"].transform("size")
    c = d["close"]
    f = pd.DataFrame(index=d.index)
    f["r1"] = g["close"].pct_change()
    for k in (3, 6, 12):
        f[f"r{k}"] = c / g["close"].shift(k) - 1
    first_open = g["open"].transform("first")
    prev_close = g["close"].last().shift(1)
    f["gap"] = d["day"].map(first_open.groupby(d["day"]).first() / prev_close - 1)
    f["day_ret"] = c / first_open - 1
    f["tod"] = d["bar"] / d["nbars"]
    f["range"] = (d["high"] - d["low"]) / c
    f["vol12"] = f["r1"].rolling(12).std()
    tp = (d["high"] + d["low"] + c) / 3
    w = d["volume"].where(d["volume"] > 0, 1.0)
    vwap = (tp * w).groupby(d["day"]).cumsum() / w.groupby(d["day"]).cumsum()
    f["dist_vwap"] = c / vwap - 1
    vm = d["volume"].rolling(20).mean()
    f["vol_ratio"] = (d["volume"] / vm).where(vm > 0, 1.0)
    f = f.replace([np.inf, -np.inf], np.nan)
    fwd = g["close"].shift(-H) / c - 1                    # NaN when it would cross the session end
    return d, f, fwd


# ----------------------------------------------------------------- stats
def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    dd = 1 + z * z / n
    cc = p + z * z / (2 * n)
    a = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (cc - a) / dd, (cc + a) / dd


def binom_p(k, n):
    if n == 0:
        return 1.0
    z = (abs(k - n / 2) - 0.5) / math.sqrt(n / 4)
    return math.erfc(max(z, 0) / math.sqrt(2))


def evaluate(dec, pos, cost_bps):
    x = dec[["day", "ret"]].copy()
    x["pos"] = pos
    x["prev"] = x.groupby("day")["pos"].shift(1).fillna(0.0)
    last = x.groupby("day").cumcount(ascending=False) == 0
    c = cost_bps / 1e4
    x["cost"] = (x["pos"] - x["prev"]).abs() * c + np.where(last, x["pos"].abs() * c, 0.0)
    x["net"] = x["pos"] * x["ret"] - x["cost"]
    tr = x["pos"] != 0
    n = int(tr.sum())
    hit = int(((x.loc[tr, "pos"] > 0) == (x.loc[tr, "ret"] > 0)).sum()) if n else 0
    lo, hi = wilson(hit, n)
    daily = x.groupby("day")["net"].sum()
    eq = (1 + daily).cumprod()
    sh = float(daily.mean() / daily.std() * math.sqrt(252)) if daily.std() > 0 else 0.0
    dd = float(((eq - eq.cummax()) / eq.cummax()).min()) if len(eq) else 0.0
    return dict(n=n, hit=hit, rate=hit / n if n else 0.0, lo=lo, hi=hi, p=binom_p(hit, n),
                net=float(eq.iloc[-1] - 1) if len(eq) else 0.0, sharpe=sh, dd=dd,
                gross_bps=float((x.loc[tr, "pos"] * x.loc[tr, "ret"]).mean() * 1e4) if n else 0.0,
                cost_bps=float(x.loc[tr, "cost"].mean() * 1e4) if n else 0.0)


def verdict(r, alpha):
    if r["n"] < 200:
        return "INCONCLUSIVE (n<200)"
    if r["lo"] > 0.5 and r["p"] < alpha and r["net"] > 0 and r["sharpe"] > 0.5:
        return "POSSIBLE EDGE (needs paper-trade confirmation)"
    return "NO PROVEN EDGE"


def fmt(name, r, alpha):
    return (f"   {name:<24} n={r['n']:<5} hit={r['rate']*100:5.1f}% CI[{r['lo']*100:4.1f},{r['hi']*100:4.1f}] "
            f"p={r['p']:.3f} gross={r['gross_bps']:5.1f}bps cost={r['cost_bps']:4.1f}bps "
            f"net={r['net']*100:7.1f}% sharpe={r['sharpe']:5.2f} maxDD={r['dd']*100:6.1f}% -> {verdict(r, alpha)}")


# ----------------------------------------------------------------- walk-forward
def run(key, df, a, k_tests):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    sym, exch, itv = key
    d, F, fwd = build(df, a.horizon)
    cols = list(F.columns)
    ok = F.notna().all(axis=1) & fwd.notna()
    X = F[ok].values
    ret = fwd[ok].values
    y = (ret > 0).astype(int)
    meta = d.loc[ok, ["day", "bar"]].reset_index(drop=True)
    days = np.array(sorted(meta["day"].unique()))
    if len(days) < a.min_days + a.refit_days:
        print(f"\n{sym} {itv}: only {len(days)} usable days (need >= {a.min_days + a.refit_days}) - skipped")
        return
    day_idx = meta["day"].map({dd: i for i, dd in enumerate(days)}).values
    prob = np.full(len(meta), np.nan)
    i = a.min_days
    while i < len(days):
        j = min(i + a.refit_days, len(days))
        tr = day_idx < i
        te = (day_idx >= i) & (day_idx < j)
        if len(np.unique(y[tr])) == 2 and te.any():
            sc = StandardScaler().fit(X[tr])
            m = LogisticRegression(C=0.05, max_iter=500).fit(sc.transform(X[tr]), y[tr])
            prob[te] = m.predict_proba(sc.transform(X[te]))[:, 1]
        i = j
    sel = ~np.isnan(prob) & (meta["bar"].values % a.horizon == 0)   # non-overlapping decisions
    dec = meta[sel].copy()
    dec["ret"] = ret[sel]
    p = prob[sel]
    yy = y[sel]
    mk_col = f"r{min((3, 6, 12), key=lambda k: abs(k - a.horizon))}"
    mom = np.sign(F.loc[ok, mk_col].values[sel])
    alpha = 0.05 / k_tests
    print(f"\n=== {sym} [{exch}] {itv}  days={len(days)}  OOS decisions={len(dec)}  "
          f"({dec['day'].min().date()} -> {dec['day'].max().date()})  horizon={a.horizon} bars ===")
    print(f"   Brier={float(np.mean((p - yy) ** 2)):.4f} (0.25 = coin flip)")
    print(fmt("model long/short all", evaluate(dec, np.where(p > 0.5, 1.0, -1.0), a.cost_bps), alpha))
    thr = np.where(p > 0.5 + a.thr, 1.0, np.where(p < 0.5 - a.thr, -1.0, 0.0))
    print(fmt(f"model only conf>{a.thr:.2f}", evaluate(dec, thr, a.cost_bps), alpha))
    print(fmt("baseline momentum", evaluate(dec, mom, a.cost_bps), alpha))
    print(fmt("baseline reversion", evaluate(dec, -mom, a.cost_bps), alpha))
    conf = np.abs(p - 0.5)
    q = np.quantile(conf, [0, 0.5, 0.8, 1.0])
    print("   accuracy by confidence:")
    for lo_q, hi_q, lab in ((q[0], q[1], "lowest 50%"), (q[1], q[2], "middle 30%"), (q[2], q[3] + 1e-9, "top 20%")):
        mk = (conf >= lo_q) & (conf < hi_q)
        k = int(((p[mk] > 0.5) == (yy[mk] == 1)).sum())
        nn = int(mk.sum())
        lo, hi = wilson(k, nn)
        print(f"      {lab:<11} n={nn:<5} hit={k/max(nn,1)*100:5.1f}% CI[{lo*100:4.1f},{hi*100:4.1f}]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join("backend", "marketlens.db"))
    ap.add_argument("--symbols", nargs="*")
    ap.add_argument("--intervals", nargs="*", default=["FIVE_MINUTE", "FIFTEEN_MINUTE"])
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--horizon", type=int, default=6, help="hold period in bars")
    ap.add_argument("--cost-bps", type=float, default=3.0, help="cost per unit position change, bps")
    ap.add_argument("--thr", type=float, default=0.03)
    ap.add_argument("--min-days", type=int, default=60)
    ap.add_argument("--refit-days", type=int, default=20)
    a = ap.parse_args()

    if a.synthetic:
        sets = {}
        sets.update(synthetic_sets("random", seed=1))
        sets.update(synthetic_sets("edge", seed=2))
    else:
        sets = load_db(a.db)

    print("Bars available (symbol, exchange, interval): days, bars, first -> last")
    for k, df in sorted(sets.items()):
        nd = df.index.normalize().nunique()
        print(f"   {k[0]:<14}{k[1]:<6}{k[2]:<16} days={nd:<5} bars={len(df):<7} {df.index[0]} -> {df.index[-1]}")
    if a.list:
        return

    todo = [(k, df) for k, df in sorted(sets.items())
            if (a.synthetic or k[2].upper() in [x.upper() for x in a.intervals])
            and (not a.symbols or k[0].upper() in [s.upper() for s in a.symbols])]
    if not todo:
        sys.exit("\nNothing to test with those filters (use --list, --intervals, --symbols).")
    k_tests = max(1, len(todo) * 4)
    print(f"\ncost={a.cost_bps} bps/position change, horizon={a.horizon} bars, "
          f"multiple-testing alpha={0.05/k_tests:.4f}")
    for k, df in todo:
        run(k, df, a, k_tests)
    print("\nREAD THIS: 'POSSIBLE EDGE' is a hypothesis, not proof. Confirm on paper for 2-3 months.")
    print("Not financial advice. Past results do not guarantee future returns.")


if __name__ == "__main__":
    main()
