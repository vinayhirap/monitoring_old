#!/usr/bin/env python3
"""MarketLens go-live fixes.

Run from the repo root (the folder that contains backend/ and frontend/).

    python apply_golive_fixes.py            # dry run: shows what WOULD change
    python apply_golive_fixes.py --apply    # writes the changes

Safe by design:
  * dry run unless --apply is given
  * every fix is anchored on exact text; if the anchor is not found the fix is
    reported as ANCHOR-MISSING and that file is left untouched
  * running it twice is harmless (already-applied fixes are reported as ALREADY)
  * files are read and written as raw UTF-8 bytes, so line endings and
    non-ASCII characters (the check marks in the log lines) are preserved
  * a file that already contains mojibake ("â€", "âœ") is refused, so a
    previous bad re-encode cannot be made worse

Fixes:
  1  numpy bool/int/float/array -> JSON      (astro-lab/measure, calibration/quick 500s)
  2  candle window counts trading bars        (calibration "only have 169 bars")
  3  sector heatmap: background + cached      (150 s timeout)
  4  stale symbols in universe.py             (ZOMATO, TV18BRDCST, AARTI IND, ...)
  5  scanner interval 5 -> 15 min             (scan pass takes ~5.5 min)
  6  journal retention 14 -> 120 days         (keep evidence for accuracy testing)
  7  /api/commodities/scan was shadowed by /{symbol}
  8  scanner universe defaults to fno_top50 (not nifty500) when the env var is unset
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent
APPLY = "--apply" in sys.argv
BACKEND = ROOT / "backend"

MOJIBAKE = ("\u00e2\u0153", "\u00e2\u20ac")  # "âœ" and "â€"


def read(p: pathlib.Path) -> str:
    return p.read_bytes().decode("utf-8")


def write(p: pathlib.Path, text: str) -> None:
    p.write_bytes(text.encode("utf-8"))


results: list[tuple[str, str, str]] = []   # (fix, file, status)
pending: dict[pathlib.Path, str] = {}      # file -> new text


def load(p: pathlib.Path) -> str | None:
    if p in pending:
        return pending[p]
    if not p.exists():
        return None
    text = read(p)
    if any(m in text for m in MOJIBAKE):
        return None
    return text


def report(fix: str, p: pathlib.Path, status: str) -> None:
    results.append((fix, str(p.relative_to(ROOT)), status))


def edit(fix: str, p: pathlib.Path, fn) -> None:
    """fn(text) -> (new_text, status). status in APPLIED / ALREADY / ANCHOR-MISSING."""
    if not p.exists():
        report(fix, p, "FILE-MISSING")
        return
    text = load(p)
    if text is None:
        report(fix, p, "REFUSED (mojibake) - run: git checkout -- " + str(p.relative_to(ROOT)))
        return
    new, status = fn(text)
    if status == "APPLIED":
        pending[p] = new
    report(fix, p, status)


# --------------------------------------------------------------------------
# 1. numpy -> JSON
# --------------------------------------------------------------------------
JSON_COMPAT = '''"""Teach FastAPI's jsonable_encoder about numpy scalars and arrays.

