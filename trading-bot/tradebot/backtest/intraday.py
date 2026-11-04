"""Portfolio simulator for 5-minute intraday strategies (flat every night)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .engine import BacktestResult, CostModel


def run_intraday_backtest(data, strat, costs: CostModel | None = None,
                          initial_capital: float = 100_000.0) -> BacktestResult:
    from .metrics import compute_metrics

    costs = costs or CostModel()
    direction, entry, exit_px, score = strat.plan(data)
    slip = costs.side_bps / 1e4
    valid = (direction != 0) & np.isfinite(entry) & np.isfinite(exit_px) & (entry > 0)
    valid[: strat.warmup] = False
    ret = np.where(valid, direction * (exit_px / np.where(valid, entry, 1.0) - 1) - 2 * slip, 0.0)
    # Choose up to max_positions symbols per day by score; each gets 1/max_positions of equity.
    k = int(strat.params["max_positions"])
    sc = np.where(valid, np.nan_to_num(score, nan=0.0), -np.inf)
    rank = (-sc).argsort(axis=1).argsort(axis=1)
    chosen = valid & (rank < k)
    w = chosen / k
    port_r = pd.Series((w * ret).sum(axis=1), index=data.days)
    equity = initial_capital * (1 + port_r).cumprod()
    eq_start = equity.shift(1).fillna(initial_capital).to_numpy()

    di, si = np.nonzero(chosen)
    if len(di):
        d = direction[di, si]
        entry_fill = entry[di, si] * (1 + slip * d)
        exit_fill = exit_px[di, si] * (1 - slip * d)
        qty = w[di, si] * eq_start[di] / entry_fill
        trades = pd.DataFrame({"symbol": np.array(data.symbols)[si], "entry": data.days[di], "exit": data.days[di],
                               "side": np.where(d > 0, "long", "short"), "entry_px": entry_fill,
                               "exit_px": exit_fill, "qty": qty})
        trades["pnl"] = trades["qty"] * (trades["exit_px"] - trades["entry_px"]) * d
        trades["ret"] = d * (trades["exit_px"] / trades["entry_px"] - 1)
    else:
        trades = pd.DataFrame(columns=["symbol", "entry", "exit", "side", "entry_px", "exit_px", "qty", "pnl", "ret"])
    wdf = pd.DataFrame(w, index=data.days, columns=data.symbols)
    turnover = 2 * wdf.sum(axis=1)
    res = BacktestResult(equity.rename("equity"), port_r, wdf, trades, turnover, float((turnover * slip * eq_start).sum()))
    res.metrics = compute_metrics(port_r, trades, turnover, wdf)
    return res
