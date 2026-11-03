"""Paper broker: simulated fills against real (or last-close) quotes.

Schwab's API has no paper-trading sandbox, so forward testing happens here. Fills
are taken at the ask (buys) / bid (sells) plus extra slippage -- deliberately a
bit pessimistic.
"""
from __future__ import annotations

from datetime import date
from typing import Callable

from ..store import Store
from .base import Broker, OrderRequest, OrderResult, Quote


class PaperBroker(Broker):
    mode = "paper"

    def __init__(self, store: Store, quote_fn: Callable[[list[str]], dict[str, Quote]],
                 extra_slippage_bps: float = 2.0, market_open_fn: Callable[[date], bool] | None = None):
        self.store = store
        self.quote_fn = quote_fn
        self.extra = extra_slippage_bps / 1e4
        self.market_open_fn = market_open_fn

    def account_summary(self) -> dict:
        cash = self.store.cash(self.mode)
        pos = self.store.positions(self.mode)
        q = self.quotes(list(pos)) if pos else {}
        mv = sum(p["qty"] * q[s].last for s, p in pos.items() if s in q)
        return {"liquidation_value": cash + mv, "cash_available": cash}

    def broker_positions(self) -> dict[str, float]:
        return {s: p["qty"] for s, p in self.store.positions(self.mode).items()}

    def quotes(self, symbols: list[str]) -> dict[str, Quote]:
        return self.quote_fn(symbols)

    def submit(self, order: OrderRequest) -> OrderResult:
        q = self.quotes([order.symbol]).get(order.symbol)
        if q is None:
            return OrderResult(None, "REJECTED", error="no quote")
        if order.side == "BUY":
            px = (q.ask if q.ask > 0 else q.last) * (1 + self.extra)
            if order.order_type == "limit" and order.limit_price is not None and px > order.limit_price:
                return OrderResult(None, "CANCELED", error=f"limit {order.limit_price} below fill {px:.2f}")
            if order.qty * px > self.store.cash(self.mode) + 1e-6:
                return OrderResult(None, "REJECTED", error="insufficient paper cash")
        else:
            px = (q.bid if q.bid > 0 else q.last) * (1 - self.extra)
            if order.order_type == "limit" and order.limit_price is not None and px < order.limit_price:
                return OrderResult(None, "CANCELED", error=f"limit {order.limit_price} above fill {px:.2f}")
            held = self.broker_positions().get(order.symbol, 0)
            if order.qty > held:
                return OrderResult(None, "REJECTED", error="selling more than held")
        return OrderResult(f"paper-{order.symbol}-{order.side}", "FILLED", float(order.qty), round(px, 4))

    def is_market_open(self, day: date) -> bool:
        if self.market_open_fn:
            return self.market_open_fn(day)
        return day.weekday() < 5


def last_close_quotes(bars) -> Callable[[list[str]], dict[str, Quote]]:
    """Quote function from the latest bar -- for paper runs without Schwab access."""
    def fn(symbols: list[str]) -> dict[str, Quote]:
        out = {}
        for s in symbols:
            if s in bars.close.columns:
                px = bars.close[s].dropna()
                if len(px):
                    p = float(px.iloc[-1])
                    out[s] = Quote(s, p * 0.9997, p * 1.0003, p)
        return out
    return fn
