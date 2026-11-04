"""Turn target weights into whole-share orders against the bot's own book."""
from __future__ import annotations

import math

from ..broker.base import OrderRequest, Quote


def plan_orders(targets: dict[str, float], equity: float, positions: dict[str, float],
                quotes: dict[str, Quote], *, band: float = 0.02, allow_buys: bool = True,
                order_type: str = "limit", collar_bps: float = 30.0, max_orders: int = 30,
                max_order_notional: float | None = None) -> tuple[list[OrderRequest], list[str]]:
    notes: list[str] = []
    sells: list[OrderRequest] = []
    buys: list[OrderRequest] = []
    for sym in sorted(set(targets) | set(positions)):
        q = quotes.get(sym)
        cur = int(positions.get(sym, 0))
        w = targets.get(sym, 0.0)
        if q is None or q.mid <= 0:
            if cur or w:
                notes.append(f"{sym}: no quote, skipped")
            continue
        px = q.mid
        tgt = int(math.floor(max(w, 0.0) * equity / px))
        delta = tgt - cur
        if delta == 0:
            continue
        full_exit = tgt == 0 and cur > 0
        if not full_exit and abs(delta) * px < band * equity:
            continue
        if delta > 0:
            if not allow_buys:
                notes.append(f"{sym}: buy of {delta} blocked by risk")
                continue
            if max_order_notional and delta * px > max_order_notional:
                delta = int(max_order_notional // px)
                notes.append(f"{sym}: buy clipped to ${max_order_notional:,.0f}")
            if delta <= 0:
                continue
            ref = q.ask if q.ask > 0 else px
            lim = round(ref * (1 + collar_bps / 1e4), 2) if order_type == "limit" else None
            buys.append(OrderRequest(sym, "BUY", delta, order_type, lim))
        else:
            ref = q.bid if q.bid > 0 else px
            lim = round(ref * (1 - collar_bps / 1e4), 2) if order_type == "limit" else None
            sells.append(OrderRequest(sym, "SELL", -delta, order_type, lim))
    orders = sells + buys
    if len(orders) > max_orders:
        notes.append(f"{len(orders)} orders exceeds max_orders_per_run={max_orders}; truncating buys")
        orders = sells[:max_orders] + buys[: max(0, max_orders - len(sells))]
    return orders, notes
