"""Angel One SmartAPI broker adapter.

Wraps `smartapi-python` (`SmartConnect`) with TOTP-based login and a paper-trading
fallback when credentials are missing or login fails.

Reference: https://smartapi.angelbroking.com/docs
"""
from __future__ import annotations

import threading
import time as _time
from datetime import datetime
from typing import Any
from uuid import uuid4

from loguru import logger

from app.brokers.base import BrokerBase, BrokerError
from app.config import settings


# Angel One getCandleData allows ~3 req/sec (180/min). The dashboard fires many
# symbols at once, so serialise candle calls and space them out.
_CANDLE_LOCK = threading.Lock()
_CANDLE_MIN_GAP = 0.40          # seconds between candle requests
_candle_last = 0.0


class AngelOneBroker(BrokerBase):
    name = "angelone"

    def __init__(self) -> None:
        self._client = None
        self._session: dict | None = None
        self._paper: bool = settings.paper_mode
        self._paper_orders: dict[str, dict] = {}
        self._paper_positions: list[dict] = []
        self._last_error: str | None = None
        self._last_login_attempt: str | None = None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def login(self, api_key: str | None = None, client_code: str | None = None,
              password: str | None = None, totp: str | None = None) -> dict:
        # Angel One now supports TOTP-only login (password no longer required).
        # In LIVE_ONLY mode we raise BrokerError on any failure instead of silently
        # falling back to paper — the user gets a clear, actionable error.
        from datetime import datetime as _dt
        self._last_login_attempt = _dt.now().isoformat()
        self._last_error = None
        api_key = api_key or settings.angelone_api_key
        client_code = client_code or settings.angelone_client_code
        password = password if password is not None else settings.angelone_password
        totp_secret = settings.angelone_totp_secret
        live_only = settings.live_only

        # ---- 1. credentials check ----
        # NOTE: Angel One's SmartAPI requires ALL of:
        #   • client_code
        #   • password (4-digit MPIN — even when TOTP is enabled on the account)
        #   • totp (6-digit code, auto-generated from secret)
        # Earlier docs claimed password was optional. It is NOT — SmartAPI rejects
        # empty/null password with "Invalid password parameter name".
        has_totp_source = bool(totp or totp_secret)
        missing = []
        if not api_key:     missing.append("ANGELONE_API_KEY")
        if not client_code: missing.append("ANGELONE_CLIENT_CODE")
        if not password:    missing.append("ANGELONE_PASSWORD (4-digit MPIN)")
        if not has_totp_source: missing.append("ANGELONE_TOTP_SECRET (or runtime TOTP)")
        if missing:
            msg = f"Missing required credentials: {', '.join(missing)}"
            if live_only:
                raise BrokerError(msg)
            self._paper = True
            logger.warning("{} → PAPER mode (set LIVE_ONLY=true in .env to require live)", msg)
            return {"status": "paper", "message": msg,
                    "paper_mode": True, "profile": None, "live_only": live_only}

        # ---- 2. smartapi-python installed? ----
        try:
            from SmartApi import SmartConnect
        except ImportError as e:
            msg = f"smartapi-python not installed: {e}"
            if live_only:
                raise BrokerError(msg)
            self._paper = True
            return {"status": "paper", "message": msg,
                    "paper_mode": True, "profile": None, "live_only": live_only}

        # ---- 3. generate TOTP code from secret ----
        if not totp:
            try:
                import pyotp
                totp = pyotp.TOTP(totp_secret).now()
            except Exception as e:
                msg = f"TOTP generation failed (check ANGELONE_TOTP_SECRET — must be base32): {e}"
                if live_only:
                    raise BrokerError(msg)
                self._paper = True
                return {"status": "paper", "message": msg,
                        "paper_mode": True, "profile": None, "live_only": live_only}

        # ---- 4. actual SmartAPI login ----
        try:
            client = SmartConnect(api_key=api_key)
            session = client.generateSession(client_code, password or "", totp)
        except Exception as e:
            msg = f"SmartAPI generateSession() raised: {e}"
            logger.exception("Angel One generateSession exception")
            if live_only:
                raise BrokerError(msg)
            self._paper = True
            return {"status": "paper", "message": msg,
                    "paper_mode": True, "profile": None, "live_only": live_only}

        if not isinstance(session, dict) or not session.get("status"):
            api_msg = session.get("message") if isinstance(session, dict) else str(session)
            err_code = session.get("errorcode") if isinstance(session, dict) else None
            msg = f"Angel One rejected login: {api_msg} (code {err_code})"
            logger.warning(msg)
            if live_only:
                raise BrokerError(msg)
            self._paper = True
            return {"status": "paper", "message": msg,
                    "paper_mode": True, "profile": None, "live_only": live_only}

        # ---- 5. success ----
        self._client = client
        self._session = session.get("data", {})
        self._paper = False
        try:
            profile = client.getProfile(self._session.get("refreshToken"))
            profile_data = profile.get("data") if isinstance(profile, dict) else None
        except Exception as e:
            logger.warning("getProfile after login failed (continuing anyway): {}", e)
            profile_data = None

        logger.success("✓ Angel One authenticated for client {}", client_code)
        return {
            "status": "ok",
            "message": "Authenticated with Angel One",
            "paper_mode": False, "live_only": live_only,
            "profile": profile_data,
        }

    def is_authenticated(self) -> bool:
        return self._client is not None and self._session is not None

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def quote(self, exchange: str, tradingsymbol: str, symbol_token: str) -> dict:
        """SmartAPI ltpData signature: (exchange, tradingsymbol, symboltoken).
        Returns {"status", "message", "data": {ltp, open, high, low, close, ...}}.
        """
        if self._paper or not self._client:
            return {"paper": True, "exchange": exchange, "symbol_token": symbol_token,
                    "ltp": None, "message": "Paper-mode quote stub"}
        try:
            res = self._client.ltpData(exchange, tradingsymbol, symbol_token)
            if isinstance(res, dict) and not res.get("status"):
                # SmartAPI returned a failure payload — surface its message
                logger.warning("ltpData failed for {}/{}/{}: {}",
                                exchange, tradingsymbol, symbol_token, res.get("message"))
            return res
        except Exception as e:
            logger.warning("ltpData exception for {}/{}/{}: {}",
                            exchange, tradingsymbol, symbol_token, e)
            raise BrokerError(f"quote failed: {e}")

    def search_scrip(self, exchange: str, query: str) -> list[dict]:
        """Search Angel One's instrument catalog via the authenticated API.
        Works post-login without needing the public scrip-master file.
        Returns list of matches like [{tradingsymbol, symboltoken, ...}, ...].
        """
        if self._paper or not self._client:
            return []
        try:
            res = self._client.searchScrip(exchange, query)  # positional: SDK param name differs by version
            if isinstance(res, dict) and res.get("status") and res.get("data"):
                return list(res["data"])
        except Exception as e:
            logger.debug("searchScrip failed for {}/{}: {}", exchange, query, e)
        return []

    def quotes_batch(self, mode: str, exchange_tokens: dict[str, list[str]]) -> dict:
        """Bulk quote via SmartAPI getMarketData. Far more efficient than
        N separate ltpData calls.

        Args:
            mode: "LTP" | "OHLC" | "FULL"
            exchange_tokens: {"NSE": ["99926000", "2885"], "NFO": [...]}
        Returns the raw SmartAPI response.
        """
        if self._paper or not self._client:
            return {"paper": True, "data": {"fetched": [], "unfetched": []}}
        try:
            res = self._client.getMarketData(mode=mode, exchangeTokens=exchange_tokens)
            if isinstance(res, dict) and not res.get("status"):
                logger.warning("getMarketData failed: {}", res.get("message"))
            return res
        except Exception as e:
            logger.warning("getMarketData exception: {}", e)
            raise BrokerError(f"batch quote failed: {e}")

    def candles(self, exchange: str, symbol_token: str, interval: str,
                fromdate: str, todate: str) -> list[list]:
        if self._paper or not self._client:
            return []
        try:
            params = {
                "exchange": exchange,
                "symboltoken": symbol_token,
                "interval": interval,         # e.g. ONE_DAY, FIFTEEN_MINUTE
                "fromdate": fromdate,         # "YYYY-MM-DD HH:MM"
                "todate": todate,
            }
            global _candle_last
            with _CANDLE_LOCK:
                wait = _CANDLE_MIN_GAP - (_time.time() - _candle_last)
                if wait > 0:
                    _time.sleep(wait)
                try:
                    data = self._client.getCandleData(params)
                finally:
                    _candle_last = _time.time()
            return data.get("data", []) if isinstance(data, dict) else []
        except Exception as e:
            raise BrokerError(f"candles failed: {e}")

    def option_greeks(self, name: str, expiry: str) -> list[dict]:
        """Pull live option chain greeks via Angel One's optionGreek endpoint.
        name   : underlying (e.g. "NIFTY", "RELIANCE")
        expiry : "DDMMMYYYY" upper-cased (e.g. "29MAY2025")

        Returns list of dicts with: strikePrice, optionType (CE/PE), delta,
        gamma, theta, vega, impliedVolatility, tradeVolume.
        """
        if self._paper or not self._client:
            return []
        try:
            params = {"name": name.upper(), "expirydate": expiry.upper()}
            # smartapi-python exposes this as `optionGreek` (singular)
            res = self._client.optionGreek(params)
            if isinstance(res, dict):
                return res.get("data", []) or []
            return []
        except Exception as e:
            raise BrokerError(f"option_greeks failed: {e}")

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def place_order(self, *, symbol: str, exchange: str, transaction_type: str,
                    order_type: str, product: str, quantity: int, price: float = 0.0,
                    trigger_price: float = 0.0, duration: str = "DAY",
                    paper: bool = True, **kwargs: Any) -> dict:
        if paper or self._paper or not self._client:
            return self._paper_order(symbol=symbol, exchange=exchange,
                                     transaction_type=transaction_type,
                                     quantity=quantity, price=price)
        try:
            order_params = {
                "variety": "NORMAL",
                "tradingsymbol": symbol,
                "symboltoken": kwargs.get("symbol_token", "0"),
                "transactiontype": transaction_type,
                "exchange": exchange,
                "ordertype": order_type,
                "producttype": product,
                "duration": duration,
                "price": str(price),
                "triggerprice": str(trigger_price),
                "quantity": str(quantity),
            }
            res = self._client.placeOrder(order_params)
            return {"order_id": res, "status": "submitted", "paper": False, "message": "ok"}
        except Exception as e:
            raise BrokerError(f"order placement failed: {e}")

    def cancel_order(self, order_id: str) -> dict:
        if self._paper or order_id in self._paper_orders:
            self._paper_orders.pop(order_id, None)
            return {"order_id": order_id, "status": "cancelled", "paper": True}
        try:
            res = self._client.cancelOrder(order_id, "NORMAL")
            return {"order_id": order_id, "status": "cancelled", "paper": False, "raw": res}
        except Exception as e:
            raise BrokerError(f"cancel failed: {e}")

    def positions(self) -> list[dict]:
        if self._paper or not self._client:
            return self._paper_positions
        try:
            res = self._client.position()
            return res.get("data", []) if isinstance(res, dict) else []
        except Exception as e:
            raise BrokerError(f"positions failed: {e}")

    def holdings(self) -> list[dict]:
        if self._paper or not self._client:
            return []
        try:
            res = self._client.holding()
            return res.get("data", []) if isinstance(res, dict) else []
        except Exception as e:
            raise BrokerError(f"holdings failed: {e}")

    # ------------------------------------------------------------------
    # Paper helpers
    # ------------------------------------------------------------------

    def _paper_order(self, *, symbol: str, exchange: str, transaction_type: str,
                     quantity: int, price: float) -> dict:
        oid = f"PAPER-{uuid4().hex[:10].upper()}"
        record = {
            "order_id": oid,
            "status": "FILLED",
            "paper": True,
            "symbol": symbol,
            "exchange": exchange,
            "transaction_type": transaction_type,
            "quantity": quantity,
            "price": price,
            "ts": datetime.utcnow().isoformat(),
            "message": "Paper trade — no live order placed",
        }
        self._paper_orders[oid] = record
        # mirror as a position
        self._paper_positions.append({
            "tradingsymbol": symbol,
            "exchange": exchange,
            "netqty": quantity if transaction_type == "BUY" else -quantity,
            "avgnetprice": price,
            "ltp": price,
            "pnl": 0.0,
            "paper": True,
        })
        return record


# Singleton (single-process)
broker_instance = AngelOneBroker()
