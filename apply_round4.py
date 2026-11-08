# apply_round4.py -- run from D:\Project\monitoring_old (dry run unless --apply)
import sys, pathlib

APPLY = "--apply" in sys.argv
ROOT = pathlib.Path(__file__).resolve().parent
B = ROOT / "backend"


def patch(rel, old, new, label):
    p = B / rel
    if not p.exists():
        print(f"  MISSING   {rel}")
        return 0
    with open(p, "r", encoding="utf-8", newline="") as f:
        raw = f.read()
    crlf = "\r\n" in raw
    s = raw.replace("\r\n", "\n")
    if new in s:
        print(f"  ALREADY   {label}")
        return 0
    if s.count(old) != 1:
        print(f"  NO MATCH  {label}  (found {s.count(old)}x; patch manually)")
        return 0
    print(f"  APPLIED   {label}")
    if APPLY:
        out = s.replace(old, new, 1)
        if crlf:
            out = out.replace("\n", "\r\n")
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(out)
    return 1


n = 0

# MEDIUM: entry<=0 -> ZeroDivisionError in ATR candidate; no candidate lets compute() use its fallback
n += patch(
    "app/engines/stop_loss_engine.py",
    "    if atr <= 0:\n        return None\n    mult = 1.5 if vol_regime",
    "    if atr <= 0 or entry <= 0:\n        return None\n    mult = 1.5 if vol_regime",
    "stop_loss_engine: guard entry<=0 in _atr_candidate",
)

# MEDIUM: product_type is deliberately required now; the F&O test was stale
n += patch(
    "tests/test_services.py",
    "estimate_required_margin(entry=100, quantity=750, is_fno=True)",
    'estimate_required_margin(entry=100, quantity=750, product_type="NRML", is_fno=True)',
    "test_services: pass product_type in F&O margin test",
)

# LOW: code intentionally uses NRML (bracket orders unsupported for multi-leg); test was stale
n += patch(
    "tests/test_fno_recommendation.py",
    'assert rec.execution_payload["product"] == "BO"',
    'assert rec.execution_payload["product"] == "NRML"',
    "test_fno_recommendation: expect NRML for multi-leg F&O",
)

print(f"\n{'Wrote' if APPLY else 'DRY RUN -'} {n} change(s)." + ("" if APPLY else " Re-run with --apply."))
