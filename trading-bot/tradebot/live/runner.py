"""Daily operations: forward-test review, rebalance, and the scheduler loop."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from ..broker.base import Broker, OrderRequest
from ..data.base import Bars, load_bars
from ..execution.planner import plan_orders
from ..execution.risk import RiskManager
from ..notify import notify
from ..research.discovery import evaluate
from ..store import Store
from ..strategies import build
from ..backtest.metrics import compute_metrics

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# brokers
# ---------------------------------------------------------------------------
def make_broker(cfg, store: Store, mode: str, bars: Bars | None = None) -> Broker:
    from ..broker.paper import PaperBroker, last_close_quotes

    ex = cfg.section("execution")
    if mode == "live":
        ok, why = cfg.live_allowed()
        if not ok:
            raise RuntimeError(f"live trading blocked: {why}")
        from ..broker.schwab_broker import SchwabBroker, make_schwab_client

        return SchwabBroker(make_schwab_client(cfg), cfg.schwab.account_hash, ex["fill_timeout_sec"])
    store.init_book("paper", ex["paper_starting_cash"])
    if cfg.schwab.configured and cfg.schwab.token_path.exists():
        # Paper trading against real Schwab quotes + market calendar.
        from ..broker.schwab_broker import SchwabBroker, make_schwab_client

        sb = SchwabBroker(make_schwab_client(cfg), cfg.schwab.account_hash)
        return PaperBroker(store, sb.quotes, market_open_fn=sb.is_market_open)
    if bars is None:
        raise RuntimeError("paper mode without Schwab credentials needs bars for quotes")
    return PaperBroker(store, last_close_quotes(bars))


# ---------------------------------------------------------------------------
# strategy combination
# ---------------------------------------------------------------------------
def active_strategies(store: Store, mode: str) -> list[dict]:
    return store.strategies(["live"] if mode == "live" else ["paper", "live"])


def combined_targets(strats: list[dict], bars: Bars) -> tuple[dict[str, float], dict]:
    """Equal capital per strategy; sum their latest target weights."""
    if not strats:
        return {}, {}
    alloc = 1.0 / len(strats)
    total: dict[str, float] = {}
    detail = {}
    for s in strats:
        syms = [x for x in s["symbols"] if x in bars.symbols]
        w = build(s["family"], s["params"]).target_weights(bars.select(syms)).iloc[-1]
        w = w[w > 1e-6]
        detail[s["id"]] = {k: round(float(v), 4) for k, v in w.items()}
        for sym, x in w.items():
            total[sym] = total.get(sym, 0.0) + alloc * float(x)
    return total, detail


def completed_bars(bars: Bars, tz: str) -> Bars:
    """Drop today's (possibly partial) bar: signals use completed sessions only."""
    today = pd.Timestamp(datetime.now(ZoneInfo(tz)).date())
    return bars.slice(None, today - pd.Timedelta(days=1))


# ---------------------------------------------------------------------------
# review: forward-test tracking, promotion eligibility, demotion
# ---------------------------------------------------------------------------
def review(cfg, store: Store, bars: Bars) -> list[str]:
    p = cfg.section("promotion")
    msgs = []
    for s in store.strategies(["paper", "live"]):
        since = pd.Timestamp(s["live_since"] if s["status"] == "live" else s["paper_since"]).tz_localize(None).normalize()
        syms = [x for x in s["symbols"] if x in bars.symbols]
        r, _, _ = evaluate(s["family"], s["params"], bars.select(syms), cfg)
        fwd = r.loc[since + pd.Timedelta(days=1):]
        m = compute_metrics(fwd) if len(fwd) > 1 else {"days": len(fwd)}
        bt_dd = (s.get("research") or {}).get("max_drawdown", 0.2)
        limit = max(p["demote_dd_multiple"] * bt_dd, p["min_demote_dd"])
        m["demote_dd_limit"] = limit
        m["eligible_for_live"] = bool(s["status"] == "paper" and m.get("days", 0) >= p["min_paper_days"]
                                      and m.get("max_drawdown", 0) <= limit and m.get("total_return", 0) > -bt_dd / 2)
        store.set_shadow(s["id"], m)
        if m.get("max_drawdown", 0) > limit:
            store.set_status(s["id"], "retired", notes=f"auto-retired: forward DD {m['max_drawdown']:.1%} > {limit:.1%}")
            msgs.append(f"strategy #{s['id']} {s['family']} RETIRED (forward drawdown {m['max_drawdown']:.1%})")
        elif m["eligible_for_live"] and not (s.get("shadow") or {}).get("eligible_for_live"):
            msgs.append(f"strategy #{s['id']} {s['family']} passed {m['days']} days of paper trading "
                        f"(return {m.get('total_return', 0):.1%}) -- run `tradebot approve {s['id']}` to trade it live")
    for msg in msgs:
        notify(msg)
    return msgs


