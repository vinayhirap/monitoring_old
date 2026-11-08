"""Alert dispatcher — Telegram (extensible to WhatsApp/email).

Configure via .env:
    ALERTS_ENABLED=true
    TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
    TELEGRAM_CHAT_ID=12345678
    ALERTS_MIN_CONFIDENCE=75    # only fire when final_confidence >= this

Use:
    from app.services import alerts
    alerts.send_signal(symbol="RELIANCE", signal="STRONG_BUY", confidence=82,
                       entry=2945, sl=2912, targets=[2978, 3010, 3055],
                       reason="6/6 engines aligned, hora=Jupiter")

Idempotency: a 30-minute per-symbol cooldown prevents alert spam if the
same signal recurs across consecutive scans.
"""
from __future__ import annotations

import os
import time
from typing import Iterable
import httpx
from loguru import logger


_cooldown: dict[str, float] = {}
_COOLDOWN_SEC = 30 * 60


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _enabled() -> bool:
    return _env("ALERTS_ENABLED", "false").lower() in ("1", "true", "yes")


def _min_conf() -> float:
    try:
        return float(_env("ALERTS_MIN_CONFIDENCE", "75"))
    except ValueError:
        return 75.0


def _telegram_creds() -> tuple[str, str] | None:
    tok = _env("TELEGRAM_BOT_TOKEN")
    cid = _env("TELEGRAM_CHAT_ID")
    if tok and cid:
        return tok, cid
    return None


def _under_cooldown(key: str) -> bool:
    last = _cooldown.get(key, 0)
    return (time.time() - last) < _COOLDOWN_SEC


def _mark(key: str) -> None:
    _cooldown[key] = time.time()


# ---------------------------------------------------------------------------

def send_telegram(text: str, disable_preview: bool = True) -> bool:
    creds = _telegram_creds()
    if not creds:
        logger.warning("Telegram alert skipped — no TELEGRAM_BOT_TOKEN/CHAT_ID")
        return False
    tok, cid = creds
    url = f"https://api.telegram.org/bot{tok}/sendMessage"
    try:
        r = httpx.post(url, json={
            "chat_id": cid, "text": text, "parse_mode": "Markdown",
            "disable_web_page_preview": disable_preview,
        }, timeout=10)
        if r.status_code == 200:
            return True
        logger.error("Telegram send failed: {} — {}", r.status_code, r.text[:200])
        return False
    except Exception as e:
        logger.error("Telegram send error: {}", e)
        return False


# ---------------------------------------------------------------------------

def send_signal(
    *, symbol: str, signal: str, confidence: float,
    entry: float, sl: float, targets: Iterable[float],
    strategy: str = "", reason: str = "",
    holding_days: float | None = None,
    horizon: str = "SWING",
) -> bool:
    """High-level helper used by the pipeline / recommender."""
    if not _enabled():
        return False
    if confidence < _min_conf():
        return False
    key = f"{symbol}:{signal}:{horizon}"
    if _under_cooldown(key):
        logger.debug("Alert cooldown: {}", key)
        return False

    direction_emoji = "🟢" if signal.endswith("BUY") else "🔴" if signal.endswith("SELL") else "⚪"
    targets_str = " / ".join(f"₹{t:,.2f}" for t in targets)
    parts = [
        f"{direction_emoji} *{signal.replace('_', ' ')}* — `{symbol}`",
        f"Confidence: *{confidence:.1f}%* · {horizon}",
        f"Entry: ₹{entry:,.2f}",
        f"SL: ₹{sl:,.2f}",
        f"Targets: {targets_str}",
    ]
    if strategy:
        parts.append(f"Strategy: `{strategy}`")
    if holding_days is not None:
        parts.append(f"Est. hold: ~{holding_days:.1f} days")
    if reason:
        parts.append(f"_Why:_ {reason[:280]}")
    parts.append("_MarketLens · educational only_")

    ok = send_telegram("\n".join(parts))
    if ok:
        _mark(key)
    return ok


def send_pipeline_finalists(finalists: list[dict], horizon: str = "SWING") -> int:
    sent = 0
    for f in finalists:
        try:
            if send_signal(
                symbol=f["symbol"],
                signal=f["final_signal"],
                confidence=f["final_confidence"],
                entry=f["strategy"]["entry"],
                sl=f["strategy"]["stoploss"],
                targets=f["strategy"]["targets"],
                strategy=f["strategy"]["strategy"],
                reason=f.get("composite_reasons", {}).get("technical", ""),
                holding_days=f.get("holding_plan", {}).get("estimated_days_to_t1"),
                horizon=horizon,
            ):
                sent += 1
        except Exception as e:
            logger.warning("Alert dispatch failed for {}: {}", f.get("symbol"), e)
    return sent
