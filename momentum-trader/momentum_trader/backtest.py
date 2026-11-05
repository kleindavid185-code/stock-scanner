"""Bar-by-bar backtest of the strategy + risk gate on historical 1-minute data.

Input files (written by a data downloader, one per source):

  <data>/universe.csv
      date,symbol,prev_close,avg_daily_volume,float_shares,short_pct_float
      -> which stocks to consider on which day, with pre-market facts
  <data>/bars/<SYMBOL>/<YYYY-MM-DD>.csv
      time,open,high,low,close,volume      (1-minute bars, US/Eastern,
                                            regular hours, time = bar start)

Fill assumptions (deliberately conservative -- listed in the report):
  * signals are computed on a CLOSED bar; the buy limit order is placed then
    and can only fill on the NEXT bar, and only if that bar trades at/below
    the limit. Unfilled orders are cancelled after one bar.
  * every fill pays `slippage_pct`: buys fill higher, sells fill lower
    (a buy never fills above its limit).
  * if a bar touches both the stop and the target, the stop is assumed first.
  * no bid/ask quotes in minute bars, so the live spread filter can't be
    applied in the backtest (live trading will skip wide-spread stocks).
"""
from __future__ import annotations

import csv
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .risk import CashLedger, OrderRejected, RiskGate, tick_round
from .settings import Settings
from .strategy import (Bar, ExitPlan, SymbolDayInfo, SymbolState, check_exit,
                       passes_static_filters, update_and_check_entry)


# ---- data loading --------------------------------------------------------------

def _f(v):
    return float(v) if v not in ("", None) else None


def load_universe(data_dir: Path) -> dict[str, list[SymbolDayInfo]]:
    by_date: dict[str, list[SymbolDayInfo]] = defaultdict(list)
    with (data_dir / "universe.csv").open(newline="") as fh:
        for row in csv.DictReader(fh):
            by_date[row["date"]].append(SymbolDayInfo(
                symbol=row["symbol"].upper(),
                prev_close=float(row["prev_close"]),
                avg_daily_volume=float(row["avg_daily_volume"]),
                float_shares=_f(row.get("float_shares")),
                short_pct_float=_f(row.get("short_pct_float")),
            ))
    return dict(sorted(by_date.items()))


def load_bars(data_dir: Path, symbol: str, day: str) -> list[Bar]:
    path = data_dir / "bars" / symbol / f"{day}.csv"
    if not path.exists():
        return []
    with path.open(newline="") as fh:
        bars = [Bar(r["time"][:16], float(r["open"]), float(r["high"]), float(r["low"]),
                    float(r["close"]), float(r["volume"])) for r in csv.DictReader(fh)]
    return [b for b in sorted(bars, key=lambda b: b.time) if "09:30" <= b.hhmm < "16:00"]