# ---------------------------------------------------------------------------
# rebalance
# ---------------------------------------------------------------------------
def rebalance(cfg, mode: str = "paper", dry_run: bool = False, force: bool = False,
              bars: Bars | None = None, broker: Broker | None = None, today=None) -> dict:
    if mode == "live" and broker is None:
        ok, why = cfg.live_allowed()
        if not ok:
            raise RuntimeError(f"live trading blocked: {why}")
    store = Store(cfg.db_path)
    tz = cfg.section("bot")["timezone"]
    today = today or datetime.now(ZoneInfo(tz)).date()
    summary: dict = {"mode": mode, "date": str(today), "dry_run": dry_run, "orders": [], "notes": []}
    if not force and store.get(f"last_rebalance:{mode}") == str(today):
        summary["notes"].append("already rebalanced today (use --force to override)")
        return summary

    strats = active_strategies(store, mode)
    syms = sorted({x for s in strats for x in s["symbols"]} | set(store.positions(mode)))
    if bars is None:
        bars = completed_bars(load_bars(cfg, syms or cfg.symbols, refresh=False), tz)
    broker = broker or make_broker(cfg, store, mode, bars)
    if not broker.is_market_open(today):
        summary["notes"].append("market closed today")
        return summary
    last_bar = bars.index[-1].date()
    if (today - last_bar).days > 5:
        summary["notes"].append(f"data stale: last bar {last_bar}; refusing to trade")
        notify(f"[{mode}] refusing to trade: stale data (last bar {last_bar})")
        return summary

    run_id = store.start_run("rebalance", mode)
    if mode == "live":
        r = cfg.section("risk")
        acct = broker.account_summary()
        store.init_book("live", min(float(r["bot_capital"]), acct["liquidation_value"]))
        _reconcile(store, broker, summary)

    positions = {s: p["qty"] for s, p in store.positions(mode).items()}
    quotes = broker.quotes(sorted(set(positions) | {x for s in strats for x in s["symbols"]}))
    cash = store.cash(mode)
    equity = cash + sum(q * quotes[s].mid for s, q in positions.items() if s in quotes)
    summary.update(equity=round(equity, 2), cash=round(cash, 2), strategies=[s["id"] for s in strats])

    targets, detail = combined_targets(strats, bars)
    summary["strategy_targets"] = detail
    risk = RiskManager(cfg, store)
    dec = risk.evaluate(mode, targets, equity, bars)
    summary["notes"] += dec.notes
    if dec.halt:
        _finish(store, run_id, mode, today, equity, cash, summary, dry_run)
        return summary
    targets = {} if dec.flatten else dec.targets
    summary["targets"] = {k: round(v, 4) for k, v in targets.items() if v > 0}

    ex, rk = cfg.section("execution"), cfg.section("risk")
    orders, notes = plan_orders(
        targets, equity, positions, quotes, band=cfg.section("backtest")["rebalance_band"],
        allow_buys=dec.allow_buys and not dec.flatten, order_type=ex["order_type"],
        collar_bps=ex["limit_collar_bps"], max_orders=rk["max_orders_per_run"],
        max_order_notional=rk["max_position_pct"] * equity * 1.05)
    summary["notes"] += notes
    if dry_run:
        summary["orders"] = [o.__dict__ for o in orders]
        store.finish_run(run_id, summary)
        return summary

    # Sells first, then buys limited by actual cash (book cash and, live, broker cash).
    for o in [o for o in orders if o.side == "SELL"]:
        _execute(store, broker, run_id, mode, o, summary)
    avail = store.cash(mode)
    if mode == "live":
        avail = min(avail, broker.account_summary()["cash_available"])
    for o in [o for o in orders if o.side == "BUY"]:
        px = o.limit_price or quotes[o.symbol].ask or quotes[o.symbol].mid
        if o.qty * px > avail:
            o.qty = int(avail // px)
            if o.qty <= 0:
                summary["notes"].append(f"{o.symbol}: skipped buy, out of cash")
                continue
        res = _execute(store, broker, run_id, mode, o, summary)
        avail -= res.filled_qty * (res.avg_price or px)

    positions = {s: p["qty"] for s, p in store.positions(mode).items()}
    cash = store.cash(mode)
    equity = cash + sum(q * quotes[s].mid for s, q in positions.items() if s in quotes)
    _finish(store, run_id, mode, today, equity, cash, summary, dry_run)
    filled = [o for o in summary["orders"] if o["status"] in ("FILLED", "PARTIAL")]
    problems = [o for o in summary["orders"] if o["status"] not in ("FILLED", "PARTIAL")]
    notify(f"[{mode}] rebalance {today}: equity ${equity:,.2f}, {len(filled)} fills"
           + (f", {len(problems)} problem orders" if problems else "")
           + (f" | {'; '.join(dec.notes)}" if dec.notes else ""))
    return summary


def _execute(store, broker, run_id, mode, o: OrderRequest, summary):
    res = broker.submit(o)
    if res.filled_qty > 0 and res.avg_price:
        signed = res.filled_qty if o.side == "BUY" else -res.filled_qty
        store.apply_fill(mode, o.symbol, signed, res.avg_price)
    row = {**o.__dict__, "broker_order_id": res.broker_order_id, "status": res.status,
           "filled_qty": res.filled_qty, "avg_price": res.avg_price, "error": res.error}
    store.record_order(run_id, mode, row)
    summary["orders"].append(row)
    if res.status not in ("FILLED", "PARTIAL"):
        log.warning("order %s %s %s: %s %s", o.side, o.qty, o.symbol, res.status, res.error)
    return res


def _reconcile(store, broker, summary):
    """Bot may only manage shares it bought. If you sold some by hand, adopt that."""
    actual = broker.broker_positions()
    for sym, p in store.positions("live").items():
        have = actual.get(sym, 0.0)
        if have + 1e-9 < p["qty"]:
            summary["notes"].append(f"{sym}: ledger {p['qty']} > broker {have}; reducing ledger")
            store.set_position("live", sym, max(have, 0.0))


def _finish(store, run_id, mode, today, equity, cash, summary, dry_run):
    summary.update(equity_after=round(equity, 2), cash_after=round(cash, 2))
    if not dry_run:
        store.record_equity(mode, str(today), equity, cash)
        store.set(f"last_rebalance:{mode}", str(today))
    store.finish_run(run_id, summary)


# ---------------------------------------------------------------------------
# daemon
# ---------------------------------------------------------------------------
def daemon(cfg, mode: str = "paper") -> None:  # pragma: no cover - long-running loop
    from ..research.discovery import discover

    tz = ZoneInfo(cfg.section("bot")["timezone"])
    hh, mm = map(int, cfg.section("bot")["run_time"].split(":"))
    every = int(cfg.section("bot")["discover_every_days"])
    log.info("daemon started in %s mode; rebalance daily at %02d:%02d %s", mode, hh, mm, tz)
    while True:
        now = datetime.now(tz)
        run_at = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        research_at = now.replace(hour=18, minute=0, second=0, microsecond=0)
        nxt = min(t if t > now else t + timedelta(days=1) for t in (run_at, research_at))
        time.sleep(max(1.0, (nxt - now).total_seconds()))
        store = Store(cfg.db_path)
        try:
            if nxt.hour == hh and nxt.minute == mm:
                s = rebalance(cfg, mode)
                log.info("rebalance: %s", {k: s.get(k) for k in ("equity_after", "notes")})
            else:
                bars = load_bars(cfg, sorted(set(cfg.symbols) | {x for s in store.strategies(['paper', 'live'])
                                                                for x in s['symbols']}), refresh=False)
                review(cfg, store, completed_bars(bars, cfg.section("bot")["timezone"]))
                last = store.get("last_discovery")
                if not last or datetime.now() - datetime.fromisoformat(last) > timedelta(days=every):
                    s = discover(cfg, bars.select([x for x in cfg.symbols if x in bars.symbols]), store)
                    notify(f"discovery: {s['trials']} trials, {len(s['candidates'])} candidates, "
                           f"promoted to paper: {s['promoted']}")
        except Exception as exc:
            log.exception("daemon step failed")
            notify(f"[{mode}] daemon error: {exc}")
