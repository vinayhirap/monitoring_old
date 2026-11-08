"""Switch MarketLens from dev to live settings. Run from D:\\Project\\monitoring_old."""
import re, secrets, shutil, sys, pathlib, datetime
root = pathlib.Path(__file__).resolve().parent
apply = "--apply" in sys.argv

cands = [root / "backend" / ".env", root / ".env"]
env = next((p for p in cands if p.exists()), None)
if env is None:
    print("No .env found in backend/ or project root."); sys.exit(1)
text = env.read_text(encoding="utf-8-sig")
print("using:", env)

def get(k):
    m = re.search(rf"^\s*{k}\s*=\s*(.*)$", text, re.M | re.I)
    return m.group(1).strip().strip('"').strip("'") if m else None

want = {"APP_ENV": "production", "LIVE_ONLY": "true"}
sk = get("SECRET_KEY")
if not sk or len(sk) < 32 or "change" in sk.lower():
    want["SECRET_KEY"] = secrets.token_urlsafe(48)
    print("SECRET_KEY: weak/default -> will generate a new one (all users must log in again)")
co = get("CORS_ORIGINS") or ""
need = ["http://localhost:3000", "http://localhost:3001", "http://127.0.0.1:3000", "http://127.0.0.1:3001"]
merged = ",".join(dict.fromkeys([x for x in co.split(",") if x.strip()] + need))
if merged != co: want["CORS_ORIGINS"] = merged

for k, v in want.items():
    shown = "<new random 64-char key>" if k == "SECRET_KEY" else v
    print(f"  {k:13s}: {get(k)!r:>30} -> {shown}")
for k in ("ANGELONE_API_KEY", "ANGELONE_CLIENT_CODE", "ANGELONE_PASSWORD", "ANGELONE_TOTP_SECRET"):
    print(f"  {k:21s} {'set' if get(k) else 'MISSING  <-- live trading needs it'}")

i18n = root / "frontend" / "lib" / "i18n.ts"
if i18n.exists():
    s = i18n.read_text(encoding="utf-8")
    n = re.sub(r"^[ \t]*// @ts-expect-error[^\n]*\n", "", s, flags=re.M)
    print("i18n.ts: stale @ts-expect-error", "will be removed" if n != s else "already clean")
    if apply and n != s: i18n.write_bytes(n.encode("utf-8"))

lg = root / "frontend" / "app" / "login" / "page.tsx"
if lg.exists():
    t = lg.read_text(encoding="utf-8")
    if "function LoginForm()" in t:
        print("login/page.tsx: already wrapped in Suspense")
    else:
        print("login/page.tsx: will wrap in <Suspense>")
        if apply:
            t = t.replace("export default function LoginPage() {", "function LoginForm() {", 1)
            t = t.replace('import { useState, FormEvent } from "react";',
                          'import { Suspense, useState, FormEvent } from "react";', 1)
            t = t.rstrip() + "\n\nexport default function LoginPage() {\n  return (\n    <Suspense fallback={null}>\n      <LoginForm />\n    </Suspense>\n  );\n}\n"
            lg.write_bytes(t.encode("utf-8"))

if not apply:
    print("\n(dry run) re-run with --apply to write changes"); sys.exit(0)
bak = env.with_name(env.name + ".bak-" + datetime.datetime.now().strftime("%Y%m%d%H%M%S"))
shutil.copy2(env, bak); print("backup:", bak)
for k, v in want.items():
    if re.search(rf"^\s*{k}\s*=", text, re.M | re.I):
        text = re.sub(rf"^\s*{k}\s*=.*$", f"{k}={v}", text, flags=re.M | re.I)
    else:
        text += ("" if text.endswith("\n") else "\n") + f"{k}={v}\n"
env.write_text(text, encoding="utf-8")
print("written. Restart the backend, then build + start the frontend.")
