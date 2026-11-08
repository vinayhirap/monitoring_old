# dump_for_fixes.py -- run from D:\Project\monitoring_old ; writes fix_context.txt (no secrets read)
import pathlib, re

ROOT = pathlib.Path(__file__).resolve().parent
B = ROOT / "backend"
out = []


def rd(p):
    return (B / p).read_text(encoding="utf-8", errors="replace").splitlines()


def lines(p, a, b):
    out.append(f"\n##### {p}  lines {a}-{b}")
    try:
        for i, l in enumerate(rd(p)[a - 1:b], a):
            out.append(f"{i:4}: {l}")
    except Exception as e:
        out.append(f"  ERR {e}")


def grep(globs, pat, before=0, after=0, limit=40):
    out.append(f"\n##### grep /{pat}/ in {globs}")
    n = 0
    for g in globs:
        for p in sorted(B.glob(g)):
            if ".venv" in p.parts:
                continue
            L = p.read_text(encoding="utf-8", errors="replace").splitlines()
            for i, l in enumerate(L):
                if re.search(pat, l):
                    out.append(f"-- {p.relative_to(B)}:{i+1}")
                    for j in range(max(0, i - before), min(len(L), i + after + 1)):
                        out.append(f"{j+1:4}: {L[j]}")
                    n += 1
                    if n >= limit:
                        return


lines("app/engines/stop_loss_engine.py", 85, 135)
lines("app/engines/stop_loss_engine.py", 290, 345)
grep(["app/services/*.py"], r"def estimate_required_margin", 0, 30)
grep(["app/**/*.py"], r"estimate_required_margin\(", 1, 3)
lines("tests/test_services.py", 60, 85)
grep(["app/services/risk_guard.py"], r"models\.portfolio", 3, 3)
out.append("\n##### app/models listing")
out += [p.name for p in sorted((B / "app/models").glob("*.py"))]
grep(["app/**/*.py"], r"\bNRML\b|[\"']BO[\"']", 1, 1, limit=25)
lines("tests/test_fno_recommendation.py", 100, 130)
lines("tests/test_strategy_entry.py", 245, 280)
grep(["app/**/*.py"], r"def select\b|stoploss\s*=", 0, 2, limit=20)

(ROOT / "fix_context.txt").write_text("\n".join(out), encoding="utf-8")
print("Wrote fix_context.txt -- upload or paste it here.")
