"""Share-level daily portfolio simulator.

Timing model (no look-ahead):
  * Strategy weights for row t are computed from data up to the close of day t.
  * They are executed at the OPEN of day t+1, with slippage + commission.
  * Equity is marked at each close.
Positions drift with prices between rebalances; trades smaller than
`rebalance_band` x equity are skipped (except full exits) to limit churn.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..data.base import Bars


@dataclass
class CostModel:
    commission_bps: float = 0.0
    slippage_bps: float = 5.0
    commission_per_trade: float = 0.0

    @property
    def side_bps(self) -> float:
        return self.commission_bps + self.slippage_bps


@dataclass
class BacktestResult:
    equity: pd.Series
    returns: pd.Series
    weights: pd.DataFrame          # realised end-of-day weights
    trades: pd.DataFrame           # closed round trips
    turnover: pd.Series            # traded notional / equity per day
    costs: float
    metrics: dict = field(default_factory=dict)


def run_backtest(bars: Bars, weights: pd.DataFrame, costs: CostModel | None = None,
                 initial_capital: float = 100_000.0, rebalance_band: float = 0.02,
                 start=None) -> BacktestResult:
    from .metrics import compute_metrics

    costs = costs or CostModel()
    weights = weights.reindex(index=bars.index, columns=bars.symbols).fillna(0.0)
    if start is not None:
        weights = weights.loc[start:]
        bars = bars.slice(weights.index[0], None)
    idx = bars.index
    o = bars.open.to_numpy(float)
    c = bars.close.to_numpy(float)
    c_ff = bars.close.ffill().to_numpy(float)   # mark delisted/halted names at last price
    o = np.where(np.isnan(o), c, o)               # some feeds miss opens
    tw = weights.to_numpy(float)
    n, k = c.shape
    slip = costs.side_bps / 1e4

    cash = initial_capital
    sh = np.zeros(k)
    basis = np.zeros(k)          # average cost per share of open position
    entry_date = [None] * k
    equity = np.empty(n)
    realised_w = np.zeros((n, k))
    turnover = np.zeros(n)
    total_cost = 0.0
    trades = []

    for i in range(n):
        if i > 0:
            target = tw[i - 1]
            px = o[i]
            tradable = ~np.isnan(px)
            mark = np.where(tradable, px, c_ff[i - 1])
            mark = np.nan_to_num(mark)
            eq_open = cash + float(sh @ mark)
            if eq_open > 0:
                cur_w = sh * mark / eq_open
                desired = np.where(tradable, target, cur_w)
                delta_w = desired - cur_w
                trade_mask = tradable & ((np.abs(delta_w) > rebalance_band) | ((desired == 0) & (sh != 0)))
                # Sells first so buys are funded by sale proceeds.
                for j in np.argsort(delta_w):
                    if not trade_mask[j]:
                        continue
                    q = desired[j] * eq_open / px[j] - sh[j]
                    if q == 0:
                        continue
                    fill = px[j] * (1 + slip if q > 0 else 1 - slip)
                    if q > 0:  # never spend cash we don't have
                        q = min(q, max(cash - costs.commission_per_trade, 0) / fill)
                        if q <= 1e-9:
                            continue
                    notional = abs(q) * fill
                    fee = notional * costs.commission_bps / 1e4 + costs.commission_per_trade
                    total_cost += abs(q) * px[j] * costs.slippage_bps / 1e4 + fee
                    turnover[i] += notional / eq_open
                    if q > 0:
                        if sh[j] == 0:
                            entry_date[j] = idx[i]
                        basis[j] = (basis[j] * sh[j] + q * fill) / (sh[j] + q)
                        cash -= notional + fee
                        sh[j] += q
                    else:
                        sold = min(-q, sh[j])
                        trades.append((bars.symbols[j], entry_date[j], idx[i], basis[j], fill, sold,
                                       sold * (fill - basis[j]) - fee))
                        cash += notional - fee
                        sh[j] += q
                        if abs(sh[j]) < 1e-9:
                            sh[j] = 0.0
                            basis[j] = 0.0
                            entry_date[j] = None
        mark_c = np.nan_to_num(c_ff[i])
        equity[i] = cash + float(sh @ mark_c)
        if equity[i] > 0:
            realised_w[i] = sh * mark_c / equity[i]

    eq = pd.Series(equity, index=idx, name="equity")
    rets = eq.pct_change().fillna(0.0)
    trades_df = pd.DataFrame(trades, columns=["symbol", "entry", "exit", "entry_px", "exit_px", "qty", "pnl"])
    if len(trades_df):
        trades_df["ret"] = trades_df["exit_px"] / trades_df["entry_px"] - 1
    res = BacktestResult(eq, rets, pd.DataFrame(realised_w, index=idx, columns=bars.symbols),
                         trades_df, pd.Series(turnover, index=idx), total_cost)
    res.metrics = compute_metrics(rets, trades_df, res.turnover, res.weights)
    return res
