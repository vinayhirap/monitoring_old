# vol_lab.py -- volatility IS predictable (direction is not). Walk-forward test of a HAR realized-vol
# forecast vs naive baselines, on the 5-minute bars in intraday_bars.db, plus tomorrow's expected move.
#
#   backend\.venv\Scripts\python.exe vol_lab.py                  # all symbols in intraday_bars.db
#   backend\.venv\Scripts\python.exe vol_lab.py --symbols NIFTY
#   backend\.venv\Scripts\python.exe vol_lab.py --synthetic      # self-test of the harness
#
# Use the output for stop distance, position size and option-strategy choice -- NOT as a buy/sell signal.
import argparse, math, os, sys
import numpy as np
import pandas as pd

Z80 = 1.2816


def daily_rv(df):
    d = df.copy()
    d["day"] = d.index.normalize()
    lr = np.log(d["close"]).groupby(d["day"]).diff()
    rv = (lr ** 2).groupby(d["day"]).sum()
    n = lr.groupby(d["day"]).count()
    keep = (n >= 0.6 * n.median()) & (rv > 0)
    return rv[keep], int(n.median())


def har_matrix(y):
    s = pd.Series(y.values)
    X = pd.DataFrame({
        "c": 1.0,
        "d": s,
        "w": s.rolling(5).mean(),
        "m": s.rolling(22).mean(),
    })
    tgt = s.shift(-1)
    return X, tgt


def fit(X, y):
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ beta
    return beta, float(np.std(res, ddof=X.shape[1]))


def qlike(true, pred):
    r = true / pred
    return float(np.mean(r - np.log(r) - 1))


def run(sym, df, a):
    rv, nbars = daily_rv(df)
    if len(rv) < a.min_days + 40:
        print(f"\n{sym}: only {len(rv)} usable days (need >= {a.min_days + 40}) - skipped")
        return
    y = np.log(rv)
    X, tgt = har_matrix(y)
    ok = X.notna().all(axis=1) & tgt.notna()
    idx = np.where(ok.values)[0]
    Xv, tv = X.values, tgt.values
    pm, pn, p20, pe, yt, ytr, cover = [], [], [], [], [], [], []
    i = a.min_days
    while i < len(idx):
        j = min(i + a.refit_days, len(idx))
        tr, te = idx[:i], idx[i:j]
        beta, sig = fit(Xv[tr], tv[tr])
        mu = Xv[te] @ beta
        bias = math.exp(0.5 * sig ** 2)
        pm += list(np.exp(mu) * bias)
        pn += list(np.exp(Xv[te, 1]))                       # naive: yesterday's RV
        p20 += list(np.exp(y.rolling(20).mean().values[te]))
        ew = np.exp(y).ewm(alpha=1 - 0.94).mean().values
        pe += list(ew[te])
        yt += list(np.exp(tv[te]))
        cover += list((tv[te] >= mu - Z80 * sig) & (tv[te] <= mu + Z80 * sig))
        i = j
    yt = np.array(yt)
    names = [("HAR model", np.array(pm)), ("naive (yesterday)", np.array(pn)),
             ("20-day average", np.array(p20)), ("EWMA 0.94", np.array(pe))]
    print(f"\n=== {sym}  days={len(rv)}  OOS days={len(yt)}  bars/day~{nbars} ===")
    base = qlike(yt, names[1][1])
    for nm, p in names:
        q = qlike(yt, p)
        mae = float(np.mean(np.abs(np.sqrt(yt) - np.sqrt(p))) * 1e4)
        print(f"   {nm:<20} QLIKE={q:6.3f} ({(1 - q / base) * 100:+5.1f}% vs naive)   MAE of daily sigma={mae:5.1f} bps")
    corr = float(np.corrcoef(np.log(yt), np.log(names[0][1]))[0, 1])
    print(f"   HAR corr(forecast, actual) in log-vol = {corr:.2f}   80% interval coverage = {np.mean(cover) * 100:.0f}% (target 80%)")
    # tomorrow's forecast from all data
    beta, sig = fit(Xv[idx], tv[idx])
    last = Xv[len(y) - 1]
    mu = float(last @ beta)
    daily = math.sqrt(math.exp(mu + 0.5 * sig ** 2)) * 1e4
    lo, hi = math.sqrt(math.exp(mu - Z80 * sig)) * 1e4, math.sqrt(math.exp(mu + Z80 * sig)) * 1e4
    h = a.horizon
    print(f"   NEXT SESSION (intraday move, close-to-close of bars): 1-sigma ~ {daily:.0f} bps, 80% range {lo:.0f}-{hi:.0f} bps")
    print(f"   1-sigma move over {h} bars ({h * 5} min) ~ {daily * math.sqrt(h / nbars):.1f} bps  -> use for stop distance & size")


def synthetic(days=400, bars=75, seed=3):
    rng = np.random.default_rng(seed)
    lv, rows, price = -9.3, [], 20000.0
    for d in range(days):
        lv = -9.3 + 0.9 * (lv + 9.3) + rng.normal(0, 0.18)
        sd = math.sqrt(math.exp(lv) / bars)
        day = pd.Timestamp("2025-01-01") + pd.tseries.offsets.BDay(d)
        for k, t in enumerate(pd.date_range(day + pd.Timedelta(hours=9, minutes=15), periods=bars, freq="5min")):
            o = price
            price *= 1 + rng.normal(0, sd)
            rows.append((t, o, max(o, price), min(o, price), price, 0))
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"]).set_index("ts")
    return {("SYNTH-VOL", "NSE", "FIVE_MINUTE"): df}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="intraday_bars.db")
    ap.add_argument("--symbols", nargs="*")
    ap.add_argument("--interval", default="FIVE_MINUTE")
    ap.add_argument("--min-days", type=int, default=120)
    ap.add_argument("--refit-days", type=int, default=20)
    ap.add_argument("--horizon", type=int, default=6)
    ap.add_argument("--synthetic", action="store_true")
    a = ap.parse_args()
    if a.synthetic:
        sets = synthetic()
    else:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from intraday_lab import load_db
        sets = load_db(a.db)
    for (s, e, i), df in sorted(sets.items()):
        if i.upper() != a.interval.upper() and not a.synthetic:
            continue
        if a.symbols and s.upper() not in [x.upper() for x in a.symbols]:
            continue
        run(f"{s} [{e}] {i}", df, a)
    print("\nNot financial advice. Volatility forecasts size risk; they do not predict direction.")


if __name__ == "__main__":
    main()
