"""Broker / order schemas."""
from typing import Literal
from pydantic import BaseModel, Field


class BrokerLoginRequest(BaseModel):
    """Optional override; defaults pulled from settings."""
    api_key: str | None = None
    client_code: str | None = None
    password: str | None = None
    totp: str | None = None


class BrokerLoginResponse(BaseModel):
    status: str
    message: str
    paper_mode: bool
    profile: dict | None = None


class OrderRequest(BaseModel):
    symbol: str = Field(..., examples=["RELIANCE-EQ"])
    exchange: str = Field("NSE", examples=["NSE", "BSE", "NFO", "MCX"])
    transaction_type: Literal["BUY", "SELL"]
    order_type: Literal["MARKET", "LIMIT", "SL", "SL-M"] = "MARKET"
    product: Literal["INTRADAY", "DELIVERY", "MARGIN", "CARRYFORWARD"] = "INTRADAY"
    quantity: int = Field(..., gt=0)
    price: float = 0.0
    trigger_price: float = 0.0
    duration: Literal["DAY", "IOC"] = "DAY"
    paper: bool = True


class OrderResponse(BaseModel):
    order_id: str
    status: str
    paper: bool
    message: str
    raw: dict | None = None
