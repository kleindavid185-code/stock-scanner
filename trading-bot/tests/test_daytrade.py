import numpy as np
import pandas as pd
import pytest

from tradebot.backtest.daytrade import run_daytrade_backtest
from tradebot.backtest.engine import CostModel
from tradebot.data.base import align_panel
from tradebot.research.discovery import discover, promote_candidates
from tradebot.store import Store
from tradebot.strategies import DAY_STRATEGIES, STRATEGIES, build


def two_day_bars():
    idx = pd.bdate_range("2024-01-01", periods=3)
    df = pd.DataFrame({"open": [100, 100, 110], "high": [101, 105, 121], "low": [99, 99, 109],
                       "close": [100, 104, 121], "volume": 1e7}, index=idx, dtype=float)
    return align_panel({"X": df})


def test_open_to_close_returns_and_flat_overnight():
    bars = two_day_bars()
    w = pd.DataFrame([[0.0], [1.0], [0.0]], index=bars.index, columns=["X"])
    res = run_daytrade_backtest(bars, w, CostModel(slippage_bps=0), initial_capital=1000)
    assert np.isclose(res.equity.iloc[1], 1040)      # bought 100 at open, sold 104 at close
    assert np.isclose(res.equity.iloc[2], 1040)      # flat: day-3 gap up and rally not captured
    assert len(res.trades) == 1


def test_slippage_charged_both_sides_every_day():
    idx = pd.bdate_range("2024-01-01", periods=252)
    df = pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1e7}, index=idx)
    bars = align_panel({"X": df})
    w = pd.DataFrame(1.0, index=idx, columns=["X"])
    res = run_daytrade_backtest(bars, w, CostModel(slippage_bps=5), initial_capital=10_000)
    # ~10 bps/day for a year on a flat market ~ -22%: why daily trading costs matter.
    assert -0.24 < res.metrics["total_return"] < -0.20


@pytest.mark.parametrize("name", sorted(DAY_STRATEGIES))
def test_day_strategy_cannot_see_past_the_open(name, bars):
    """Changing day t's high/low/close must not change day t's decision."""
    rng = np.random.default_rng(1)
    for _ in range(3):
        params = STRATEGIES[name].sample_params(__import__("random").Random(int(rng.integers(1e9))))
        s = build(name, params)
        t = bars.index[int(rng.integers(300, len(bars.index) - 5))]
        base = s.target_weights(bars).loc[t]
        mod = bars.slice(None, None)
        for f in ("close", "high", "low"):
            frame = getattr(mod, f).copy()
            frame.loc[t] *= 1.25
            setattr(mod, f, frame)
        np.testing.assert_allclose(base.to_numpy(), s.target_weights(mod).loc[t].to_numpy(), atol=1e-12,
                                   err_msg=f"{s} looks past the open on {t}")


def test_daytrade_discovery_runs_but_never_auto_promotes(cfg):
    from tradebot.data.base import load_bars
    from tradebot.data.synthetic import SyntheticProvider

    st = Store(cfg.db_path)
    b = load_bars(cfg, ["A1", "A2", "A3", "A4", "SPY"], start="2010-01-01", end="2025-06-30",
                  provider=SyntheticProvider(seed=4, regimes=False))
    s = discover(cfg, b, st, n_trials=40, seed=3, families=list(DAY_STRATEGIES))
    assert s["promoted"] == [] and s["benchmark_cagr"] is not None
    # Even a forced candidate must not be promoted to paper.
    sid = st.upsert_strategy("forced", "day_gap_fade", {}, ["A1"], "candidate")
    assert sid not in promote_candidates(cfg, st)
