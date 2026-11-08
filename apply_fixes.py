"""Apply small code fixes to MarketLens. Run from D:\\Project\\monitoring_old."""
import pathlib, shutil, sys

root = pathlib.Path(__file__).resolve().parent
apply = "--apply" in sys.argv
changed = 0


def patch(rel, old, new, marker, base=("backend", "app")):
    global changed
    p = root.joinpath(*base) / rel
    if not p.exists():
        print(f"MISSING {p}"); return
    s = p.read_text(encoding="utf-8")
    if marker in s:
        print(f"already patched: {rel}"); return
    if old not in s:
        print(f"PATTERN NOT FOUND in {rel} - file differs from expected, not touched"); return
    print(f"will patch: {rel}")
    changed += 1
    if apply:
        shutil.copy2(p, p.with_name(p.name + ".bak"))
        p.write_text(s.replace(old, new, 1), encoding="utf-8")


patch(
    "brokers/angelone.py",
    "res = self._client.searchScrip(exchange=exchange, searchtext=query)",
    "res = self._client.searchScrip(exchange, query)  # positional: SDK param name differs by version",
    "searchScrip(exchange, query)",
)

patch(
    "engines/recommender.py",
    "        df = get_ohlcv(symbol, periods=250)\n        return decision.aggregate(",
    "        df = get_ohlcv(symbol, periods=250)\n"
    "        # Skip dead / circuit-locked / zero-price instruments (zero range -> divide-by-zero)\n"
    "        if df is None or len(df) < 30 or float(df[\"close\"].iloc[-1]) <= 0 \\\n"
    "                or float((df[\"high\"] - df[\"low\"]).tail(20).sum()) <= 0:\n"
    "            return {\"symbol\": symbol, \"error\": \"skipped: flat or zero-price data\"}\n"
    "        return decision.aggregate(",
    "skipped: flat or zero-price data",
)

FE = ("frontend",)
patch("app/astro-lab/page.tsx", "Sparkles, Flask, TrendingUp", "Sparkles, TrendingUp",
      "Sparkles, TrendingUp, TrendingDown, Calendar", FE)
patch("app/portal/page.tsx", "Activity, Sparkles, Moon,\n} from \"lucide-react\"",
      "Activity, Sparkles, Moon, Star,\n} from \"lucide-react\"", "Moon, Star,", FE)
patch("components/SimpleRecommendation.tsx", "ShieldAlert, Ban,\n} from \"lucide-react\"",
      "ShieldAlert, Ban, Star,\n} from \"lucide-react\"", "Ban, Star,", FE)

if not apply:
    print(f"\n(dry run) {changed} file(s) would change. Re-run with --apply.")
else:
    print(f"\ndone, {changed} file(s) patched. Restart the backend.")
