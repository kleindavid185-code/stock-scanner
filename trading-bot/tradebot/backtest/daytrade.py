"""Day-trading simulator: buy at the OPEN, sell at the CLOSE, flat every night.

Row t of `weights` is the fraction of equity to put into each symbol at the open
of day t. It may use the day-t opening price (you see the open, then trade) but
nothing after it. Slippage is charged on both the entry and the exit, every day.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data.base import Bars
from .engine import BacktestResult, CostModel


def run_daytrade_backtest(bars: Bars, weights: pd.DataFrame, costs: CostModel | None = None,
                          initial_capital: float = 100_000.0) -> BacktestResult:
    from .metrics import compute_metrics

    costs = costs or CostModel()
    o, c = bars.open, bars.close
    valid = o.notna() & c.notna() & (o > 0)
    w = weights.reindex(index=c.index, columns=c.columns).fillna(0.0).where(valid, 0.0).clip(lower=0.0)
    gross = w.sum(axis=1)
    w = w.div(gross.where(gross > 1.0, 1.0), axis=0)  # never more than 100% invested
    slip = costs.side_bps / 1e4
    asset_r = ((c * (1 - slip)) / (o * (1 + slip)) - 1).where(valid, 0.0)
    port_r = (w * asset_r).sum(axis=1)
    if costs.commission_per_trade:
        n_pos = (w > 0).sum(axis=1)
        eq_prev = initial_capital * (1 + port_r).cumprod().shift(1).fillna(1.0)
        port_r = port_r - 2 * costs.commission_per_trade * n_pos / eq_prev
    equity = initial_capital * (1 + port_r).cumprod()
    eq_start = equity.shift(1).fillna(initial_capital)

    held = w.stack()
    held = held[held > 0]
    if len(held):
        dates = held.index.get_level_values(0)
        syms = held.index.get_level_values(1)
        entry_px = o.stack().reindex(held.index).to_numpy() * (1 + slip)
        exit_px = c.stack().reindex(held.index).to_numpy() * (1 - slip)
        qty = held.to_numpy() * eq_start.reindex(dates).to_numpy() / entry_px
        trades = pd.DataFrame({"symbol": syms, "entry": dates, "exit": dates, "entry_px": entry_px,
                               "exit_px": exit_px, "qty": qty, "pnl": qty * (exit_px - entry_px)})
        trades["ret"] = trades["exit_px"] / trades["entry_px"] - 1
    else:
        trades = pd.DataFrame(columns=["symbol", "entry", "exit", "entry_px", "exit_px", "qty", "pnl", "ret"])
    turnover = 2 * w.sum(axis=1)
    res = BacktestResult(equity.rename("equity"), port_r, w, trades, turnover,
                         float(((w * slip * 2).sum(axis=1) * eq_start).sum()))
    res.metrics = compute_metrics(port_r, trades, turnover, w)
    return res
