import numpy as np
import pandas as pd

from tradebot.backtest.engine import CostModel, run_backtest
from tradebot.data.base import align_panel

from .conftest import flat_bars


def stepping_bars():
    idx = pd.bdate_range("2024-01-01", periods=10)
    close = pd.Series(np.arange(100, 110, dtype=float), index=idx)
    df = pd.DataFrame({"open": close - 0.5, "high": close + 1, "low": close - 1, "close": close,
                       "volume": 1e7})
    return align_panel({"X": df})


def test_signal_at_close_executes_next_open():
    bars = stepping_bars()
    w = pd.DataFrame(0.0, index=bars.index, columns=["X"])
    w.iloc[3:] = 1.0  # decided at close of day 3
    res = run_backtest(bars, w, CostModel(slippage_bps=0), initial_capital=1000, rebalance_band=0)
    eq = res.equity
    assert (eq.iloc[:4] == 1000).all(), "no exposure until the open after the signal"
    # Bought at open of day 4 (=103.5), marked at close 104.
    assert np.isclose(eq.iloc[4], 1000 * 104 / 103.5)


def test_round_trip_costs_charged():
    bars = flat_bars(10)
    w = pd.DataFrame(0.0, index=bars.index, columns=["X"])
    w.iloc[2:5] = 1.0
    res = run_backtest(bars, w, CostModel(slippage_bps=10), initial_capital=10_000, rebalance_band=0)
    loss = 10_000 - res.equity.iloc[-1]
    assert 19 < loss < 21  # ~2 x 10bps
    assert len(res.trades) == 1 and res.trades["pnl"].iloc[0] < 0


def test_never_spends_more_cash_than_available():
    bars = flat_bars(10, symbols=("X", "Y"))
    w = pd.DataFrame(0.9, index=bars.index, columns=["X", "Y"])  # 180% gross requested
    res = run_backtest(bars, w, CostModel(slippage_bps=5), initial_capital=10_000, rebalance_band=0)
    assert res.weights.sum(axis=1).max() <= 1.0 + 1e-9
    assert (res.equity > 0).all()


def test_rebalance_band_reduces_churn():
    bars = flat_bars(50)
    w = pd.DataFrame(0.5, index=bars.index, columns=["X"])
    w.iloc[::2] = 0.51  # tiny oscillation
    tight = run_backtest(bars, w, rebalance_band=0.0)
    banded = run_backtest(bars, w, rebalance_band=0.02)
    # Ignore the initial purchase; compare ongoing churn.
    assert banded.turnover.iloc[2:].sum() < tight.turnover.iloc[2:].sum() / 5
    assert banded.turnover.iloc[2:].sum() == 0
