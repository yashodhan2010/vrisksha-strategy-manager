from __future__ import annotations

from typing import Protocol

from app.strategy.models import OrderProposal


class Broker(Protocol):
    def validate_session(self) -> bool:
        ...

    def get_holdings(self) -> list[dict]:
        ...

    def get_orders(self) -> list[dict]:
        ...

    def place_order(self, order: OrderProposal) -> str:
        ...


class ZerodhaBroker:
    def __init__(self, api_key: str | None = None, access_token: str | None = None) -> None:
        self.api_key = api_key
        self.access_token = access_token

    def validate_session(self) -> bool:
        return bool(self.api_key and self.access_token)

    def get_holdings(self) -> list[dict]:
        raise NotImplementedError("Zerodha holdings retrieval will be implemented in a later sprint.")

    def get_orders(self) -> list[dict]:
        raise NotImplementedError("Zerodha order retrieval will be implemented in a later sprint.")

    def place_order(self, order: OrderProposal) -> str:
        raise NotImplementedError("Live order placement is intentionally disabled in Sprint 0.")

