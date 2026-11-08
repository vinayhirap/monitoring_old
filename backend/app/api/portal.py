"""Portal API — endpoints that the consumer-facing user portal uses.

These deliberately return *simplified* payloads — no engine internals, no
calibration metadata, no raw scores. Just what the user portal needs:

  • GET  /api/portal/me/watchlist      — list watchlist
  • POST /api/portal/me/watchlist      — add symbol
  • DEL  /api/portal/me/watchlist/{symbol}
  • GET  /api/portal/top-picks         — today's top BUY + SELL picks (cached, fast)
  • GET  /api/portal/market-pulse      — clean summary for the portal home

The admin endpoints in /api/recommend/* and /api/symbol/* still return
the full payload for the admin console.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from loguru import logger

from app.dependencies import get_db, get_current_user, require_tier, get_user_tier
from app.models.user import User, ADMIN_ROLES
from app.models.watchlist import WatchlistItem
from app.models.subscription import TIER_FEATURES

router = APIRouter()


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

class WatchlistAdd(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32)
    exchange: str = "NSE"


@router.get("/me/watchlist", summary="Get current user's watchlist")
def get_watchlist(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    items = (db.query(WatchlistItem)
             .filter(WatchlistItem.user_id == user.id)
             .order_by(WatchlistItem.sort_order, WatchlistItem.added_at)
             .all())
    return {
        "count": len(items),
        "items": [
            {"id": i.id, "symbol": i.symbol, "exchange": i.exchange,
             "added_at": i.added_at.isoformat() if i.added_at else None}
            for i in items
        ],
    }


@router.post("/me/watchlist", summary="Add a symbol to watchlist", status_code=201)
def add_watchlist(req: WatchlistAdd,
                   user_tier: Annotated[tuple[User, str], Depends(get_user_tier)],
                   db: Annotated[Session, Depends(get_db)]):
    user, tier = user_tier
    sym = req.symbol.upper().strip()
    exists = (db.query(WatchlistItem)
              .filter_by(user_id=user.id, symbol=sym, exchange=req.exchange)
              .one_or_none())
    if exists:
        return {"id": exists.id, "symbol": sym, "exchange": req.exchange, "already": True}

    # Tier-based watchlist size cap. -1 in TIER_FEATURES means unlimited.
    max_size = TIER_FEATURES.get(tier, {}).get("watchlist_size", 5)
    if max_size != -1:
        current = (db.query(WatchlistItem)
                    .filter(WatchlistItem.user_id == user.id)
                    .count())
        if current >= max_size:
            raise HTTPException(
                402,
                {
                    "message": (f"Watchlist limit reached ({max_size} for {tier} tier). "
                                 f"Upgrade your subscription for a larger watchlist."),
                    "current_tier": tier,
                    "current_size": current,
                    "max_size": max_size,
                    "upgrade_url": "/portal/profile",
                },
            )

    item = WatchlistItem(user_id=user.id, symbol=sym, exchange=req.exchange)
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "symbol": sym, "exchange": req.exchange, "added_at": item.added_at.isoformat()}


@router.delete("/me/watchlist/{symbol}", summary="Remove a symbol from watchlist")
def delete_watchlist(symbol: str,
                      user: Annotated[User, Depends(get_current_user)],
                      db: Annotated[Session, Depends(get_db)],
                      exchange: str = "NSE"):
    sym = symbol.upper().strip()
    n = (db.query(WatchlistItem)
         .filter_by(user_id=user.id, symbol=sym, exchange=exchange)
         .delete())
    db.commit()
    return {"removed": n}


# ---------------------------------------------------------------------------
# Top picks — simplified
# ---------------------------------------------------------------------------

@router.get("/top-picks", summary="Today's top BUY + SELL picks (simplified payload)")
def top_picks(
    user_tier: Annotated[tuple[User, str], Depends(get_user_tier)],
    horizon: str = Query("SWING", pattern="^(INTRADAY|SWING|POSITIONAL)$"),
    min_stars: int = Query(3, ge=1, le=5),
    top_n: int = Query(5, ge=1, le=20),
):
    """Returns a small simple list of picks. Internally uses the professional
    grade endpoint but strips the technical depth.

    Tier-based gating:
      • Only allow horizons the tier supports (FREE/BASIC = SWING only)
      • Force min_stars up to tier floor (FREE only sees 4★ and 5★ picks)
      • Cap top_n by tier (FREE = 5, BASIC = 10, INTERMEDIATE+ = 20)
    """
    user, tier = user_tier
    features = TIER_FEATURES.get(tier, TIER_FEATURES["FREE"])

    # Horizon gate — block unsupported horizons for lower tiers
    if horizon not in features["horizons_allowed"]:
        raise HTTPException(
            402,
            {
                "message": (f"Horizon '{horizon}' not available on {tier} tier. "
                             f"Allowed: {features['horizons_allowed']}."),
                "current_tier": tier,
                "required_tier": "INTERMEDIATE",
                "upgrade_url": "/portal/profile",
            },
        )

    # Floor min_stars to the tier's minimum-visible level
    effective_min_stars = max(min_stars, features["min_stars_visible"])

    # Cap top_n by tier (FREE caps tighter)
    tier_top_n_cap = {"FREE": 5, "BASIC": 10}.get(tier, 20)
    effective_top_n = min(top_n, tier_top_n_cap)

    try:
        # ---- Try cached snapshot first (populated by background scanner) ----
        # Falls back to inline scan if no snapshot for this (horizon,min_stars)
        # combination, or if the scanner isn't running.
        from app.jobs import picks_scanner
        from app.engines import recommender

        snapshot, is_stale = picks_scanner.latest_snapshot(horizon, effective_min_stars)
        if snapshot is not None and not is_stale:
            # Cached path — clip lists to user's top_n cap and return
            res = {
                "asof":     snapshot.get("asof"),
                "top_buy":  snapshot.get("top_buy", [])[:effective_top_n],
                "top_sell": snapshot.get("top_sell", [])[:effective_top_n],
                "_cached":  True,
                "_scanned_at": snapshot.get("_scanned_at"),
            }
        elif snapshot is not None and is_stale:
            # Stale row — return it but flag so UI can show "from N min ago"
            res = {
                "asof":     snapshot.get("asof"),
                "top_buy":  snapshot.get("top_buy", [])[:effective_top_n],
                "top_sell": snapshot.get("top_sell", [])[:effective_top_n],
                "_cached":  True,
                "_is_stale": True,
                "_scanned_at": snapshot.get("_scanned_at"),
            }
        else:
            # No snapshot at all — inline scan (legacy path)
            res = recommender.professional_scan(
                horizon=horizon, capital=100_000, min_stars=effective_min_stars,
                top_n=effective_top_n, quick=True,
            )
            res["_cached"] = False
        def _strip(p):
            """Map the full scanner output → simplified portal shape."""
            g = p.get("grade", {})
            raw = p.get("raw_signal", {})
            return {
                "symbol": p["symbol"],
                "sector": p.get("sector"),
                "label": g.get("conviction_label"),
                "stars": g.get("stars"),
                "direction": g.get("direction"),
                "confidence": g.get("confidence"),
                "entry": raw.get("entry"),
                "stoploss": raw.get("stoploss"),
                "targets": raw.get("targets", []),
                "best_instrument": (g.get("instrument_ranking", [{}])[0] or {}).get("instrument"),
                "best_subtype":    (g.get("instrument_ranking", [{}])[0] or {}).get("subtype"),
            }

        # Cached results were stripped by the scanner at write time, so they're
        # already in the portal shape — `_strip()` would double-strip and zero
        # out the fields. Inline-scan results are raw and need stripping.
        if res.get("_cached"):
            top_buy_out  = res.get("top_buy", [])
            top_sell_out = res.get("top_sell", [])
        else:
            top_buy_out  = [_strip(p) for p in res.get("top_buy", [])]
            top_sell_out = [_strip(p) for p in res.get("top_sell", [])]

        # ---- Live tape consistency check ----
        # The scanner runs on daily bars + an astro snapshot, but by the time
        # the user opens the page the intraday tape may have moved opposite
        # to the rated direction. Enrich each pick with live LTP + day-change %
        # + a `live_verdict` that downgrades the original verdict when the
        # tape contradicts (BULLISH pick down -1%) OR when the current hora
        # is opposite the trade direction with high weight (Saturn/Mars).
        try:
            from app.services import tape_consistency
            from app.engines import hora as hora_eng
            try:
                cur_hora = hora_eng.current_hora().to_dict()
            except Exception:
                cur_hora = None
            top_buy_out  = tape_consistency.enrich_picks(top_buy_out, hora=cur_hora)
            top_sell_out = tape_consistency.enrich_picks(top_sell_out, hora=cur_hora)
        except Exception as e:
            logger.debug("tape_consistency enrichment skipped: {}", e)

        return {
            "asof": res.get("asof"),
            "horizon": horizon,
            "top_buy":  top_buy_out,
            "top_sell": top_sell_out,
            # Cache-status flags so UI can show "live scan" vs "from 8 min ago"
            "is_cached":     bool(res.get("_cached")),
            "is_stale":      bool(res.get("_is_stale")),
            "scanned_at":    res.get("_scanned_at"),
            "disclaimer": "Educational only. Verify before deploying capital.",
            # Echo tier context so the UI can show "Upgrade to see more" hints
            # when the caller's requested params were silently capped.
            "tier_applied": {
                "current_tier": tier,
                "min_stars_requested": min_stars,
                "min_stars_used":      effective_min_stars,
                "top_n_requested":     top_n,
                "top_n_used":          effective_top_n,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"top picks failed: {e}")


# ---------------------------------------------------------------------------
# Market pulse — minimal payload for the portal home
# ---------------------------------------------------------------------------

@router.get("/history", summary="Recent recommendation history (last 14 days by default)")
def portal_history(
    user: Annotated[User, Depends(require_tier("BASIC"))],
    days: int = Query(14, ge=1, le=14, description="Max 14-day retention"),
    symbol: str | None = None,
    limit: int = Query(100, ge=1, le=500),
):
    """Portal-facing history. Capped at 14 days (matches retention policy).
    Gated to BASIC+ — FREE tier cannot see historical signal performance."""
    from app.services import signals_logger
    if symbol:
        rows = signals_logger.history_for_symbol(symbol, days=days, limit=limit)
    else:
        rows = signals_logger.recent_signals(days=days, limit=limit)
    return {"count": len(rows), "rows": rows, "retention_days": 14}


@router.get("/daily-forecast/{symbol}",
             summary="14-day forecast — astrology details hidden for USER role, exposed for admin")
def daily_forecast(symbol: str,
                    user: Annotated[User, Depends(require_tier("BASIC"))],
                    days: int = Query(14, ge=1, le=14)):
    """14 calendar days of forecast bias for one symbol/index/commodity.

    Response shape varies by caller's role:
      • USER → clean view: date, bias, confidence, range, entry windows,
        sanitized events. No nakshatra/day-lord/tara/tithi.
      • ADMIN/OWNER/ANALYST → full view with all astrology internals so
        researchers can trace WHY the engine produced the bias.
    """
    try:
        from app.engines import daily_astro_forecast
        view = "admin" if user.role in ADMIN_ROLES else "user"
        return daily_astro_forecast.forecast(symbol.upper(), days=days, view=view)
    except Exception as e:
        raise HTTPException(500, f"daily forecast failed: {e}")


@router.get("/market-pulse", summary="Clean market summary for portal home")
def market_pulse(user: Annotated[User, Depends(get_current_user)]):
    try:
        from app.engines import astrology as astro_eng, hora as hora_eng
        sent = astro_eng.market_sentiment(datetime.now()).to_dict()
        hora = hora_eng.current_hora().to_dict()
        phase = astro_eng.moon_phase(datetime.now())
        return {
            "asof": datetime.now().isoformat(),
            "market_bias": sent.get("bias"),
            "market_score": sent.get("score"),
            "headline": sent.get("headline"),
            "hora": {
                "ruler": hora.get("ruler"),
                "bias": hora.get("bias"),
                "next_ruler": hora.get("next_ruler"),
                "next_change_minutes": hora.get("next_change_in_minutes"),
            },
            "moon": {
                "phase": phase.get("phase"),
                "paksha": phase.get("paksha"),
                "tithi": phase.get("tithi"),
            },
        }
    except Exception as e:
        raise HTTPException(500, f"market pulse failed: {e}")


# ---------------------------------------------------------------------------
# Sector-wise BUY / SELL recommendations
# ---------------------------------------------------------------------------

@router.get("/sector-picks",
             summary="Recommendations grouped by sector — BUY/SELL count per sector + top pick")
def sector_picks(
    user_tier: Annotated[tuple[User, str], Depends(get_user_tier)],
    horizon: str = Query("SWING", pattern="^(INTRADAY|SWING|POSITIONAL)$"),
    min_stars: int = Query(3, ge=1, le=5),
):
    """Aggregates the current top-picks by sector. Returns:

      • per-sector count of bullish vs bearish picks
      • net sentiment (bullish - bearish) for sector heatmap colouring
      • top BUY pick and top SELL pick per sector
      • aggregate confidence average

    Same tier gates as /top-picks — horizon + min_stars are floored to the
    user's tier limits. FREE/BASIC capped to SWING only.
    """
    user, tier = user_tier
    features = TIER_FEATURES.get(tier, TIER_FEATURES["FREE"])

    # Reuse the same horizon/min_stars gates as top-picks
    if horizon not in features["horizons_allowed"]:
        raise HTTPException(
            402,
            {
                "message": (f"Horizon '{horizon}' not available on {tier} tier."),
                "current_tier": tier,
                "required_tier": "INTERMEDIATE",
                "upgrade_url": "/portal/profile",
            },
        )
    effective_min_stars = max(min_stars, features["min_stars_visible"])

    # Reuse the cached scanner output when available
    try:
        from app.jobs import picks_scanner
        snapshot, _ = picks_scanner.latest_snapshot(horizon, effective_min_stars)
        if snapshot is None:
            from app.engines import recommender
            res = recommender.professional_scan(
                horizon=horizon, capital=100_000,
                min_stars=effective_min_stars, top_n=20, quick=True,
            )
            top_buy  = [{"symbol": p["symbol"], "sector": p.get("sector"),
                          "stars": (p.get("grade") or {}).get("stars"),
                          "confidence": (p.get("grade") or {}).get("confidence"),
                          "direction": "BULLISH"}
                         for p in res.get("top_buy", [])]
            top_sell = [{"symbol": p["symbol"], "sector": p.get("sector"),
                          "stars": (p.get("grade") or {}).get("stars"),
                          "confidence": (p.get("grade") or {}).get("confidence"),
                          "direction": "BEARISH"}
                         for p in res.get("top_sell", [])]
        else:
            top_buy  = [{**p, "direction": "BULLISH"} for p in snapshot.get("top_buy", [])]
            top_sell = [{**p, "direction": "BEARISH"} for p in snapshot.get("top_sell", [])]

        # Group by sector
        sector_map: dict[str, dict] = {}
        for p in (top_buy + top_sell):
            sector = (p.get("sector") or "Other").strip() or "Other"
            sm = sector_map.setdefault(sector, {
                "sector": sector,
                "bullish_count": 0, "bearish_count": 0,
                "bullish_picks": [], "bearish_picks": [],
                "confidence_sum": 0.0, "count": 0,
            })
            if p["direction"] == "BULLISH":
                sm["bullish_count"] += 1
                sm["bullish_picks"].append(p)
            else:
                sm["bearish_count"] += 1
                sm["bearish_picks"].append(p)
            sm["confidence_sum"] += (p.get("confidence") or 0)
            sm["count"] += 1

        # Build final list — sorted by net sentiment (bullish - bearish)
        sectors = []
        for sm in sector_map.values():
            net = sm["bullish_count"] - sm["bearish_count"]
            avg_conf = sm["confidence_sum"] / sm["count"] if sm["count"] else 0
            # Top BUY = highest confidence in bullish_picks, same for SELL
            top_buy_pick  = max(sm["bullish_picks"], key=lambda x: x.get("confidence", 0), default=None)
            top_sell_pick = max(sm["bearish_picks"], key=lambda x: x.get("confidence", 0), default=None)
            # Sector bias label
            if net >= 2:    bias = "BULLISH"
            elif net <= -2: bias = "BEARISH"
            else:           bias = "MIXED"
            sectors.append({
                "sector":         sm["sector"],
                "bullish_count":  sm["bullish_count"],
                "bearish_count":  sm["bearish_count"],
                "total":          sm["count"],
                "net_sentiment":  net,
                "avg_confidence": round(avg_conf, 1),
                "bias":           bias,
                "top_buy":        top_buy_pick,
                "top_sell":       top_sell_pick,
                "all_picks":      sm["bullish_picks"] + sm["bearish_picks"],
            })
        sectors.sort(key=lambda s: s["net_sentiment"], reverse=True)

        return {
            "horizon":       horizon,
            "min_stars_used": effective_min_stars,
            "current_tier":  tier,
            "sectors":       sectors,
            "total_sectors": len(sectors),
            "total_picks":   sum(s["total"] for s in sectors),
            "disclaimer":    "Educational only. Verify every recommendation before risking capital.",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"sector picks failed: {e}")


# ---------------------------------------------------------------------------
# Intraday F&O — daily-bias-aligned picks with suggested option + futures
# ---------------------------------------------------------------------------

@router.get("/astro-intraday-fno",
             summary="Today's intraday picks aligned with daily bias + suggested option + futures level")
def astro_intraday_fno(
    user_tier: Annotated[tuple[User, str], Depends(get_user_tier)],
    min_stars: int = Query(3, ge=1, le=5),
    top_n: int = Query(8, ge=1, le=20),
):
    """Composite endpoint that ties three things together for intraday traders:

      1. **Today's market bias** from the daily astrology forecast on NIFTY —
         BULLISH / BEARISH / NEUTRAL with a confidence score.
      2. **Intraday picks** that align with that bias (BULLISH picks on
         bullish days, BEARISH on bearish; on NEUTRAL days, show both).
         Astrology is one input — direction selection is dominated by
         price-action signals (technical + advanced TA + SMC).
      3. **F&O suggestions** for each pick — the nearest ATM CE (for BUY)
         or PE (for SELL) with strike + premium + lot size + max-pain
         context, plus the futures price + expiry.

    Tier-gated to INTERMEDIATE+ (intraday horizon is gated already, plus
    options data is INTERMEDIATE-only feature).
    """
    user, tier = user_tier
    features = TIER_FEATURES.get(tier, TIER_FEATURES["FREE"])
    if "INTRADAY" not in features["horizons_allowed"]:
        raise HTTPException(
            402,
            {
                "message": ("Intraday F&O picks require INTERMEDIATE or higher. "
                              f"Your tier: {tier}."),
                "current_tier": tier,
                "required_tier": "INTERMEDIATE",
                "upgrade_url": "/portal/profile",
            },
        )
    if not features.get("fno_recommendations"):
        raise HTTPException(
            402,
            {
                "message": ("F&O recommendations require INTERMEDIATE or higher. "
                              f"Your tier: {tier}."),
                "current_tier": tier,
                "required_tier": "INTERMEDIATE",
                "upgrade_url": "/portal/profile",
            },
        )

    effective_min_stars = max(min_stars, features["min_stars_visible"])

    try:
        # ---- 1. Today's daily bias from the NIFTY forecast ----
        from app.engines import daily_astro_forecast
        view = "admin" if user.role in ADMIN_ROLES else "user"
        nifty_forecast = daily_astro_forecast.forecast("NIFTY", days=1, view=view)
        today_bar = (nifty_forecast.get("days") or [{}])[0]
        # User view returns confidence, admin view returns astro_score
        day_strength = today_bar.get("confidence", today_bar.get("astro_score", 50))
        day_bias = today_bar.get("bias", "NEUTRAL")
        if day_bias == "MARKET_CLOSED":
            return {
                "as_of":              today_bar.get("date"),
                "day_bias":           "MARKET_CLOSED",
                "day_strength":       0,
                "intraday_picks":     [],
                "message":            "NSE is closed today. Check back next trading day.",
            }

        # ---- 2. Intraday top picks ----
        from app.jobs import picks_scanner
        snapshot, _ = picks_scanner.latest_snapshot("INTRADAY", effective_min_stars)
        if snapshot is None:
            from app.engines import recommender
            res = recommender.professional_scan(
                horizon="INTRADAY", capital=100_000,
                min_stars=effective_min_stars, top_n=20, quick=True,
            )
            buy_picks  = [{"symbol": p["symbol"], "sector": p.get("sector"),
                            "stars": (p.get("grade") or {}).get("stars"),
                            "confidence": (p.get("grade") or {}).get("confidence"),
                            "entry": (p.get("raw_signal") or {}).get("entry"),
                            "stoploss": (p.get("raw_signal") or {}).get("stoploss"),
                            "targets": (p.get("raw_signal") or {}).get("targets", []),
                            "direction": "BULLISH"}
                           for p in res.get("top_buy", [])]
            sell_picks = [{"symbol": p["symbol"], "sector": p.get("sector"),
                            "stars": (p.get("grade") or {}).get("stars"),
                            "confidence": (p.get("grade") or {}).get("confidence"),
                            "entry": (p.get("raw_signal") or {}).get("entry"),
                            "stoploss": (p.get("raw_signal") or {}).get("stoploss"),
                            "targets": (p.get("raw_signal") or {}).get("targets", []),
                            "direction": "BEARISH"}
                           for p in res.get("top_sell", [])]
        else:
            buy_picks  = [{**p, "direction": "BULLISH"} for p in (snapshot.get("top_buy")  or [])]
            sell_picks = [{**p, "direction": "BEARISH"} for p in (snapshot.get("top_sell") or [])]

        # ---- 3. Align with day bias ----
        # On a bullish day, prefer BUY picks; on bearish, prefer SELL.
        # On neutral, show both. Picks NOT aligned with the day's bias
        # get a small "contrarian" flag — useful info, not auto-hidden.
        all_picks = buy_picks + sell_picks
        if day_bias == "BULLISH":
            aligned   = [p for p in all_picks if p["direction"] == "BULLISH"]
            contrarian = [p for p in all_picks if p["direction"] == "BEARISH"]
        elif day_bias == "BEARISH":
            aligned   = [p for p in all_picks if p["direction"] == "BEARISH"]
            contrarian = [p for p in all_picks if p["direction"] == "BULLISH"]
        else:
            aligned   = all_picks
            contrarian = []

        # Sort by confidence × stars (composite quality score)
        def _quality(p):
            return (p.get("confidence") or 0) * 0.7 + (p.get("stars") or 0) * 6
        aligned.sort(key=_quality, reverse=True)
        aligned = aligned[:top_n]

        # ---- 4. Enrich each pick with F&O suggestion ----
        enriched = []
        for p in aligned:
            enriched.append(_enrich_with_fno(p))

        # ---- 5. Best entry windows (from the day forecast) ----
        best_entry_windows = today_bar.get("best_entry_windows", [])

        return {
            "as_of":              today_bar.get("date"),
            "day_bias":           day_bias,
            "day_strength":       round(day_strength, 1) if day_strength else 50,
            "best_entry_windows": best_entry_windows,
            "expected_range_pct": today_bar.get("expected_range_pct"),
            "intraday_picks":     enriched,
            "contrarian_count":   len(contrarian),
            "current_tier":       tier,
            "disclaimer": (
                "Intraday F&O carries amplified risk. Use strict stops, "
                "and never risk more than 2% of capital per trade. "
                "Educational only."
            ),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"astro intraday F&O failed: {e}")


def _enrich_with_fno(pick: dict) -> dict:
    """For a single pick, compute the suggested ATM option strike + futures
    contract. Failures degrade gracefully — the pick is still returned with
    `fno: None` so the UI shows what it can.

    Strike selection logic:
      BULLISH → ATM Call (CE) — closest strike at or above spot
      BEARISH → ATM Put (PE)  — closest strike at or below spot
    """
    out = {**pick, "fno": None}
    try:
        from app.engines import options as options_eng
        from app.brokers.angelone import broker_instance
        from app.services.market_data import get_option_chain
        from datetime import date, timedelta

        sym = pick["symbol"]
        spot = float(pick.get("entry") or 0)
        if spot <= 0:
            return out

        # Nearest Thursday expiry
        today = date.today()
        days_to_thu = (3 - today.weekday()) % 7 or 7
        expiry = today + timedelta(days=days_to_thu)

        # Try live chain; fall back to synthetic so the page always has something
        chain: list[dict] = []
        try:
            if broker_instance.is_authenticated():
                chain = get_option_chain(sym, expiry) or []
        except Exception:
            pass
        if not chain:
            chain = options_eng.synthetic_chain(sym, spot)

        # Pick strike based on direction
        if pick["direction"] == "BULLISH":
            # ATM CE = nearest strike at or above spot
            candidates = [c for c in chain if c["strike"] >= spot]
            best = min(candidates, key=lambda c: c["strike"] - spot) if candidates \
                   else min(chain, key=lambda c: abs(c["strike"] - spot))
            leg = "CE"
            premium = best.get("ce_ltp") or 0
            iv = best.get("ce_iv") or 0
            oi = best.get("ce_oi") or 0
        else:
            candidates = [c for c in chain if c["strike"] <= spot]
            best = max(candidates, key=lambda c: c["strike"]) if candidates \
                   else min(chain, key=lambda c: abs(c["strike"] - spot))
            leg = "PE"
            premium = best.get("pe_ltp") or 0
            iv = best.get("pe_iv") or 0
            oi = best.get("pe_oi") or 0

        # Lot size — pull from instruments lookup
        lot_size = _safe_lot_size(sym)

        # Standard intraday-options exit triggers — 50% stop, 100%/150% targets
        sl_premium = round(premium * 0.50, 2) if premium else None
        t1_premium = round(premium * 1.50, 2) if premium else None    # +50% gain
        t2_premium = round(premium * 2.00, 2) if premium else None    # +100% gain

        out["fno"] = {
            "expiry":      expiry.isoformat(),
            "strike":      best["strike"],
            "leg":         leg,                         # "CE" or "PE"
            "premium":     round(float(premium), 2),
            "lot_size":    lot_size,
            "iv_pct":      round(float(iv) * 100, 1) if iv else None,
            "open_interest": int(oi) if oi else None,
            "sl_premium":  sl_premium,
            "target_1":    t1_premium,
            "target_2":    t2_premium,
            "notional":    round(premium * lot_size, 2) if (premium and lot_size) else None,
            "future_price_proxy": spot,    # cash-future basis usually <0.5%
        }
        return out
    except Exception as e:
        logger.debug("fno enrichment failed for {}: {}", pick.get("symbol"), e)
        return out


def _safe_lot_size(symbol: str) -> int:
    """Best-effort lot-size lookup. Falls back to 1 if we can't determine
    the F&O lot — the UI can still render premium / notional based on 1."""
    try:
        from app.services import instruments
        # If your instruments module exposes lot-size, wire it here. Else
        # use a static map of well-known symbols. Default to 1.
        row = instruments.lookup(symbol, "NFO") if hasattr(instruments, "lookup") else None
        if row and row.get("lotsize"):
            return int(row["lotsize"])
    except Exception:
        pass
    # Common Nifty/Bank-Nifty defaults (Apr 2026 lot sizes — verify before live)
    KNOWN = {
        "NIFTY":     25, "BANKNIFTY": 15, "FINNIFTY":  25,
        "RELIANCE": 250, "TCS":       150, "HDFCBANK": 550,
        "INFY":     300, "ICICIBANK": 700, "AXISBANK": 625,
        "SBIN":     750, "ITC":     1600, "HDFC":     300,
    }
    return KNOWN.get(symbol.upper(), 1)
