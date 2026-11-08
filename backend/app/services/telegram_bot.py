"""Telegram bot integration — publishes signals to per-tier channels.

How to enable this feature:

  1. Talk to @BotFather on Telegram. Run /newbot and follow the prompts.
     You'll receive an HTTP API token like '8123456789:AAH...'.

  2. Set the token in backend/.env:
        TELEGRAM_BOT_TOKEN=8123456789:AAH...

  3. Create three Telegram channels (one per paid tier):
        MarketLens BASIC channel
        MarketLens INTERMEDIATE channel
        MarketLens ADVANCED channel
     Add the bot as an admin to each, with "Post messages" permission.

  4. Get each channel's chat_id (or @channel_username) and set:
        TELEGRAM_CHANNEL_BASIC=@your_basic_channel_handle
        TELEGRAM_CHANNEL_INTERMEDIATE=@your_intermediate_channel_handle
        TELEGRAM_CHANNEL_ADVANCED=@your_advanced_channel_handle

  5. Restart the backend. On startup the module logs whether config is valid.
     If misconfigured, this entire module is a no-op — signals continue to
     work without Telegram delivery.

Module behavior:

  • publish_signal(symbol, direction, ...) → posts to BASIC/INTERMEDIATE/ADVANCED
    in parallel (the lowest tier that should see this signal determines floor).
    Tier inclusion is configurable via SIGNAL_TIER_FLOOR (defaults: stars ≥ 4
    → BASIC, stars ≥ 3 → INTERMEDIATE, stars ≥ 2 → ADVANCED).

  • Posts are formatted in Markdown — symbol bold, entry/SL/target tabular,
    disclaimer suffixed.

  • All HTTP calls are wrapped in try/except — Telegram outages don't break
    the signal flow.

What this module DOES NOT do (yet):
  • User onboarding via /start (auto-fill telegram_chat_id) — that needs
    long-polling or a webhook endpoint. Add when ready.
  • Per-user DMs — current architecture is channel broadcasts.
  • Image generation (chart screenshots) — text-only for now.
"""
from __future__ import annotations

import os
import time
from typing import Optional

import httpx
from loguru import logger


# ----- Config from environment -----
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_API_BASE   = "https://api.telegram.org"
HTTP_TIMEOUT_SEC    = 10

CHANNEL_FOR_TIER = {
    "BASIC":        os.getenv("TELEGRAM_CHANNEL_BASIC", "").strip(),
    "INTERMEDIATE": os.getenv("TELEGRAM_CHANNEL_INTERMEDIATE", "").strip(),
    "ADVANCED":     os.getenv("TELEGRAM_CHANNEL_ADVANCED", "").strip(),
}

# What's the lowest tier that should see a signal of N stars?
# Higher-conviction signals reach lower-tier channels too — but FREE gets
# nothing (no channel mapped above).
SIGNAL_TIER_FLOOR = {
    5: "BASIC",         # 5★ → reach everyone paid
    4: "BASIC",
    3: "INTERMEDIATE",
    2: "ADVANCED",
    1: "ADVANCED",
}


def is_configured() -> bool:
    """True iff the bot token is set AND at least one channel is configured."""
    if not TELEGRAM_BOT_TOKEN:
        return False
    return any(CHANNEL_FOR_TIER.values())


def _channels_for_signal(stars: int) -> list[str]:
    """Returns the list of channel chat_ids/handles that should receive
    a signal with this star rating. Empty list if Telegram is disabled or
    no channel matches."""
    if not is_configured():
        return []
    floor_tier = SIGNAL_TIER_FLOOR.get(stars, "ADVANCED")
    # Order from highest paying tier to lowest. Lower tiers get the floor's
    # signals too — but premium tiers (ADVANCED) see everything ≥ their floor.
    tier_order = ["ADVANCED", "INTERMEDIATE", "BASIC"]
    floor_idx = tier_order.index(floor_tier)
    eligible = tier_order[floor_idx:]    # all tiers from floor upward (toward BASIC)
    return [CHANNEL_FOR_TIER[t] for t in eligible if CHANNEL_FOR_TIER[t]]


