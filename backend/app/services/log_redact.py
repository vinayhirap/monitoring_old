"""Redact credentials from third-party logs (SmartApi/logzero prints full headers)."""
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
