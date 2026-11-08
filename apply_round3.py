# apply_round3.py  -- fix renamed/missing symbols in SECTORS (dry run unless --apply)
import re, sys, pathlib

APPLY = "--apply" in sys.argv
ROOT = pathlib.Path(__file__).resolve().parent
UNIVERSE = ROOT / "backend/app/services/universe.py"

# old -> replacement symbols (None = remove). Source: Angel One scrip master.
RENAMES = {
    "LTIM": ["LTM"],
    "TATAMOTORS": ["TMPV", "TMCV"],
    "ICICIPRULI": None,  # not in scrip master under any ICICIPRU* name
}


def sub_symbol(s, old, new_list):
    pat = re.compile(r"""(['"])%s\1""" % re.escape(old))
    if not pat.search(s):
        return s, False
    if new_list is None:
        rm = re.compile(r"""\s*(['"])%s\1\s*,?""" % re.escape(old))
        return rm.sub("", s, count=1), True

    def rep(m):
        q = m.group(1)
        return ", ".join(f"{q}{x}{q}" for x in new_list)

    return pat.sub(rep, s, count=1), True


if not UNIVERSE.exists():
    sys.exit(f"MISSING {UNIVERSE}")

s = UNIVERSE.read_text(encoding="utf-8")
changed = 0
for old, new in RENAMES.items():
    if new and all(re.search(r"""(['"])%s\1""" % x, s) for x in new) and not re.search(r"""(['"])%s\1""" % old, s):
        print(f"  ALREADY   {old}")
        continue
    s2, ok = sub_symbol(s, old, new)
    if ok:
        print(f"  APPLIED   {old} -> {new if new else 'removed'}")
        s = s2
        changed += 1
    else:
        print(f"  NO MATCH  {old} (not found as a quoted string in universe.py)")

if APPLY and changed:
    UNIVERSE.write_text(s, encoding="utf-8", newline="")

# read-only: other places still using the old names
print("\nOther references to old symbols (review manually):")
hits = 0
for p in (ROOT / "backend").rglob("*.py"):
    if ".venv" in p.parts or p == UNIVERSE or p.name.startswith("apply_"):
        continue
    try:
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if re.search(r"\b(LTIM|TATAMOTORS|ICICIPRULI)\b", line):
                print(f"  {p.relative_to(ROOT)}:{i}: {line.strip()[:120]}")
                hits += 1
    except Exception:
        pass
if not hits:
    print("  none")

print(f"\n{'Wrote' if APPLY else 'DRY RUN -'} {changed} change(s)." + ("" if APPLY else " Re-run with --apply."))
