import numpy as np

from tradebot.research.stats import deflated_sharpe, expected_max_sharpe, probabilistic_sharpe
from tradebot.research.walkforward import walk_forward
import pandas as pd


def test_psr_increases_with_sharpe_and_sample():
    assert probabilistic_sharpe(0.05, 1000) > probabilistic_sharpe(0.02, 1000)
    assert probabilistic_sharpe(0.05, 2000) > probabilistic_sharpe(0.05, 500)
    assert abs(probabilistic_sharpe(0.0, 1000) - 0.5) < 1e-9


def test_expected_max_sharpe_grows_with_trials():
    assert expected_max_sharpe(1e-4, 1000) > expected_max_sharpe(1e-4, 10) > 0


def test_best_of_many_noise_strategies_is_not_significant():
    rng = np.random.default_rng(1)
    n, k = 1500, 200
    rets = rng.normal(0, 0.01, (n, k))
    srs = rets.mean(0) / rets.std(0)
    best = srs.max()
    # Naive PSR says "significant"; DSR correctly says "probably luck".
    assert probabilistic_sharpe(best, n) > 0.95
    assert deflated_sharpe(best, n, 0.0, 3.0, srs) < 0.95


def test_walk_forward_is_out_of_sample():
    idx = pd.bdate_range("2010-01-01", "2020-12-31")
    good_early = pd.Series(np.where(idx.year < 2015, 0.002, -0.002), index=idx)
    good_late = -good_early
    wf = walk_forward({"a": good_early, "b": good_late}, train_years=2, test_years=1)
    # Picks 'a' while it worked in training; is punished when regime flips.
    assert wf.oos_returns.index.min() >= idx[0] + pd.DateOffset(years=2) - pd.Timedelta(days=3)
    assert len(wf.chosen) >= 8
