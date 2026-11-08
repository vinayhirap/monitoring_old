"""Subscription tier model — kept separate from User so we don't need a
migration on the existing users table.

Tiers (visibility ladder):
  • FREE         — limited (5 picks/day, no F&O, no commodities, no live)
  • BASIC        — full equity recommendations, 1 horizon (SWING)
  • INTERMEDIATE — all horizons, F&O included, MCX commodities
  • ADVANCED     — all of the above + intraday options strikes + Telegram pro channel

When wired to Telegram (separately), each tier has a dedicated channel ID
that admins add the user to on payment confirmation.
"""
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Boolean

from app.database import Base


SUBSCRIPTION_TIERS = ("FREE", "BASIC", "INTERMEDIATE", "ADVANCED")


# Public price list (INR/month). Used by the /payments/razorpay/config endpoint
# so the frontend can render prices on the tier-comparison card and decide what
# amount to charge. Keep in sync with the Razorpay dashboard plans.
TIER_PRICING_INR: dict[str, int] = {
    "FREE":         0,
    "BASIC":        499,
    "INTERMEDIATE": 1499,
    "ADVANCED":     2999,
}


class Subscription(Base):
    __tablename__ = "subscriptions"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    user_id      = Column(Integer, ForeignKey("users.id"), unique=True, index=True, nullable=False)
    tier         = Column(String(16), default="FREE", nullable=False)
    is_active    = Column(Boolean, default=True)
    valid_until  = Column(DateTime, nullable=True)              # None = no expiry (paid lifetime / FREE)
    started_at   = Column(DateTime, default=datetime.utcnow)
    telegram_username = Column(String(64), nullable=True)        # for channel-add automation
    telegram_chat_id  = Column(String(32), nullable=True)        # filled when user DMs the bot
    notes        = Column(String(512), nullable=True)


# Feature matrix — used by the gating service to decide what each tier sees.
TIER_FEATURES: dict[str, dict] = {
    "FREE": {
        "max_picks_per_day":     5,
        "horizons_allowed":      ["SWING"],
        "fno_recommendations":   False,
        "commodities":           False,
        "live_options_strategy": False,
        "watchlist_size":        5,
        "intraday_signals":      False,
        "min_stars_visible":     4,           # only show top-tier picks
        "delay_minutes":         15,          # delayed signals
        "telegram_channel":      None,
    },
    "BASIC": {
        "max_picks_per_day":     20,
        "horizons_allowed":      ["SWING"],
        "fno_recommendations":   False,
        "commodities":           False,
        "live_options_strategy": False,
        "watchlist_size":        20,
        "intraday_signals":      False,
        "min_stars_visible":     3,
        "delay_minutes":         5,
        "telegram_channel":      "BASIC",
    },
    "INTERMEDIATE": {
        "max_picks_per_day":     50,
        "horizons_allowed":      ["INTRADAY", "SWING", "POSITIONAL"],
        "fno_recommendations":   True,
        "commodities":           True,
        "live_options_strategy": True,
        "watchlist_size":        50,
        "intraday_signals":      True,
        "min_stars_visible":     2,
        "delay_minutes":         0,
        "telegram_channel":      "INTERMEDIATE",
    },
    "ADVANCED": {
        "max_picks_per_day":     -1,           # unlimited
        "horizons_allowed":      ["INTRADAY", "SWING", "POSITIONAL"],
        "fno_recommendations":   True,
        "commodities":           True,
        "live_options_strategy": True,
        "watchlist_size":        -1,           # unlimited
        "intraday_signals":      True,
        "min_stars_visible":     1,
        "delay_minutes":         0,
        "telegram_channel":      "ADVANCED",
    },
}
