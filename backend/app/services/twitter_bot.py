"""Twitter / X track-record bot — public timestamped signal feed.

Why this matters (strategic):

The single highest-leverage credibility move for an unregistered trading
platform is a PUBLIC, IMMUTABLE track record. Posting every signal to
Twitter at emission time creates:
  • A timestamp no competitor can fake retroactively
  • Verifiable performance — anyone can check what you posted vs what
    actually happened
  • Continuous proof that the system was being used (not just claimed)
  • SEBI-friendly evidence that the platform is "education" if you make
    the framing right

When to enable:
  Once you have the X API Basic tier subscription ($200/mo as of 2025).
  The free tier allows only ~500 tweets/month with strict rate limits;
  the platform's ~50-100 signals/day exceeds it.

How to enable:
  1. Apply for X Developer account → upgrade to Basic tier
  2. Create a project + app at developer.x.com
  3. Set in backend/.env:
        TWITTER_BEARER_TOKEN=<bearer token from app settings>
        TWITTER_API_KEY=<consumer key>
        TWITTER_API_SECRET=<consumer secret>
        TWITTER_ACCESS_TOKEN=<access token>
        TWITTER_ACCESS_SECRET=<access token secret>
  4. Restart backend. Module logs whether config is valid on startup.

Module behavior:

When configured:
  • `post_signal()` is called by the picks scanner on every NEW signal
    that appears (same diff logic as Telegram bot).
  • Format: short, professional. Symbol, direction, entry/SL/T1,
    confidence, timestamp. ~200 char tweets.
  • Educational disclaimer included.

When NOT configured:
  • All public functions are no-ops. Backend runs identically; no
  spurious errors.

What this module DOES NOT do (yet):
  • Reply handling (engagement). Currently posts only.
  • Outcome follow-up tweets (post-fact "we said BUY at X, hit T1 at Y").
    Worth adding — clean way to display the track record. See TODO.
  • Twitter Lists per tier. Currently single feed.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

import httpx
from loguru import logger


# ----- Config -----
TWITTER_BEARER       = os.getenv("TWITTER_BEARER_TOKEN", "").strip()
TWITTER_API_KEY      = os.getenv("TWITTER_API_KEY", "").strip()
TWITTER_API_SECRET   = os.getenv("TWITTER_API_SECRET", "").strip()
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN", "").strip()
TWITTER_ACCESS_SECRET = os.getenv("TWITTER_ACCESS_SECRET", "").strip()

# Disclaimer suffix appended to every tweet. Keeps signal posts within
# the platform's "educational" framing.
DISCLAIMER = "Educational. Not advice."

# Min star rating to publish — avoids polluting the feed with marginal signals.
MIN_STARS_FOR_TWITTER = int(os.getenv("TWITTER_MIN_STARS", "4"))


def is_configured() -> bool:
    """Twitter posting requires OAuth 1.0a User Context (bearer token alone
    is read-only). All four user-context fields must be present."""
    return bool(TWITTER_API_KEY and TWITTER_API_SECRET
                  and TWITTER_ACCESS_TOKEN and TWITTER_ACCESS_SECRET)


def _format_signal(*, symbol: str, direction: str, stars: int, confidence: float,
                    entry: float, stoploss: float, targets: list[float],
                    horizon: str) -> str:
    """X tweet max is 280 chars. We aim for ~220 to leave room for disclaimer
    and emoji rendering."""
    arrow = "📈" if direction == "BULLISH" else "📉" if direction == "BEARISH" else "↔️"
    label = "BUY" if direction == "BULLISH" else "SELL" if direction == "BEARISH" else "HOLD"
    star_str = "⭐" * max(1, min(5, stars))
    t1 = targets[0] if targets else None
    lines = [
        f"{arrow} {symbol} — {label} {star_str}",
        f"Entry ₹{entry:.2f} · SL ₹{stoploss:.2f}" + (f" · T1 ₹{t1:.2f}" if t1 else ""),
        f"Confidence: {confidence:.0f}% · {horizon.title()}",
        f"#{symbol} #StockMarket #Trading",
        DISCLAIMER,
    ]
    return "\n".join(lines)[:280]


# ----------------------------------------------------------------------------
# Posting via tweepy if available, else direct API v2
# ----------------------------------------------------------------------------

def _post_via_tweepy(text: str) -> dict:
    """Preferred path — tweepy abstracts OAuth signing."""
    import tweepy  # type: ignore
    client = tweepy.Client(
        consumer_key=TWITTER_API_KEY, consumer_secret=TWITTER_API_SECRET,
        access_token=TWITTER_ACCESS_TOKEN, access_token_secret=TWITTER_ACCESS_SECRET,
    )
    response = client.create_tweet(text=text)
    return {"ok": True, "tweet_id": getattr(response.data, "id", None)}


def _post_via_httpx(text: str) -> dict:
    """Fallback when tweepy isn't installed. Uses OAuth1 via requests_oauthlib
    if available; otherwise returns a soft failure rather than crashing."""
    try:
        from requests_oauthlib import OAuth1  # type: ignore
    except ImportError:
        return {"ok": False,
                 "error": "Neither tweepy nor requests-oauthlib installed. "
                          "pip install tweepy"}
    auth = OAuth1(TWITTER_API_KEY, TWITTER_API_SECRET,
                   TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET)
    r = httpx.post("https://api.twitter.com/2/tweets",
                    json={"text": text}, auth=auth, timeout=10)
    if r.status_code in (200, 201):
        data = r.json().get("data", {})
        return {"ok": True, "tweet_id": data.get("id")}
    return {"ok": False, "error": f"{r.status_code} {r.text[:200]}"}


def post_signal(*, symbol: str, direction: str, stars: int, confidence: float,
                 entry: float, stoploss: float, targets: list[float],
                 horizon: str = "SWING") -> dict:
    """Post a single signal to Twitter. Returns a result dict — never raises.

    Called from the picks scanner's new-signal diff (same callsite as the
    Telegram bot). Throttled by MIN_STARS_FOR_TWITTER — marginal signals
    don't pollute the feed.
    """
    if not is_configured():
        return {"posted": False, "reason": "Twitter not configured"}
    if stars < MIN_STARS_FOR_TWITTER:
        return {"posted": False, "reason": f"Below {MIN_STARS_FOR_TWITTER}★ floor"}

    text = _format_signal(
        symbol=symbol, direction=direction, stars=stars, confidence=confidence,
        entry=entry, stoploss=stoploss, targets=targets, horizon=horizon,
    )

    try:
        # Prefer tweepy; fall back to direct OAuth1 + httpx
        try:
            result = _post_via_tweepy(text)
        except ImportError:
            result = _post_via_httpx(text)
    except Exception as e:
        logger.warning("Twitter post failed for {}: {}", symbol, e)
        return {"posted": False, "error": str(e)}

    if result.get("ok"):
        logger.info("Tweeted {} signal (tweet_id={})", symbol, result.get("tweet_id"))
        return {"posted": True, "tweet_id": result.get("tweet_id"),
                 "text": text, "posted_at": datetime.utcnow().isoformat()}
    else:
        logger.warning("Twitter post returned non-OK: {}", result)
        return {"posted": False, "error": result.get("error")}


def diagnose() -> dict:
    """Self-check for /api/health and /api/admin/twitter/diagnose.
    Verifies OAuth credentials by attempting a read-only GET /users/me call.
    Does NOT post a tweet (so it's safe to call from health checks)."""
    if not is_configured():
        return {"ok": False, "reason": "Twitter credentials not configured"}
    try:
        from requests_oauthlib import OAuth1  # type: ignore
        auth = OAuth1(TWITTER_API_KEY, TWITTER_API_SECRET,
                       TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET)
        r = httpx.get("https://api.twitter.com/2/users/me", auth=auth, timeout=5)
        if r.status_code == 200:
            return {"ok": True, "user": r.json().get("data")}
        return {"ok": False, "reason": f"{r.status_code} {r.text[:200]}"}
    except Exception as e:
        return {"ok": False, "reason": str(e)}
