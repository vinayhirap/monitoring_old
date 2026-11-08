# apply_round2.py
import re, sys, pathlib

APPLY = "--apply" in sys.argv
ROOT = pathlib.Path(__file__).resolve().parent
B = ROOT / "backend"

LOG_REDACT = r'''"""Redact credentials from third-party logs (SmartApi/logzero prints full headers)."""
import logging
import re

_PATTERNS = [
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+"), r"\1***"),
    (re.compile(r"('(?:X-PrivateKey|Authorization|X-ClientPublicIP|X-ClientLocalIP|X-MACAddress)'\s*:\s*)'[^']*'"), r"\1'***'"),
    (re.compile(r'("(?:X-PrivateKey|Authorization|X-ClientPublicIP|X-ClientLocalIP|X-MACAddress)"\s*:\s*)"[^"]*"'), r'\1"***"'),
    (re.compile(r"(?i)((?:api[_-]?key|totp|password|token|secret)\s*[=:]\s*)[^\s,'\"}]+"), r"\1***"),
]


def scrub(text: str) -> str:
    for pat, rep in _PATTERNS:
        text = pat.sub(rep, text)
    return text


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        cleaned = scrub(msg)
        if cleaned != msg:
            record.msg = cleaned
            record.args = ()
        return True


_installed = False


def install_redaction() -> None:
    global _installed
    if _installed:
        return
    f = RedactFilter()
    targets = [logging.getLogger()]
    try:
        import logzero
        targets.append(logzero.logger)
    except Exception:
        pass
    for name in ("SmartApi", "smartConnect", "logzero_default"):
        targets.append(logging.getLogger(name))
    for lg in targets:
        lg.addFilter(f)
        for h in lg.handlers:
            h.addFilter(f)
    _installed = True


install_redaction()
'''

TEST_REDACT = r'''from app.services.log_redact import scrub


def test_scrub_headers_and_bearer():
    s = ("Headers: {'X-PrivateKey': 'abc123', 'X-ClientPublicIP': '1.2.3.4', "
         "'Authorization': 'Bearer eyJhbGciOi.payload.sig'}")
    out = scrub(s)
    assert "abc123" not in out
    assert "1.2.3.4" not in out
    assert "eyJhbGciOi" not in out


def test_scrub_leaves_normal_text():
    assert scrub("Scanner pass complete: 7 combinations") == "Scanner pass complete: 7 combinations"
'''

FIND_SYMBOLS = r'''import json, sys, urllib.request as u
URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
Q = {
    "ICICIPRULI": ["ICICI PRU", "ICICIPRU"],
    "LTIM": ["LTIMINDTREE", "LTIM", "LTM"],
    "TATAMOTORS": ["TATA MOTORS", "TATAMOTORS", "TMPV", "TMCV"],
}
d = json.load(u.urlopen(URL, timeout=120))
eq = [x for x in d if x["exch_seg"] == "NSE" and x["symbol"].endswith("-EQ")]
for old, keys in Q.items():
    print(f"\n== {old} ==")
    seen = set()
    for x in eq:
        hay = (x["symbol"] + " " + x.get("name", "")).upper()
        if any(k in hay for k in keys) and x["symbol"] not in seen:
            seen.add(x["symbol"])
            print(f"  {x['symbol']:<18} name={x.get('name','')!r:<28} token={x['token']}")
'''

PYTEST_INI = "[pytest]\nasyncio_mode = auto\nasyncio_default_fixture_loop_scope = function\ntestpaths = tests\n"


def write_new(path, text):
    if path.exists():
        print(f"  SKIP (exists)   {path.relative_to(ROOT)}")
        return 0
    print(f"  APPLIED (new)   {path.relative_to(ROOT)}")
    if APPLY:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return 1


def patch(path, old, new, label):
    if not path.exists():
        print(f"  MISSING         {path.relative_to(ROOT)}")
        return 0
    s = path.read_text(encoding="utf-8")
    if new in s:
        print(f"  ALREADY         {label}")
        return 0
    if old not in s:
        print(f"  NO MATCH        {label}  (patch manually)")
        return 0
    print(f"  APPLIED         {label}")
    if APPLY:
        path.write_text(s.replace(old, new, 1), encoding="utf-8", newline="")
    return 1


def patch_main_install(path):
    imp = "from app.services.log_redact import install_redaction  # noqa: E402\ninstall_redaction()\n"
    s = path.read_text(encoding="utf-8")
    if "install_redaction" in s:
        print("  ALREADY         main.py redaction hook")
        return 0
    m = re.search(r"^(app\s*=\s*FastAPI|@asynccontextmanager)", s, re.M)
    if not m:
        print("  NO MATCH        main.py  -> add manually near the top:\n"
              "                  from app.services.log_redact import install_redaction\n"
              "                  install_redaction()")
        return 0
    print("  APPLIED         main.py redaction hook")
    if APPLY:
        path.write_text(s[:m.start()] + imp + "\n" + s[m.start():], encoding="utf-8", newline="")
    return 1


n = 0
n += write_new(B / "app/services/log_redact.py", LOG_REDACT)
n += write_new(B / "tests/test_log_redact.py", TEST_REDACT)
n += write_new(B / "scripts/find_symbols.py", FIND_SYMBOLS)
n += write_new(B / "pytest.ini", PYTEST_INI)
n += patch_main_install(B / "app/main.py")
n += patch(
    B / "app/services/trade_executor.py",
    "rg_dict.get('reasons', ['unknown'])[0]",
    "(rg_dict.get('reasons') or ['unknown'])[0]",
    "trade_executor: empty risk-guard reasons crash",
)

print(f"\n{'Wrote' if APPLY else 'DRY RUN -'} {n} change(s)." + ("" if APPLY else " Re-run with --apply."))
