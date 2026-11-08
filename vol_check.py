r"""Run from D:\Project\monitoring_old (backend can stay running):
   backend\.venv\Scripts\python.exe vol_check.py [--db intraday_bars.db]
Checks backend/app/engines/vol_forecast.py on the bars from download_intraday.py."""
import argparse, importlib.util, pathlib, sqlite3, sys
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--db", default=str(ROOT / "intraday_bars.db"))
ap.add_argument("--symbols", default="NIFTY,BANKNIFTY")
args = ap.parse_args()

spec = importlib.util.spec_from_file_location("vf", ROOT / "backend" / "app" / "engines" / "vol_forecast.py")
vf = importlib.util.module_from_spec(spec); sys.modules["vf"] = vf; spec.loader.exec_module(vf)

con = sqlite3.connect(args.db)
tables = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
table, cols = None, []
for t in tables:
    c = [r[1] for r in con.execute(f"pragma table_info('{t}')")]
    print(f"table {t}: {c}")
    if "close" in [x.lower() for x in c] and table is None:
        table, cols = t, c
if table is None:
    raise SystemExit("no table with a 'close' column found - paste the table list above")
low = {c.lower(): c for c in cols}
tcol = next((low[k] for k in ("ts", "timestamp", "datetime", "time", "date") if k in low), None)
scol = next((low[k] for k in ("symbol", "sym", "name") if k in low), None)
icol = next((low[k] for k in ("interval", "timeframe", "tf") if k in low), None)
print(f"using {table}: time={tcol} symbol={scol} interval={icol}")
raw = pd.read_sql(f'select * from "{table}"', con)
if tcol is None:
    raise SystemExit("could not find a time column")
raw[tcol] = pd.to_datetime(raw[tcol], errors="coerce")
raw = raw.dropna(subset=[tcol])
if icol:
    iv = raw[icol].astype(str).str.upper()
    raw = raw[iv.isin(["FIVE_MINUTE", "5M", "5MIN", "5"])]

for sym in args.symbols.split(","):
    d = raw[raw[scol].astype(str).str.upper() == sym] if scol else raw
    if len(d) < 1000:
        print(f"\n{sym}: only {len(d)} bars - skipping"); continue
    df = d.set_index(tcol).sort_index()
    df = df[~df.index.duplicated()]
    df.columns = [c.lower() for c in df.columns]
    rv, bars = vf.daily_rv_from_intraday(df)
    f = vf.forecast(df, intraday=True)
    print(f"\n=== {sym}  bars={len(df)} sessions={len(rv)} bars/day={bars} dropped_short={f.dropped_short_sessions}")
    for w in (1.0, 0.5):
        ev = vf.walk_forward_eval(rv, w_har=w)
        if not ev["ok"]:
            print(ev); break
        m = ev["models"]
        print(f" w_har={w}: HAR {m['har']['vs_naive_pct']:+.1f}% | blend {m['blend']['vs_naive_pct']:+.1f}% | "
              f"ewma {m['ewma']['vs_naive_pct']:+.1f}% vs naive (QLIKE) | "
              f"MAE bps har {m['har']['mae_sigma_bps']} naive {m['naive']['mae_sigma_bps']} | "
              f"80% coverage {ev['blend_80pct_coverage']}%")
    print(f" NEXT: sigma {f.sigma_day_pct}% (80% {f.range80_pct[0]}-{f.range80_pct[1]}%), "
          f"30m {f.sigma_30m_pct}%, regime {f.regime}, HAR weight {f.blend_weight_har}")
    for w in f.warnings: print("  note:", w)
