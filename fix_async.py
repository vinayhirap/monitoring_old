"""Stop slow API routes from freezing the whole backend. Run from D:\\Project\\monitoring_old."""
import pathlib, re, shutil, sys

root = pathlib.Path(__file__).resolve().parent
app_dir = root / "backend" / "app"
api_dir = app_dir / "api"
apply = "--apply" in sys.argv

files = {p: p.read_text(encoding="utf-8").split("\n") for p in sorted(api_dir.glob("*.py"))}


def block_end(lines, i):
    j = i + 1
    while j < len(lines) and (lines[j] == "" or lines[j][0] in " \t)#"):
        j += 1
    return j


funcs = []
for p, lines in files.items():
    for i, l in enumerate(lines):
        if l.startswith("async def "):
            if any("websocket" in x.lower() for x in lines[max(0, i - 8):i]):
                continue
            funcs.append((p, i, block_end(lines, i), re.match(r"async def (\w+)", l).group(1)))

outside = set()
for p in app_dir.rglob("*.py"):
    if api_dir in p.parents:
        continue
    for m in re.finditer(r"\bawait\s+(?:[\w.]*\.)?(\w+)\s*\(", p.read_text(encoding="utf-8", errors="ignore")):
        outside.add(m.group(1))

HARD = re.compile(r"\bawait\b|\basync\s+(with|for)\b|\byield\b")
conv = set()
changed = True
while changed:
    changed = False
    for p, s, e, name in funcs:
        if name in conv or name in outside:
            continue
        body = "\n".join(files[p][s:e])
        body = re.sub(r"\bawait\s+(?:[\w.]*\.)?(\w+)\s*\(",
                      lambda m: (m.group(1) + "(") if m.group(1) in conv else m.group(0), body)
        if not HARD.search(body):
            conv.add(name); changed = True

per_file = {}
for p, lines in files.items():
    new = list(lines)
    n = 0
    for fp, s, e, name in funcs:
        if fp != p:
            continue
        for k in range(s, e):
            new[k] = re.sub(r"\bawait\s+((?:[\w.]*\.)?(\w+))\s*\(",
                            lambda m: (m.group(1) + "(") if m.group(2) in conv else m.group(0), new[k])
        if name in conv:
            new[s] = new[s].replace("async def ", "def ", 1); n += 1
    if n or new != lines:
        per_file[p] = (new, n)

total = 0
for p, (new, n) in per_file.items():
    total += n
    print(f"{p.name}: {n} route(s) converted")
    if apply:
        shutil.copy2(p, p.with_name(p.name + ".bak-async"))
        p.write_text("\n".join(new), encoding="utf-8")
print(f"\n{total} route(s) " + ("converted. Restart the backend." if apply else "would be converted. Re-run with --apply."))
