from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class Quote:
    symbol: str
    bid: float
    ask: float
    last: float

    @property
    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2
        return self.last


@dataclass
class OrderRequest:
    symbol: str
    side: str            # BUY | SELL
    qty: int
    order_type: str      # market | limit
    limit_price: float | None = None


@dataclass
class OrderResult:
    broker_order_id: str | None
    status: str          # FILLED | PARTIAL | REJECTED | CANCELED | WORKING | ERROR
    filled_qty: float = 0.0
    avg_price: float | None = None
    error: str | None = None


class Broker:
    mode: str = "base"

    def account_summary(self) -> dict:
        """{'liquidation_value': float, 'cash_available': float}"""
        raise NotImplementedError

    def broker_positions(self) -> dict[str, float]:
        raise NotImplementedError

    def quotes(self, symbols: list[str]) -> dict[str, Quote]:
        raise NotImplementedError

    def submit(self, order: OrderRequest) -> OrderResult:
        """Place an order and wait (bounded) for it to fill. Must not raise."""
        raise NotImplementedError

    def is_market_open(self, day: date) -> bool:
        return day.weekday() < 5
