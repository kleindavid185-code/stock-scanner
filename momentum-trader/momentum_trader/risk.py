"""Hard risk limits and cash-account (settled funds) bookkeeping.

Every order -- backtest, dry run, manual or auto -- must pass `RiskGate`.
The strategy only *proposes* trades; this module decides whether they are
allowed and how big they may be. Its limits come from read-only settings.

Good-faith violations, in plain English:
  In a cash account, money from a sale is "unsettled" until the next business
  day (T+1). If you buy with unsettled money and then sell that new stock
  before the money settles, that's a good-faith violation (GFV). Rack up a
  few and Schwab restricts the account for 90 days.

  This bot avoids GFVs completely by sizing every buy from SETTLED cash
  only. Sale proceeds sit in "pending" until they settle and cannot be
  spent before then.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

from .settings import RiskSettings


class OrderRejected(Exception):
    pass


@dataclass(frozen=True)
class LimitOrder:
    """The only order type the bot can create. There is no market order class."""
    symbol: str
    side: str            # "BUY" or "SELL"
    quantity: int
    limit_price: float
    reason: str = ""

    def __post_init__(self):
        if self.side not in ("BUY", "SELL"):
            raise ValueError(f"side must be BUY or SELL, got {self.side!r}")
        if not isinstance(self.quantity, int) or self.quantity <= 0:
            raise ValueError("quantity must be a positive whole number")
        if not (isinstance(self.limit_price, (int, float)) and math.isfinite(self.limit_price)
                and self.limit_price > 0):
            raise ValueError("limit orders need a positive limit price")

    @property
    def order_type(self) -> str:
        return "LIMIT"


# ---- settlement ----------------------------------------------------------------

# NYSE full-day holidays, 2025-2027 (settlement does not happen on these).
MARKET_HOLIDAYS = {
    "2025-01-01", "2025-01-09", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26",
    "2025-06-19", "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25",
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19",
    "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18",
    "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
}


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d.isoformat() not in MARKET_HOLIDAYS


def next_business_day(d: date) -> date:
    d += timedelta(days=1)
    while not is_business_day(d):
        d += timedelta(days=1)
    return d


@dataclass
class CashLedger:
    """Settled vs. unsettled cash for a cash account (T+1 settlement)."""
    settled: float
    pending: list[tuple[str, float]] = field(default_factory=list)  # (settle_date, amount)

    @property
    def unsettled(self) -> float:
        return sum(a for _, a in self.pending)

    @property
    def total(self) -> float:
        return self.settled + self.unsettled

    def settle_through(self, today: str) -> None:
        """Move every sale whose settlement date has arrived into settled cash."""
        still = []
        for settle_date, amount in self.pending:
            if settle_date <= today:
                self.settled += amount
            else:
                still.append((settle_date, amount))
        self.pending = still

    def pay_for_buy(self, cost: float) -> None:
        if cost > self.settled + 1e-9:
            raise OrderRejected(
                f"would use unsettled funds (needs ${cost:,.2f}, settled ${self.settled:,.2f}) "
                "-- blocked to prevent a good-faith violation")
        self.settled -= cost

    def receive_sale(self, proceeds: float, trade_date: str) -> None:
        settle = next_business_day(date.fromisoformat(trade_date)).isoformat()
        self.pending.append((settle, proceeds))


# ---- the gate ------------------------------------------------------------------

@dataclass
class DayState:
    date: str
    trades_today: int = 0
    realized_pnl: float = 0.0
    halted: bool = False
    halt_reason: str = ""


def tick_round(price: float) -> float:
    """US equities: $0.01 ticks at/above $1, $0.0001 below $1."""
    return round(price, 2) if price >= 1 else round(price, 4)


class RiskGate:
    def __init__(self, limits: RiskSettings):
        self.limits = limits
        self.day: DayState | None = None

    def start_day(self, today: str) -> None:
        if self.day is None or self.day.date != today:
            self.day = DayState(today)

    def halt(self, reason: str) -> None:
        assert self.day is not None
        if not self.day.halted:
            self.day.halted = True
            self.day.halt_reason = reason

    def record_entry(self) -> None:
        self.day.trades_today += 1

    def record_realized(self, pnl: float) -> None:
        self.day.realized_pnl += pnl
        self.check_daily_loss(0.0)

    def check_daily_loss(self, unrealized_pnl: float) -> bool:
        """Halt (and return True) once realized + open losses reach the limit."""
        total = self.day.realized_pnl + unrealized_pnl
        if total <= -self.limits.max_daily_loss_dollars:
            self.halt(f"daily loss limit hit (${total:,.2f})")
            return True
        return False

    def size_buy(self, symbol: str, limit_price: float, *, equity: float,
                 ledger: CashLedger, open_positions: int, reason: str = "") -> LimitOrder:
        """Return an approved BUY limit order, or raise OrderRejected."""
        L = self.limits
        d = self.day
        if d is None:
            raise OrderRejected("risk gate not started for today")
        if d.halted:
            raise OrderRejected(f"trading halted for the day: {d.halt_reason}")
        if d.trades_today >= L.max_trades_per_day:
            raise OrderRejected(f"max trades per day reached ({L.max_trades_per_day})")
        if open_positions >= L.max_open_positions:
            raise OrderRejected(f"max open positions reached ({L.max_open_positions})")
        if d.realized_pnl <= -L.max_daily_loss_dollars:
            raise OrderRejected("daily loss limit reached")
        limit_price = tick_round(limit_price)
        budget = min(L.max_position_dollars,
                     equity * L.max_account_pct_per_trade / 100,
                     ledger.settled)
        qty = int(budget // limit_price)
        if qty < 1:
            raise OrderRejected(
                f"position too small: budget ${budget:,.2f} buys 0 shares at ${limit_price:.2f} "
                f"(settled cash ${ledger.settled:,.2f})")
        return LimitOrder(symbol, "BUY", qty, limit_price, reason)