Without this, any endpoint that returns a numpy.bool_ / numpy.int64 / ndarray
fails with: TypeError: 'numpy.bool_' object is not iterable  ->  HTTP 500.
Importing this module (done once from app.main) fixes every route at once.
"""
import numpy as np
from fastapi.encoders import ENCODERS_BY_TYPE


def _register() -> None:
    ENCODERS_BY_TYPE[np.bool_] = bool
    for t in (np.int8, np.int16, np.int32, np.int64,
              np.uint8, np.uint16, np.uint32, np.uint64):
        ENCODERS_BY_TYPE[t] = int
    for t in (np.float16, np.float32, np.float64):
        ENCODERS_BY_TYPE[t] = float
    ENCODERS_BY_TYPE[np.ndarray] = lambda a: a.tolist()


_register()
'''

JSON_COMPAT_TEST = '''"""numpy values must survive FastAPI serialisation (regression: HTTP 500 on
/api/astro-lab/measure and /api/calibration/quick)."""
import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.services.json_compat  # noqa: F401  (registers the encoders)


def _client() -> TestClient:
    app = FastAPI()

    @app.get("/x")
    def x():
        return {
            "flag": np.bool_(True),
            "n": np.int64(7),
            "f": np.float32(1.5),
            "arr": np.array([1, 2, 3]),
            "nested": [{"ok": np.bool_(False)}],
        }

    return TestClient(app)


def test_numpy_values_serialise():
    r = _client().get("/x")
    assert r.status_code == 200
    assert r.json() == {
        "flag": True, "n": 7, "f": 1.5, "arr": [1, 2, 3],
        "nested": [{"ok": False}],
    }
'''


def fix1() -> None:
    mod = BACKEND / "app" / "services" / "json_compat.py"
    tst = BACKEND / "tests" / "test_json_compat.py"
    for p, body in ((mod, JSON_COMPAT), (tst, JSON_COMPAT_TEST)):
        if p.exists() and read(p) == body:
            report("1", p, "ALREADY")
        elif p.exists():
            report("1", p, "ALREADY (exists, different content - left alone)")
        else:
            pending[p] = body
            report("1", p, "APPLIED (new file)")

    def hook(text: str):
        if "app.services.json_compat" in text or "services import json_compat" in text:
            return text, "ALREADY"
        m = re.search(r"^from loguru import logger[^\r\n]*(\r?\n)", text, re.M)
        if not m:
            return text, "ANCHOR-MISSING"
        nl = m.group(1)
        ins = "import app.services.json_compat  # noqa: F401  numpy -> JSON" + nl
        return text[: m.end()] + ins + text[m.end():], "APPLIED"

    edit("1", BACKEND / "app" / "main.py", hook)


# --------------------------------------------------------------------------
# 2. candle window: periods are TRADING BARS, not calendar days
# --------------------------------------------------------------------------
def fix2() -> None:
    def f(text: str):
        if "_days = min(2000" in text:
            return text, "ALREADY"
        m = re.search(
            r"^([ \t]*)from_dt = to_dt - timedelta\(days=periods \+ 30\)[ \t]*(\r?\n)",
            text, re.M)
        if not m:
            return text, "ANCHOR-MISSING"
        i, nl = m.group(1), m.group(2)
        new = nl.join([
            f"{i}# `periods` counts trading BARS. Daily bars are ~252 per 365 calendar",
            f"{i}# days, so the old `periods + 30` calendar-day window returned only",
            f"{i}# ~2/3 of the bars asked for (250 requested -> 169 returned).",
            f"{i}# Angel One caps ONE_DAY history at 2000 days per request.",
            f'{i}if interval == "ONE_DAY":',
            f"{i}    _days = min(2000, int(periods * 1.5) + 30)",
            f"{i}else:",
            f"{i}    _days = periods + 30",
            f"{i}from_dt = to_dt - timedelta(days=_days)",
        ]) + nl
        return text[: m.start()] + new + text[m.end():], "APPLIED"

    edit("2", BACKEND / "app" / "services" / "market_data.py", f)


# --------------------------------------------------------------------------
# 3. sector heatmap: compute in background, serve cache
# --------------------------------------------------------------------------
HEATMAP = '''@router.get("/sectors/heatmap", summary="Sector rotation heatmap - bullish vs bearish stock counts per sector")
def sector_heatmap(parallel: int = Query(4, ge=1, le=16),
                   refresh: bool = Query(False, description="force a background recompute")):
    """Runs decision.aggregate on every constituent of every sector and counts
    bullish vs bearish. ~180 symbols through the full engine takes minutes, so
    it is computed in a background thread and cached for 15 minutes; a request
    never blocks longer than ~20 s. Symbols missing from the scrip master are
    skipped and listed in `skipped_symbols`; symbols whose data fetch failed are
    listed in `errors` and are NOT counted as neutral.
    """
    now = time.time()
    with _hm_lock:
        data, at = _hm_state["data"], _hm_state["at"]
    if data is not None and not refresh and now - at < _HEATMAP_TTL_SEC:
        return {**data, "cached": True, "age_sec": int(now - at)}

    _hm_start(parallel)
    if data is None:
        _hm_done.wait(timeout=_HEATMAP_WAIT_SEC)
        with _hm_lock:
            data, at = _hm_state["data"], _hm_state["at"]
            err = _hm_state["error"]
        if data is None:
            return {"sectors": [], "total_sectors": 0, "status": "computing",
                    "detail": "first computation in progress - retry in a minute",
                    "error": err}
    return {**data, "cached": True, "stale": True, "age_sec": int(time.time() - at)}
'''

HEATMAP_HELPERS = '''

# --- Sector heatmap: background compute + cache ----------------------------
import threading
import time

_HEATMAP_TTL_SEC = 15 * 60
_HEATMAP_WAIT_SEC = 20
_hm_lock = threading.Lock()
_hm_state: dict = {"data": None, "at": 0.0, "running": False, "error": None}
_hm_done = threading.Event()


def _has_token(sym: str) -> bool:
    """True if the symbol is in the scrip master (no network call)."""
    try:
        from app.services import instruments
        eq = getattr(instruments, "_equity_lookup", None)
        if not eq or not getattr(instruments, "_loaded", False):
            return True            # master not loaded yet: do not skip anything
        return sym.upper() in eq
    except Exception:
        return True


def _compute_heatmap(parallel: int) -> dict:
    def _score_one(sym: str):
        try:
            df = get_ohlcv(sym, periods=200)
            r = decision.aggregate(symbol=sym, df=df)
            return sym, r["signal"], r["confidence"]
        except Exception as e:
            logger.debug("sector heatmap {} failed: {}", sym, e)
            return sym, "ERROR", 0

    by_sector: dict[str, list[str]] = {}
    skipped: list[str] = []
    for sector_name, symbols in SECTORS.items():
        ok = []
        for s in symbols:
            if _has_token(s):
                ok.append(s)
            elif s not in skipped:
                skipped.append(s)
        by_sector[sector_name] = ok
    unique = sorted({s for v in by_sector.values() for s in v})

    scores: dict[str, tuple] = {}
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = {pool.submit(_score_one, s): s for s in unique}
        for fut in as_completed(futures):
            try:
                sym, sig, conf = fut.result()
            except Exception:
                continue
            scores[sym] = (sig, conf)

    errors = sorted(s for s, (sig, _) in scores.items() if sig == "ERROR")
    sector_data = []
    for sector_name, symbols in by_sector.items():
        bulls = bears = neutral = count = 0
        total_conf = 0.0
        top = []
        for sym in symbols:
            if sym not in scores or scores[sym][0] == "ERROR":
                continue
            sig, conf = scores[sym]
            if sig in ("BUY", "STRONG_BUY"):
                bulls += 1
            elif sig in ("SELL", "STRONG_SELL"):
                bears += 1
            else:
                neutral += 1
            total_conf += conf
            count += 1
            top.append({"symbol": sym, "signal": sig, "confidence": conf})
        top.sort(key=lambda x: -x["confidence"])
        sector_data.append({
            "sector": sector_name,
            "count": count,
            "bulls": bulls, "bears": bears, "neutral": neutral,
            "net_bias": bulls - bears,
            "avg_confidence": round(total_conf / max(1, count), 2),
            "top_3": top[:3],
        })
    sector_data.sort(key=lambda s: -s["net_bias"])
    return {"sectors": sector_data, "total_sectors": len(sector_data),
            "skipped_symbols": skipped, "errors": errors,
            "computed_at": time.strftime("%Y-%m-%d %H:%M:%S")}


def _hm_worker(parallel: int) -> None:
    try:
        data = _compute_heatmap(parallel)
        with _hm_lock:
            _hm_state.update(data=data, at=time.time(), error=None)
        logger.info("sector heatmap computed: {} sectors, {} skipped, {} errors",
                    data["total_sectors"], len(data["skipped_symbols"]), len(data["errors"]))
    except Exception as e:
        logger.exception("sector heatmap compute crashed")
        with _hm_lock:
            _hm_state["error"] = f"{type(e).__name__}: {e}"
    finally:
        with _hm_lock:
            _hm_state["running"] = False
        _hm_done.set()


def _hm_start(parallel: int) -> None:
    with _hm_lock:
        if _hm_state["running"]:
            return
        _hm_state["running"] = True
        _hm_done.clear()
    threading.Thread(target=_hm_worker, args=(parallel,),
                     name="sector-heatmap", daemon=True).start()


'''


def fix3() -> None:
    def f(text: str):
        if "_hm_state" in text:
            return text, "ALREADY"
        m = re.search(r'^@router\.get\("/sectors/heatmap"', text, re.M)
        if not m:
            return text, "ANCHOR-MISSING"
        tail = text[m.start():]
        if len(re.findall(r"^@router\.", tail, re.M)) != 1:
            return text, "ANCHOR-MISSING (heatmap is not the last route in the file)"
        if "decision" not in text or "get_ohlcv" not in text or "SECTORS" not in text:
            return text, "ANCHOR-MISSING (expected imports not found)"
        nl = "\r\n" if "\r\n" in text else "\n"
        body = (HEATMAP_HELPERS + HEATMAP).replace("\n", nl)
        return text[: m.start()].rstrip("\r\n") + nl + body, "APPLIED"

    edit("3", BACKEND / "app" / "api" / "advanced.py", f)


# --------------------------------------------------------------------------
# 4. stale symbols
# --------------------------------------------------------------------------
SYMBOL_MAP = {
    '"ZOMATO"': '"ETERNAL"',          # renamed
    '"AARTI IND"': '"AARTIIND"',      # trading symbol has no space
    '"GMRINFRA"': '"GMRAIRPORT"',     # renamed
    '"PIRAMA"': '"PIRAMALFIN"',       # truncated / renamed
}
SYMBOL_DROP = ['"TV18BRDCST"']        # merged into NETWORK18 (already listed)


def fix4() -> None:
    def f(text: str):
        new = text
        changed = False
        for old, rep in SYMBOL_MAP.items():
            if old in new:
                new = new.replace(old, rep)
                changed = True
        for d in SYMBOL_DROP:
            pat = re.compile(r"[ \t]*" + re.escape(d) + r",")
            if pat.search(new):
                new = pat.sub("", new, count=1)
                changed = True
        return (new, "APPLIED") if changed else (text, "ALREADY")

    edit("4", BACKEND / "app" / "services" / "universe.py", f)


# --------------------------------------------------------------------------
# 5 + 6. scanner interval, journal retention
# --------------------------------------------------------------------------
def fix5() -> None:
    def f(text: str):
        new = re.sub(r"^(SCAN_INTERVAL_MINUTES\s*=\s*)5\b", r"\g<1>15", text, flags=re.M)
        new = re.sub(r"^(FRESHNESS_THRESHOLD_SECONDS\s*=\s*)600[^\r\n]*",
                     r"\g<1>1800    # 30 min = 2x the 15-min scan interval", new, flags=re.M)
        if new != text:
            return new, "APPLIED"
        if re.search(r"^SCAN_INTERVAL_MINUTES\s*=\s*15\b", text, re.M):
            return text, "ALREADY"
        return text, "ANCHOR-MISSING"

    edit("5", BACKEND / "app" / "jobs" / "picks_scanner.py", f)


def fix6() -> None:
    def f(text: str):
        new = text.replace("purge_older_than_days(days=14)", "purge_older_than_days(days=120)")
        new = new.replace("(14-day window, purges every 6h)", "(120-day window, purges every 6h)")
        new = new.replace("keep last 14 days", "keep last 120 days")
        if new != text:
            return new, "APPLIED"
        if "purge_older_than_days(days=120)" in text:
            return text, "ALREADY"
        return text, "ANCHOR-MISSING"

    edit("6", BACKEND / "app" / "main.py", f)


# --------------------------------------------------------------------------
# 7. /scan shadowed by /{symbol}
# --------------------------------------------------------------------------
def fix7() -> None:
    def f(text: str):
        s = re.search(r'^@router\.get\("/scan"', text, re.M)
        d = re.search(r'^@router\.get\("/\{symbol\}"', text, re.M)
        if not s or not d:
            return text, "ANCHOR-MISSING"
        if s.start() < d.start():
            return text, "ALREADY"
        tail = text[s.start():]
        if len(re.findall(r"^@router\.", tail, re.M)) != 1:
            return text, "ANCHOR-MISSING (scan is not the last route)"
        nl = "\r\n" if "\r\n" in text else "\n"
        block = tail.rstrip("\r\n") + nl + nl + nl
        head = text[: s.start()].rstrip("\r\n") + nl
        # insert block just before the /{symbol} decorator
        return head[: d.start()] + block + head[d.start():], "APPLIED"

    edit("7", BACKEND / "app" / "api" / "commodities.py", f)


# --------------------------------------------------------------------------
# 8. scanner universe default
# --------------------------------------------------------------------------
def fix8() -> None:
    def f(text: str):
        new = re.sub(r'(os\.getenv\("SCANNER_UNIVERSE",\s*)"nifty500"', r'\g<1>"fno_top50"', text)
        if new != text:
            return new, "APPLIED"
        if re.search(r'os\.getenv\("SCANNER_UNIVERSE",\s*"fno_top50"', text):
            return text, "ALREADY"
        return text, "ANCHOR-MISSING"

    edit("8", BACKEND / "app" / "jobs" / "picks_scanner.py", f)


# --------------------------------------------------------------------------
def main() -> int:
    if not (BACKEND / "app").is_dir():
        print("Run this from the repo root (the folder containing backend/ and frontend/).")
        return 2
    for fn in (fix1, fix2, fix3, fix4, fix5, fix6, fix7, fix8):
        fn()

    width = max(len(r[1]) for r in results)
    for fix, f, status in results:
        print(f"  fix {fix}  {f.ljust(width)}  {status}")

    bad = [r for r in results if r[2].startswith(("ANCHOR", "REFUSED", "FILE-MISSING"))]
    if APPLY:
        for p, text in pending.items():
            p.parent.mkdir(parents=True, exist_ok=True)
            write(p, text)
        print(f"\nWrote {len(pending)} file(s).")
    else:
        print(f"\nDRY RUN - {len(pending)} file(s) would change. Re-run with --apply to write.")
    if bad:
        print(f"{len(bad)} fix(es) could not be applied - paste this output back and I'll adjust.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
