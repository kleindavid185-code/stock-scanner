"""The trading rules, as pure logic (no network, no broker).

The SAME code is used by the backtest, dry-run, manual and auto modes, so a
backtest result reflects exactly the rules that would trade live.

Entry (momentum breakout with volume confirmation), checked on each closed bar:
  * stock passes the scanner filters at that moment (price, % up, RVOL, ...)
  * time is inside [no_entries_before, no_entries_after)
  * bar close > highest high of the previous N bars
  * bar volume >= volume_confirm_multiple x average volume of those N bars
  * close above VWAP (if required)

Exit, checked on every bar while in a position:
  * stop loss   : price falls stop_loss_pct below entry
  * target      : price rises profit_target_pct above entry
  * trailing    : once up trailing_activation_pct, exit if price falls
                  trailing_stop_pct below the highest price seen
  * end of day  : at flatten_at, sell no matter what
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .settings import EntrySettings, ExitSettings, ScannerSettings


@dataclass(frozen=True)
class Bar:
    time: str        # "YYYY-MM-DD HH:MM", US/Eastern, bar START time
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def date(self) -> str:
        return self.time[:10]

    @property
    def hhmm(self) -> str:
        return self.time[11:16]


@dataclass(frozen=True)
class SymbolDayInfo:
    """Facts about a stock known before the day starts."""
    symbol: str
    prev_close: float
    avg_daily_volume: float          # e.g. 20-day average
    float_shares: float | None       # None = unknown
    short_pct_float: float | None    # percent, e.g. 15.0; None = unknown


SESSION_MINUTES = 390  # 09:30-16:00


def minutes_since_open(hhmm: str) -> int:
    h, m = int(hhmm[:2]), int(hhmm[3:5])
    return (h * 60 + m) - (9 * 60 + 30)


def relative_volume(cum_volume: float, avg_daily_volume: float, hhmm_end: str) -> float:
    """Today's volume so far vs. what's normal by this time of day.

    Uses a simple straight-line assumption (by 10:00, a normal day has done
    30/390 of its volume). Low-float runners trade far more in the morning,
    so this is a fair, slightly conservative-early approximation.
    """
    if avg_daily_volume <= 0:
        return 0.0
    elapsed = min(max(minutes_since_open(hhmm_end), 1), SESSION_MINUTES)
    expected = avg_daily_volume * elapsed / SESSION_MINUTES
    return cum_volume / expected


def passes_static_filters(info: SymbolDayInfo, sc: ScannerSettings) -> tuple[bool, str]:
    """Float and short interest -- known before the open."""
    if info.float_shares is None or info.float_shares > sc.max_float_shares:
        return False, "float unknown or too large"
    if sc.require_short_interest_flag:
        if info.short_pct_float is None or info.short_pct_float < sc.min_short_interest_pct_float:
            return False, "short interest not flagged"
    return True, ""


@dataclass
class SymbolState:
    """Rolling intraday state for one symbol on one day."""
    info: SymbolDayInfo
    lookback: int
    recent: deque = field(default_factory=deque)   # previous N bars
    cum_volume: float = 0.0
    cum_pv: float = 0.0                              # price*volume, for VWAP

    @property
    def vwap(self) -> float | None:
        return self.cum_pv / self.cum_volume if self.cum_volume > 0 else None


@dataclass(frozen=True)
class EntrySignal:
    symbol: str
    time: str
    price: float          # breakout bar close
    breakout_level: float
    volume_ratio: float
    rvol: float
    pct_change: float
    vwap: float | None


def _bar_end_hhmm(bar: Bar, bar_minutes: int) -> str:
    h, m = int(bar.hhmm[:2]), int(bar.hhmm[3:5]) + bar_minutes
    h, m = h + m // 60, m % 60
    return f"{h:02d}:{m:02d}"


def update_and_check_entry(state: SymbolState, bar: Bar, sc: ScannerSettings,
                           en: EntrySettings) -> EntrySignal | None:
    """Feed one CLOSED bar; return an EntrySignal if it is a valid breakout."""
    prior = list(state.recent)
    state.cum_volume += bar.volume
    typical = (bar.high + bar.low + bar.close) / 3
    state.cum_pv += typical * bar.volume
    state.recent.append(bar)
    while len(state.recent) > state.lookback:
        state.recent.popleft()

    if len(prior) < state.lookback:
        return None
    end = _bar_end_hhmm(bar, en.bar_minutes)
    if not (en.no_entries_before <= end <= en.no_entries_after):
        return None

    price = bar.close
    if not (sc.min_price <= price <= sc.max_price):
        return None
    pct_change = (price / state.info.prev_close - 1) * 100 if state.info.prev_close > 0 else 0.0
    if pct_change < sc.min_pct_change:
        return None
    if state.cum_volume < sc.min_day_volume:
        return None
    rvol = relative_volume(state.cum_volume, state.info.avg_daily_volume, end)
    if rvol < sc.min_relative_volume:
        return None

    breakout_level = max(b.high for b in prior)
    if price <= breakout_level:
        return None
    avg_vol = sum(b.volume for b in prior) / len(prior)
    volume_ratio = bar.volume / avg_vol if avg_vol > 0 else float("inf")
    if volume_ratio < en.volume_confirm_multiple:
        return None
    vwap = state.vwap
    if en.require_above_vwap and (vwap is None or price <= vwap):
        return None

    return EntrySignal(state.info.symbol, bar.time, price, breakout_level,
                       round(volume_ratio, 2), round(rvol, 2), round(pct_change, 2),
                       round(vwap, 4) if vwap else None)


# ---- exits -------------------------------------------------------------------

@dataclass
class ExitPlan:
    """Price levels for an open position; updated as the price moves."""
    entry_price: float
    stop_price: float
    target_price: float
    trail_pct: float
    trail_activation_price: float
    highest: float

    @classmethod
    def for_entry(cls, entry_price: float, ex: ExitSettings) -> "ExitPlan":
        return cls(
            entry_price=entry_price,
            stop_price=entry_price * (1 - ex.stop_loss_pct / 100),
            target_price=entry_price * (1 + ex.profit_target_pct / 100),
            trail_pct=ex.trailing_stop_pct,
            trail_activation_price=entry_price * (1 + ex.trailing_activation_pct / 100),
            highest=entry_price,
        )

    @property
    def trailing_armed(self) -> bool:
        return self.highest >= self.trail_activation_price

    @property
    def effective_stop(self) -> float:
        """The higher of the hard stop and (if armed) the trailing stop."""
        if self.trailing_armed:
            return max(self.stop_price, self.highest * (1 - self.trail_pct / 100))
        return self.stop_price


def check_exit(plan: ExitPlan, bar: Bar, flatten_at: str) -> tuple[str, float] | None:
    """Return (reason, trigger_price) if this bar triggers an exit, else None.

    Conservative ordering: within a bar we can't know whether the high or the
    low came first, so if both the stop and the target are touched we assume
    the STOP hit first. The trailing high only updates AFTER the bar is
    checked, so a bar can't raise its own trailing stop and then stop out.
    """
    if bar.hhmm >= flatten_at:
        return "eod_flatten", bar.open
    stop = plan.effective_stop
    if bar.open <= stop:                       # gapped through the stop
        return ("trailing_stop" if stop > plan.stop_price else "stop_loss"), bar.open
    if bar.low <= stop:
        return ("trailing_stop" if stop > plan.stop_price else "stop_loss"), stop
    if bar.open >= plan.target_price:
        return "profit_target", bar.open
    if bar.high >= plan.target_price:
        return "profit_target", plan.target_price
    plan.highest = max(plan.highest, bar.high)
    return None
