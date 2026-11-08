# edge_lab.py -- honest walk-forward test: is there a real, tradable edge after costs?
#
# Usage (from D:\Project\monitoring_old, inside the backend venv):
#   backend\.venv\Scripts\python.exe -m pip install yfinance scikit-learn pandas numpy
#   backend\.venv\Scripts\python.exe edge_lab.py                  # default NSE symbols, 10y daily
#   backend\.venv\Scripts\python.exe edge_lab.py --symbols ^NSEI RELIANCE.NS --cost-bps 8
#   backend\.venv\Scripts\python.exe edge_lab.py --csv nifty.csv  # columns: date,open,high,low,close[,volume]
#   backend\.venv\Scripts\python.exe edge_lab.py --synthetic      # self-test of the harness
#
# Rules that keep it honest:
#   * features at day t use data up to close of t only; target is the sign of day t+1 return
#   * walk-forward (expanding window, refit every N days); scaler fit on train only
#   * costs charged on every position change
#   * verdict needs enough trades, a CI above 50%, p below a multiple-testing threshold
#     AND positive net return after costs. Anything else = NO PROVEN EDGE.
import argparse, math, sys
import numpy as np
import pandas as pd

DEFAULT_SYMBOLS = ["^NSEI", "^NSEBANK", "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS"]


# ----------------------------------------------------------------- data
def load_yf(sym, years):
    import yfinance as yf
    df = yf.download(sym, period=f"{years}y", interval="1d", auto_adjust=True, progress=False)
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)
    return df[["open", "high", "low", "close"] + (["volume"] if "volume" in df else [])].dropna()


def load_csv(path):
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index().dropna()


def synthetic(kind, n=2500, seed=1):
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0004, 0.01, n)
    if kind == "edge":                       # planted weak momentum: next day follows 5d trend
        for i in range(5, n):
            r[i] += 0.0035 * np.sign(r[i - 5:i].sum())
    close = 100 * np.exp(np.cumsum(r))
    idx = pd.bdate_range("2015-01-01", periods=n)
    hi = close * (1 + np.abs(rng.normal(0, 0.004, n)))
    lo = close * (1 - np.abs(rng.normal(0, 0.004, n)))
    op = np.r_[close[0], close[:-1]]
    return pd.DataFrame({"open": op, "high": hi, "low": lo, "close": close}, index=idx)


# ----------------------------------------------------------------- features
def rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def make_features(df):
    c = df["close"]
    r1 = c.pct_change()
    f = pd.DataFrame(index=df.index)
    f["ret1"] = r1
    f["ret5"] = c.pct_change(5)
    f["ret10"] = c.pct_change(10)
    f["ret20"] = c.pct_change(20)
    f["sma20_50"] = c.rolling(20).mean() / c.rolling(50).mean() - 1
    f["dist_sma50"] = c / c.rolling(50).mean() - 1
    f["rsi14"] = rsi(c) / 100 - 0.5
    f["range"] = (df["high"] - df["low"]) / c
    f["vol20"] = r1.rolling(20).std()
    f["vol_ratio"] = r1.rolling(5).std() / r1.rolling(60).std()
    f = f.replace([np.inf, -np.inf], np.nan)
    nxt = c.pct_change().shift(-1)           # next-day return (target)
    return f, nxt


# ----------------------------------------------------------------- stats
def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    a = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - a) / d, (c + a) / d


def binom_p(k, n):
    """Two-sided p vs 50% (normal approx with continuity correction)."""
    if n == 0:
        return 1.0
    z = (abs(k - n / 2) - 0.5) / math.sqrt(n / 4)
    return math.erfc(max(z, 0) / math.sqrt(2))


def max_dd(eq):
    peak = np.maximum.accumulate(eq)
    return float(((eq - peak) / peak).min())


# ----------------------------------------------------------------- walk-forward
def walk_forward(df, cost_bps, thr, refit, min_train):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    F, nxt = make_features(df)
    data = F.copy()
    data["nxt"] = nxt
    data = data.dropna(subset=list(F.columns))
    X_all = data[F.columns].values
    ret_next = data["nxt"].values
    y_all = (ret_next > 0).astype(int)
    valid = ~np.isnan(ret_next)                      # last row has no next-day return
    n = len(data)
    prob = np.full(n, np.nan)
    i = min_train
    while i < n:
        j = min(i + refit, n)
        tr = np.arange(0, i)[valid[:i]]
        if len(tr) < min_train * 0.8 or len(np.unique(y_all[tr])) < 2:
            i = j
            continue
        sc = StandardScaler().fit(X_all[tr])
        m = LogisticRegression(C=0.1, max_iter=500).fit(sc.transform(X_all[tr]), y_all[tr])
        prob[i:j] = m.predict_proba(sc.transform(X_all[i:j]))[:, 1]
        i = j
    out = pd.DataFrame({"prob": prob, "ret": ret_next, "y": y_all}, index=data.index)
    out = out[valid & ~np.isnan(prob)]
    out["mom20"] = np.sign(data.loc[out.index, "ret20"])      # simple baselines
    out["rev1"] = -np.sign(data.loc[out.index, "ret1"])
    return out


