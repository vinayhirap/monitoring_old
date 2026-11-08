"""Hora (planetary hour) endpoint."""
from datetime import datetime, date as _date
from typing import Literal, Optional
from fastapi import APIRouter, HTTPException, Query

from app.engines import hora as hora_eng, consistency

router = APIRouter()


@router.get("/current", summary="Current planetary hora + bias")
def current_hora(asof: datetime | None = Query(None)):
    try:
        return hora_eng.current_hora(asof).to_dict()
    except Exception as e:
        raise HTTPException(500, f"hora failed: {e}")


@router.get(
    "/day-timeline",
    summary="Full intraday hora schedule — every window overlapping NSE 09:15–15:30",
    description=(
        "Returns every planetary hora that touches today's (or a given date's) "
        "NSE trading session, with start/end times, ruler, bias (bullish/"
        "bearish/neutral), weight (0..1), and human-readable notes. Unlike "
        "the older `next-window` lookup, this exposes ALL windows — so the "
        "user can see what hora was active during any minute of the session "
        "(e.g. why the market dropped during Saturn hora between 11:40 and 12:45)."
    ),
)
def day_timeline(
    date: Optional[str] = Query(None,
        description="ISO date YYYY-MM-DD; defaults to today (IST)"),
):
    try:
        import pytz
        from app.config import settings
        tz = pytz.timezone(settings.astro_timezone)
        if date:
            try:
                d = _date.fromisoformat(date)
            except ValueError:
                raise HTTPException(400, f"date must be YYYY-MM-DD, got {date!r}")
            anchor = tz.localize(datetime(d.year, d.month, d.day, 12, 0))
        else:
            anchor = datetime.now(tz)
        timeline = hora_eng.day_timeline(anchor)
        # Include the current hora so the UI has both views in one round-trip.
        cur = hora_eng.current_hora(anchor if date else None).to_dict()
        return {
            "date":      anchor.date().isoformat(),
            "weekday":   anchor.strftime("%A"),
            "timeline":  timeline,
            "current":   cur,
            "asof":      datetime.now(tz).isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"day-timeline failed: {e}")


@router.get(
    "/next-window",
    summary="Next benefic planetary-hora entry window for BUY or SELL",
    description=(
        "Scans the next ~16 horas forward and returns the first planetary "
        "hora that (a) matches the requested direction's bias and (b) falls "
        "within the NSE 09:15–15:30 session. The 'entry_time' is the *mid-"
        "point* of that hora to avoid the edges where the ruling planet "
        "changes. Returns the surrounding window too."
    ),
)
def next_window(
    direction: Literal["BUY", "SELL", "NEUTRAL"] = Query("BUY"),
    asof: datetime | None = Query(None),
    lookahead_horas: int = Query(16, ge=1, le=48),
):
    try:
        win = hora_eng.next_window(direction, asof=asof, lookahead_horas=lookahead_horas)
        return win.to_dict()
    except Exception as e:
        raise HTTPException(500, f"next-window failed: {e}")


@router.get("/validate-strategy", summary="Test the consistency validator against any strategy")
def validate_strategy(
    strategy_type: str = Query(..., examples=["OPT_CE_BUY"]),
    symbol_astro_bias: str = "BULLISH",
    numerology_bias: str = "BULLISH",
    market_bias: str = "NEUTRAL",
    mode: str = "strict",
):
    try:
        hora = hora_eng.current_hora().to_dict()
        result = consistency.validate(
            strategy_type=strategy_type,
            esoteric_components={
                "astrology":  {"bias": symbol_astro_bias},
                "numerology": {"bias": numerology_bias},
            },
            hora=hora,
            astro_market={"bias": market_bias},
            mode=mode,  # type: ignore
        )
        return {"hora": hora, "validation": result.to_dict()}
    except Exception as e:
        raise HTTPException(500, f"validation failed: {e}")
