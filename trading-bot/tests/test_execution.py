import os

import pandas as pd
import pytest

from tradebot.broker.base import Quote
from tradebot.broker.paper import PaperBroker, last_close_quotes
from tradebot.execution.planner import plan_orders
from tradebot.execution.risk import RiskManager
from tradebot.live.runner import make_broker, rebalance
from tradebot.store import Store

from .conftest import flat_bars


def q(px):
    return Quote("X", px * 0.999, px * 1.001, px)


def test_planner_whole_shares_and_sells_first():
    quotes = {"A": q(100), "B": q(50)}
    orders, _ = plan_orders({"B": 0.5}, 10_000, {"A": 30}, quotes, band=0.0)
    assert [o.side for o in orders] == ["SELL", "BUY"]
    assert orders[0].qty == 30 and orders[1].qty == 100
    assert all(isinstance(o.qty, int) for o in orders)
    assert orders[1].limit_price > quotes["B"].ask


def test_planner_band_skips_small_but_always_fully_exits():
    quotes = {"A": q(100), "B": q(100)}
    orders, _ = plan_orders({"A": 0.505}, 10_000, {"A": 50, "B": 1}, quotes, band=0.02)
    assert len(orders) == 1 and orders[0].symbol == "B" and orders[0].side == "SELL"


def test_planner_respects_buy_block():
    orders, notes = plan_orders({"A": 0.5}, 10_000, {}, {"A": q(100)}, allow_buys=False)
    assert orders == [] and notes


def test_risk_caps_filters_and_kill(cfg):
    st = Store(cfg.db_path)
    rm = RiskManager(cfg, st)
    bars = flat_bars(40, symbols=("A", "B", "PENNY"))
    bars.close["PENNY"] = 1.0
    d = rm.evaluate("paper", {"A": 0.6, "B": 0.1, "PENNY": 0.1}, 10_000, bars)
    assert d.targets["A"] == pytest.approx(0.20) and d.targets["PENNY"] == 0
    # Drawdown beyond limit -> flatten + kill persists.
    d = rm.evaluate("paper", {"A": 0.2}, 7_000, bars)
    assert d.flatten and rm.killed("paper")
    d = rm.evaluate("paper", {"A": 0.2}, 7_000, bars)
    assert d.halt
    rm.reset_kill("paper")
    assert not rm.killed("paper")
    (cfg.state_dir / "KILL").touch()
    assert rm.evaluate("paper", {"A": 0.2}, 7_000, bars).halt


def test_daily_loss_limit_blocks_buys(cfg):
    st = Store(cfg.db_path)
    st.record_equity("paper", "2024-01-01", 10_000, 0)
    d = RiskManager(cfg, st).evaluate("paper", {}, 9_500, flat_bars(40))
    assert not d.allow_buys


def test_live_requires_both_interlocks(cfg, monkeypatch):
    st = Store(cfg.db_path)
    with pytest.raises(RuntimeError, match="live trading blocked"):
        make_broker(cfg, st, "live")
    cfg.raw["execution"]["live_trading_enabled"] = True
    with pytest.raises(RuntimeError, match="TRADEBOT_LIVE_CONFIRM"):
        make_broker(cfg, st, "live")


def test_paper_rebalance_end_to_end(cfg):
    st = Store(cfg.db_path)
    bars = flat_bars(300, symbols=("A", "B", "C"))
    # Rising prices so trend_sma wants to hold everything.
    for i, s in enumerate(bars.symbols):
        ramp = pd.Series(range(len(bars.index)), index=bars.index) * (0.1 + i * 0.05) + 50
        for f in ("open", "high", "low", "close"):
            getattr(bars, f)[s] = ramp
    sid = st.upsert_strategy("k1", "trend_sma", {"sma": 100, "rebalance": 1, "max_positions": 5,
                                                 "sizing": "equal", "vol_target": 0.0},
                             ["A", "B", "C"], "paper")
    st.set_status(sid, "paper")
    today = (bars.index[-1] + pd.Timedelta(days=1)).date()
    while today.weekday() >= 5:
        today += pd.Timedelta(days=1)
    out = rebalance(cfg, "paper", bars=bars, today=today)
    assert {o["symbol"] for o in out["orders"]} == {"A", "B", "C"}
    assert all(o["status"] == "FILLED" for o in out["orders"])
    pos = st.positions("paper")
    assert set(pos) == {"A", "B", "C"}
    assert st.cash("paper") >= 0
    assert abs(out["equity_after"] - 10_000) < 50  # only costs lost
    again = rebalance(cfg, "paper", bars=bars, today=today)
    assert again["orders"] == [] and "already rebalanced" in again["notes"][0]


def test_paper_broker_rejects_overspend(cfg):
    st = Store(cfg.db_path)
    st.init_book("paper", 1000)
    b = PaperBroker(st, last_close_quotes(flat_bars(5)))
    from tradebot.broker.base import OrderRequest

    assert b.submit(OrderRequest("X", "BUY", 50, "market")).status == "REJECTED"
    assert b.submit(OrderRequest("X", "BUY", 5, "market")).status == "FILLED"
    assert b.submit(OrderRequest("X", "SELL", 10, "market")).status == "REJECTED"
