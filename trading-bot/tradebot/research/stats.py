"""Statistics that correct for luck and multiple testing.

References:
  Bailey & Lopez de Prado (2012) "The Sharpe Ratio Efficient Frontier" -- PSR.
  Bailey & Lopez de Prado (2014) "The Deflated Sharpe Ratio" -- DSR.
When you try N strategies, the best one's Sharpe is inflated by selection.
DSR asks: what's the probability the true Sharpe > 0, given that we picked
the best of N noisy trials?
"""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np

_N = NormalDist()
EULER_GAMMA = 0.5772156649015329


def probabilistic_sharpe(sr: float, n_obs: int, skew: float = 0.0, kurt: float = 3.0,
                         sr_benchmark: float = 0.0) -> float:
    """PSR: P(true SR > sr_benchmark). Sharpe values are PER-PERIOD (daily), not annualised."""
    if n_obs < 3:
        return 0.0
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr ** 2
    if denom <= 0:
        return 0.0
    z = (sr - sr_benchmark) * math.sqrt(n_obs - 1) / math.sqrt(denom)
    return _N.cdf(z)


def expected_max_sharpe(trial_sharpes_var: float, n_trials: int) -> float:
    """Expected maximum per-period SR among n_trials of zero-skill strategies."""
    if n_trials <= 1 or trial_sharpes_var <= 0:
        return 0.0
    a = _N.inv_cdf(1 - 1 / n_trials)
    b = _N.inv_cdf(1 - 1 / (n_trials * math.e))
    return math.sqrt(trial_sharpes_var) * ((1 - EULER_GAMMA) * a + EULER_GAMMA * b)


def deflated_sharpe(sr: float, n_obs: int, skew: float, kurt: float,
                    trial_sharpes: list[float] | np.ndarray, n_trials: int | None = None) -> float:
    """DSR for a strategy picked from many trials. All Sharpes per-period (daily)."""
    ts = np.asarray(trial_sharpes, dtype=float)
    ts = ts[np.isfinite(ts)]
    n = n_trials or len(ts)
    var = float(ts.var(ddof=1)) if len(ts) > 1 else 0.0
    sr0 = expected_max_sharpe(var, n)
    return probabilistic_sharpe(sr, n_obs, skew, kurt, sr_benchmark=sr0)


def annual_to_daily(sr_annual: float) -> float:
    return sr_annual / math.sqrt(252)
