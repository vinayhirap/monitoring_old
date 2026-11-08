# dump_round4b.py -- run from D:\Project\monitoring_old ; prints code snippets only (no secrets), also saves fix_context2.txt
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


def grep_file(p, pat):
    out.append(f"\n##### grep /{pat}/ in {p}")
    try:
        for i, l in enumerate(rd(p), 1):
            if re.search(pat, l):
                out.append(f"{i:4}: {l}")
    except Exception as e:
        out.append(f"  ERR {e}")


lines("app/engines/strategy.py", 252, 346)
lines("app/engines/strategy.py", 374, 440)
for m in ("app/models/trade.py", "app/models/trade_execution.py"):
    grep_file(m, r"^class |Column\(|mapped_column|__tablename__")
lines("app/services/risk_guard.py", 250, 310)
out.append("\n##### callers")
for p in sorted((B / "app").rglob("*.py")):
    for i, l in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if re.search(r"open_portfolio_risk_pct\(|recent_loss_count\(", l) and "def " not in l:
            out.append(f"{p.relative_to(B)}:{i}: {l.strip()}")

text = "\n".join(out)
(ROOT / "fix_context2.txt").write_text(text, encoding="utf-8")
print(text)