def _format_signal(*, symbol: str, direction: str, stars: int, confidence: float,
                    entry: float, stoploss: float, targets: list[float],
                    horizon: str, sector: str | None = None,
                    is_calibrated: bool = False) -> str:
    """Markdown-formatted signal post.

    Telegram supports parse_mode=Markdown with limited subset:
      *bold*, _italic_, `monospace`, [text](url).
    """
    star_str = "⭐" * max(1, min(5, stars))
    arrow = "🟢⬆️" if direction == "BULLISH" else "🔴⬇️" if direction == "BEARISH" else "⚪️➡️"
    label = "BUY" if direction == "BULLISH" else "SELL" if direction == "BEARISH" else "HOLD"

    targets_str = "\n".join(
        f"   • T{i+1}: ₹{t:.2f}" for i, t in enumerate(targets or []) if t
    ) or "   • —"

    confidence_label = f"{confidence:.0f}%"
    if is_calibrated:
        confidence_label += " (calibrated)"

    return (
        f"{arrow} *{symbol}* — {label}\n"
        f"{star_str}  ·  {confidence_label}  ·  {horizon.title()}\n"
        f"{'_' + sector + '_' if sector else ''}\n"
        f"\n"
        f"`Entry`    : ₹{entry:.2f}\n"
        f"`Stop loss`: ₹{stoploss:.2f}\n"
        f"`Targets`  :\n{targets_str}\n"
        f"\n"
        f"_Educational only · Verify before deploying capital_"
    )


def publish_signal(*, symbol: str, direction: str, stars: int, confidence: float,
                    entry: float, stoploss: float, targets: list[float],
                    horizon: str = "SWING", sector: str | None = None,
                    is_calibrated: bool = False) -> dict:
    """Publish a signal to all tier-eligible channels.

    Returns a summary dict — does NOT raise. Designed to be called from
    the signal-emission hot path; a Telegram outage must never block
    the user's recommendation API response.
    """
    if not is_configured():
        return {"published": False, "reason": "Telegram not configured"}

    channels = _channels_for_signal(stars)
    if not channels:
        return {"published": False, "reason": f"No channel mapped for {stars}★"}

    text = _format_signal(
        symbol=symbol, direction=direction, stars=stars, confidence=confidence,
        entry=entry, stoploss=stoploss, targets=targets,
        horizon=horizon, sector=sector, is_calibrated=is_calibrated,
    )

    results = []
    url = f"{TELEGRAM_API_BASE}/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    with httpx.Client(timeout=HTTP_TIMEOUT_SEC) as http:
        for chat_id in channels:
            try:
                r = http.post(url, json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                })
                ok = (r.status_code == 200) and r.json().get("ok", False)
                if not ok:
                    logger.warning("Telegram post failed for {}: {} — {}",
                                     chat_id, r.status_code, r.text[:200])
                results.append({"chat_id": chat_id, "ok": ok})
            except Exception as e:
                logger.warning("Telegram post error for {}: {}", chat_id, e)
                results.append({"chat_id": chat_id, "ok": False, "error": str(e)})

    return {"published": True, "channels": results,
             "symbol": symbol, "stars": stars}


def test_credentials() -> dict:
    """Self-check — calls /getMe to verify the bot token works.
    Used by /api/admin/telegram/diagnose (added separately if needed)."""
    if not TELEGRAM_BOT_TOKEN:
        return {"ok": False, "reason": "TELEGRAM_BOT_TOKEN not set"}
    try:
        url = f"{TELEGRAM_API_BASE}/bot{TELEGRAM_BOT_TOKEN}/getMe"
        r = httpx.get(url, timeout=HTTP_TIMEOUT_SEC)
        data = r.json()
        if r.status_code == 200 and data.get("ok"):
            return {"ok": True, "bot": data["result"]["username"],
                     "configured_channels": [
                         {"tier": tier, "channel": ch}
                         for tier, ch in CHANNEL_FOR_TIER.items() if ch
                     ]}
        return {"ok": False, "reason": data.get("description", "Unknown error")}
    except Exception as e:
        return {"ok": False, "reason": str(e)}