def evaluate(pos, ret, y, cost_bps):
    pos = np.asarray(pos, float)
    prev = np.r_[0.0, pos[:-1]]
    cost = np.abs(pos - prev) * cost_bps / 1e4
    net = pos * ret - cost
    traded = pos != 0
    n = int(traded.sum())
    hit = int(((pos[traded] > 0) == (y[traded] == 1)).sum()) if n else 0
    lo, hi = wilson(hit, n)
    eq = np.cumprod(1 + net)
    sharpe = float(net.mean() / net.std() * math.sqrt(252)) if net.std() > 0 else 0.0
    return dict(n=n, hit=hit, rate=(hit / n if n else 0.0), lo=lo, hi=hi, p=binom_p(hit, n),
                net_total=float(eq[-1] - 1) if len(eq) else 0.0, sharpe=sharpe,
                dd=max_dd(eq) if len(eq) else 0.0, gross_mean_bps=float((pos * ret).mean() * 1e4))


def verdict(r, alpha):
    if r["n"] < 100:
        return "INCONCLUSIVE (n<100)"
    if r["lo"] > 0.5 and r["p"] < alpha and r["net_total"] > 0 and r["sharpe"] > 0.5:
        return "POSSIBLE EDGE (needs paper-trade confirmation)"
    return "NO PROVEN EDGE"


def fmt(name, r, alpha):
    return (f"   {name:<22} n={r['n']:<5} hit={r['rate']*100:5.1f}%  CI[{r['lo']*100:4.1f},{r['hi']*100:4.1f}]  "
            f"p={r['p']:.3f}  net={r['net_total']*100:7.1f}%  sharpe={r['sharpe']:5.2f}  "
            f"maxDD={r['dd']*100:6.1f}%  -> {verdict(r, alpha)}")


def run_symbol(sym, df, a, k_tests):
    wf = walk_forward(df, a.cost_bps, a.thr, a.refit, a.min_train)
    if len(wf) < 200:
        print(f"\n{sym}: not enough data ({len(wf)} out-of-sample days)")
        return
    alpha = 0.05 / k_tests                           # Bonferroni across everything tested
    ret, y, p = wf["ret"].values, wf["y"].values, wf["prob"].values
    print(f"\n=== {sym}  out-of-sample days={len(wf)}  ({wf.index[0].date()} -> {wf.index[-1].date()}) ===")
    bh = np.cumprod(1 + ret)[-1] - 1
    print(f"   buy&hold over same days: {bh*100:.1f}%")
    brier = float(np.mean((p - y) ** 2))
    print(f"   model Brier={brier:.4f} (0.25 = coin flip, lower is better)")
    pos_all = np.where(p > 0.5, 1.0, -1.0)
    print(fmt("model long/short all", evaluate(pos_all, ret, y, a.cost_bps), alpha))
    pos_thr = np.where(p > 0.5 + a.thr, 1.0, np.where(p < 0.5 - a.thr, -1.0, 0.0))
    print(fmt(f"model only conf>{a.thr:.2f}", evaluate(pos_thr, ret, y, a.cost_bps), alpha))
    print(fmt("baseline momentum 20d", evaluate(wf["mom20"].values, ret, y, a.cost_bps), alpha))
    print(fmt("baseline reversion 1d", evaluate(wf["rev1"].values, ret, y, a.cost_bps), alpha))
    conf = np.abs(p - 0.5)
    q = np.quantile(conf, [0, 0.5, 0.8, 1.0])
    print("   accuracy by confidence (does higher confidence mean higher hit rate?):")
    for lo_q, hi_q, lab in ((q[0], q[1], "lowest 50%"), (q[1], q[2], "middle 30%"), (q[2], q[3] + 1e-9, "top 20%")):
        m = (conf >= lo_q) & (conf < hi_q)
        k = int((((p[m] > 0.5) == (y[m] == 1))).sum())
        nn = int(m.sum())
        lo, hi = wilson(k, nn)
        print(f"      {lab:<11} n={nn:<5} hit={k/max(nn,1)*100:5.1f}%  CI[{lo*100:4.1f},{hi*100:4.1f}]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS)
    ap.add_argument("--years", type=int, default=10)
    ap.add_argument("--csv")
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--cost-bps", type=float, default=5.0, help="cost per unit position change, bps")
    ap.add_argument("--thr", type=float, default=0.03, help="min |prob-0.5| to take a trade")
    ap.add_argument("--refit", type=int, default=63)
    ap.add_argument("--min-train", type=int, default=750)
    a = ap.parse_args()

    sets = []
    if a.synthetic:
        sets = [("SYNTH-RANDOM (no edge)", synthetic("random", seed=1)),
                ("SYNTH-PLANTED (has edge)", synthetic("edge", seed=2))]
    elif a.csv:
        sets = [(a.csv, load_csv(a.csv))]
    else:
        for s in a.symbols:
            try:
                df = load_yf(s, a.years)
            except Exception as e:
                print(f"{s}: download failed ({e})")
                continue
            if df is not None:
                sets.append((s, df))
    if not sets:
        sys.exit("No data loaded.")
    k_tests = max(1, len(sets) * 4)                  # 4 strategies per symbol
    print(f"cost={a.cost_bps} bps/position change, conf threshold={a.thr}, "
          f"multiple-testing alpha={0.05/k_tests:.4f}")
    for name, df in sets:
        run_symbol(name, df, a, k_tests)
    print("\nREAD THIS: 'POSSIBLE EDGE' is a hypothesis, not proof. Confirm on paper for 2-3 months.")
    print("Not financial advice. Past results do not guarantee future returns.")


if __name__ == "__main__":
    main()
