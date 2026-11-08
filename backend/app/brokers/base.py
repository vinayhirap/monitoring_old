"""Abstract broker interface — keeps the rest of the app broker-agnostic."""
from abc import ABC, abstractmethod
from typing import Any


class BrokerError(Exception):
    pass


class BrokerBase(ABC):
    """Minimal contract every broker integration must implement."""

    name: str = "base"

    @abstractmethod
    def login(self, **kwargs: Any) -> dict:
        """Authenticate. Returns profile dict on success."""

    @abstractmethod
    def is_authenticated(self) -> bool: ...

    @abstractmethod
    def quote(self, exchange: str, symbol_token: str) -> dict: ...

    @abstractmethod
    def candles(self, exchange: str, symbol_token: str, interval: str,
                fromdate: str, todate: str) -> list[list]: ...

    @abstractmethod
    def place_order(self, **kwargs: Any) -> dict: ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> dict: ...

    @abstractmethod
    def positions(self) -> list[dict]: ...

    @abstractmethod
    def holdings(self) -> list[dict]: ...