def aggregate(bars: list[Bar], minutes: int) -> list[Bar]:
    if minutes == 1:
        return bars
    groups: dict[str, list[Bar]] = defaultdict(list)
    for b in bars:
        m = int(b.hhmm[:2]) * 60 + int(b.hhmm[3:5]) - (9 * 60 + 30)
        start = 9 * 60 + 30 + (m // minutes) * minutes
        groups[f"{b.date} {start // 60:02d}:{start % 60:02d}"].append(b)
    return [Bar(t, g[0].open, max(x.high for x in g), min(x.low for x in g), g[-1].close,
                sum(x.volume for x in g)) for t, g in sorted(groups.items())]


# ---- simulation ----------------------------------------------------------------

@dataclass
class Trade:
    symbol: str
    date: str
    entry_time: str
    entry_price: float
    exit_time: str
    exit_price: float
    quantity: int
    pnl: float
    pnl_pct: float
    exit_reason: str


@dataclass
class _Position:
    symbol: str
    qty: int
    entry_price: float
    entry_time: str
    plan: ExitPlan
    last_price: float


@dataclass
class BacktestResult:
    trades: list[Trade]
    daily_equity: list[tuple[str, float]]
    starting_cash: float
    days_tested: int
    signals: int
    unfilled_orders: int
    rejections: Counter
    skipped: Counter
    halted_days: int
    settings: Settings
    equity_points: list[float] = field(default_factory=list)


def run_backtest(settings: Settings, data_dir: Path) -> BacktestResult:
    s = settings
    slip = s.backtest.slippage_pct / 100
    commission = s.backtest.commission_per_order
    ledger = CashLedger(settled=s.backtest.starting_cash)
    gate = RiskGate(s.risk)

    trades: list[Trade] = []
    daily_equity: list[tuple[str, float]] = []
    equity_points = [s.backtest.starting_cash]
    rejections: Counter = Counter()
    skipped: Counter = Counter()
    signals = unfilled = halted_days = 0

    universe = load_universe(data_dir)
    for day, infos in universe.items():
        ledger.settle_through(day)
        gate.start_day(day)
        states: dict[str, SymbolState] = {}
        bars_by_time: dict[str, dict[str, Bar]] = defaultdict(dict)
        for info in infos:
            ok, why = passes_static_filters(info, s.scanner)
            if not ok:
                skipped[why] += 1
                continue
            bars = aggregate(load_bars(data_dir, info.symbol, day), s.entry.bar_minutes)
            if not bars:
                skipped["no intraday bars"] += 1
                continue
            states[info.symbol] = SymbolState(info, s.entry.breakout_lookback_bars)
            for b in bars:
                bars_by_time[b.time][info.symbol] = b

        positions: dict[str, _Position] = {}
        pending: dict[str, tuple[int, float, str]] = {}   # symbol -> (qty, limit, signal_time)

        def close_position(pos: _Position, raw_price: float, when: str, reason: str):
            price = tick_round(raw_price * (1 - slip))
            proceeds = pos.qty * price - commission
            cost = pos.qty * pos.entry_price + commission
            pnl = proceeds - cost
            ledger.receive_sale(proceeds, day)
            gate.record_realized(pnl)
            trades.append(Trade(pos.symbol, day, pos.entry_time, pos.entry_price, when, price,
                                pos.qty, round(pnl, 2), round(pnl / cost * 100, 2), reason))
            equity_points.append(ledger.total + sum(
                p.qty * p.last_price for p in positions.values() if p is not pos))
            del positions[pos.symbol]

        for t in sorted(bars_by_time):
            for sym, bar in bars_by_time[t].items():
                # 1) try to fill the buy order placed on the previous bar
                if sym in pending:
                    qty, limit, _sig_time = pending.pop(sym)
                    if gate.day.halted:
                        unfilled += 1          # cancelled: trading halted
                    elif bar.low <= limit:
                        fill = tick_round(min(min(bar.open, limit) * (1 + slip), limit))
                        try:
                            ledger.pay_for_buy(qty * fill + commission)
                        except OrderRejected as exc:
                            rejections[str(exc).split(" (")[0]] += 1
                        else:
                            gate.record_entry()
                            plan = ExitPlan.for_entry(fill, s.exit)
                            pos = _Position(sym, qty, fill, t, plan, bar.close)
                            positions[sym] = pos
                            if bar.low <= plan.stop_price:   # conservative: stop same bar
                                close_position(pos, plan.stop_price, t, "stop_loss")
                    else:
                        unfilled += 1

                # 2) manage an open position (skip the bar it was just filled on)
                pos = positions.get(sym)
                if pos and pos.entry_time != t:
                    hit = check_exit(pos.plan, bar, s.exit.flatten_at)
                    if hit:
                        close_position(pos, hit[1], t, hit[0])
                    else:
                        pos.last_price = bar.close
                elif pos:
                    pos.last_price = bar.close

                # 3) look for a new entry on this closed bar
                sig = update_and_check_entry(states[sym], bar, s.scanner, s.entry)
                if sig and sym not in positions and sym not in pending:
                    signals += 1
                    limit = sig.price * (1 + s.entry.entry_limit_offset_pct / 100)
                    equity = ledger.total + sum(p.qty * p.last_price for p in positions.values())
                    try:
                        order = gate.size_buy(sym, limit, equity=equity, ledger=ledger,
                                              open_positions=len(positions) + len(pending),
                                              reason="breakout")
                    except OrderRejected as exc:
                        rejections[str(exc).split(" (")[0].split(":")[0]] += 1
                    else:
                        pending[sym] = (order.quantity, order.limit_price, t)

            # 4) daily loss limit including open positions -> flatten and halt
            unrealized = sum(p.qty * (p.last_price - p.entry_price) for p in positions.values())
            if gate.day.halted or gate.check_daily_loss(unrealized):
                for pos in list(positions.values()):
                    close_position(pos, pos.last_price, t, "daily_loss_halt")
                unfilled += len(pending)
                pending.clear()

        # 5) end of day: nothing is held overnight
        for pos in list(positions.values()):
            close_position(pos, pos.last_price, pos.entry_time[:11] + "16:00", "eod_flatten")
        unfilled += len(pending)
        if gate.day.halted:
            halted_days += 1
        daily_equity.append((day, round(ledger.total, 2)))

    return BacktestResult(trades, daily_equity, s.backtest.starting_cash, len(universe),
                          signals, unfilled, rejections, skipped, halted_days, s, equity_points)


# ---- report --------------------------------------------------------------------

def summarize(r: BacktestResult) -> dict:
    pnls = [t.pnl for t in r.trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    final = r.daily_equity[-1][1] if r.daily_equity else r.starting_cash
    peak, max_dd, max_dd_pct = r.starting_cash, 0.0, 0.0
    for eq in r.equity_points:
        peak = max(peak, eq)
        dd = peak - eq
        if dd > max_dd:
            max_dd, max_dd_pct = dd, dd / peak * 100
    gross_win, gross_loss = sum(wins), -sum(losses)
    return {
        "starting_cash": r.starting_cash,
        "ending_cash": final,
        "net_profit": round(final - r.starting_cash, 2),
        "return_pct": round((final / r.starting_cash - 1) * 100, 2),
        "days_tested": r.days_tested,
        "trades": len(pnls),
        "win_rate_pct": round(len(wins) / len(pnls) * 100, 1) if pnls else 0.0,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "largest_win": round(max(pnls), 2) if pnls else 0.0,
        "largest_loss": round(min(pnls), 2) if pnls else 0.0,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else (
            math.inf if gross_win > 0 else 0.0),
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "signals": r.signals,
        "unfilled_orders": r.unfilled_orders,
        "halted_days": r.halted_days,
        "exit_reasons": dict(Counter(t.exit_reason for t in r.trades)),
        "rejections": dict(r.rejections),
        "skipped": dict(r.skipped),
    }


def write_report(r: BacktestResult, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    st = summarize(r)
    s = r.settings
    with (out_dir / "trades.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(list(Trade.__dataclass_fields__))
        for t in r.trades:
            w.writerow(list(t.__dict__.values()))

    lines = [
        "# Backtest report",
        f"_Generated {datetime.now():%Y-%m-%d %H:%M}_",
        "",
        "## Results",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Starting cash | ${st['starting_cash']:,.2f} |",
        f"| Ending cash | ${st['ending_cash']:,.2f} |",
        f"| **Net profit** | **${st['net_profit']:,.2f} ({st['return_pct']:+.2f}%)** |",
        f"| Days tested | {st['days_tested']} |",
        f"| Trades | {st['trades']} |",
        f"| Win rate | {st['win_rate_pct']}% |",
        f"| Average win | ${st['avg_win']:,.2f} |",
        f"| Average loss | ${st['avg_loss']:,.2f} |",
        f"| Largest win / loss | ${st['largest_win']:,.2f} / ${st['largest_loss']:,.2f} |",
        f"| Profit factor | {st['profit_factor']} |",
        f"| Max drawdown | ${st['max_drawdown']:,.2f} ({st['max_drawdown_pct']}%) |",
        f"| Days halted by daily-loss limit | {st['halted_days']} |",
        "",
        "## Activity",
        f"* Signals: {st['signals']}, unfilled limit orders: {st['unfilled_orders']}",
        f"* Exit reasons: {st['exit_reasons']}",
        f"* Orders blocked by the risk gate: {st['rejections'] or 'none'}",
        f"* Stocks skipped before the open: {st['skipped'] or 'none'}",
        "",
        "## Assumptions",
        f"* Slippage: {s.backtest.slippage_pct}% against you on every buy and every sell",
        f"* Commission: ${s.backtest.commission_per_order:.2f} per order",
        "* Buy limit placed at signal-bar close + "
        f"{s.entry.entry_limit_offset_pct}%; fills only on the next bar, at or below the limit",
        "* Stop assumed to hit before target when both are inside one bar",
        "* Cash account: buys use settled cash only; sale proceeds settle next business day",
        "* No bid/ask data in minute bars, so the live spread filter is not applied",
        "* Float / short interest are the values at download time, not as of each "
        "historical day (look-ahead bias -- results may look better than reality)",
        "* Past results do not predict future results",
    ]
    path = out_dir / "report.md"
    path.write_text("\n".join(lines) + "\n")
    return path
