"""Pydantic schemas for analysis I/O."""
from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, Field


class AnalysisRequest(BaseModel):
    symbol: str = Field(..., examples=["RELIANCE"])
    exchange: str = Field("NSE", examples=["NSE", "BSE", "NFO"])
    timeframe: str = Field("1d", examples=["5m", "15m", "1h", "1d"])
    horizon: Literal["INTRADAY", "SWING", "POSITIONAL"] = "SWING"
    capital: float = Field(100000.0, gt=0)


class EngineScore(BaseModel):
    score: float                   # 0..100
    bias: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    reason: str
    details: dict = {}


class FullAnalysis(BaseModel):
    symbol: str
    exchange: str
    timeframe: str
    horizon: str
    asof: datetime

    signal: Literal["STRONG_BUY", "BUY", "NEUTRAL", "SELL", "STRONG_SELL"]
    trend: Literal["BULLISH", "BEARISH", "SIDEWAYS"]
    confidence: float

    entry: float
    stoploss: float
    targets: list[float]
    risk_reward: float
    capital_allocation_pct: float

    engines: dict[str, EngineScore]    # {technical, astrology, gann, numerology, options}
    reasons: dict[str, str]
    disclaimer: str = (
        "Educational/analytical use only. Not SEBI-registered advice. "
        "Astrology & numerology are confluence layers, not guaranteed predictors."
    )


class AstroTransitsResponse(BaseModel):
    asof: datetime
    timezone: str
    ayanamsa: str
    planets: dict             # {Sun: {long, sign, nakshatra, retrograde, ...}, ...}
    moon_phase: dict
    market_sentiment: dict


class NumerologyResponse(BaseModel):
    symbol: str
    pythagorean: dict
    chaldean: dict
    today_date_number: int
    compatibility_with_today: float
    planetary_ruler: str
    interpretation: str


class GannSquare9Request(BaseModel):
    price: float
    levels: int = Field(8, ge=1, le=16)


class GannSquare9Response(BaseModel):
    anchor_price: float
    supports: list[dict]      # [{angle:90, price:..., type:'support'}, ...]
    resistances: list[dict]
    natural_angles: list[dict]


class GannCyclesRequest(BaseModel):
    anchor_date: date
    cycles: list[int] = [30, 45, 60, 90, 120, 144, 180, 270, 360]


class GannCyclesResponse(BaseModel):
    anchor_date: date
    projected_dates: list[dict]


class OptionsAnalyzeRequest(BaseModel):
    symbol: str
    spot_price: float
    expiry: date
    chain: list[dict]   # [{strike, ce_oi, ce_iv, ce_ltp, pe_oi, pe_iv, pe_ltp}, ...]


class OptionsAnalyzeResponse(BaseModel):
    pcr: float
    max_pain: float
    bias: str
    suggested_strategy: str
    institutional_view: str
    greeks_atm: dict
