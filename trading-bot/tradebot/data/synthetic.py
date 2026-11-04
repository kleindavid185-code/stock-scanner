"""Deterministic synthetic market for demos and tests (NOT real data).

Prices follow a regime-switching random walk with a common market factor, so
trend/mean-reversion code paths get exercised. Results on this data say nothing
about real-world profitability.
"""
from __future__ import annotations

import zlib
from datetime import date

import numpy as np
import pandas as pd


def synthetic_bars(symbol: str, start: date, end: date, seed: int = 7, trend_edge: float = 0.0,
                   regimes: bool = True) -> pd.DataFrame:
    """trend_edge > 0 plants a persistent (slowly mean-reverting) drift in each
    asset, i.e. a genuine momentum effect a trend strategy should be able to find.
    regimes=False gives a pure zero-drift random walk: NO strategy has an edge."""
    idx = pd.bdate_range(start, end)
    n = len(idx)
    mkt_rng = np.random.default_rng(seed)
    regime = np.cumsum(mkt_rng.normal(0, 1, n) > 2.2) % 2  # occasional regime flips
    if regimes:
        mkt = mkt_rng.normal(np.where(regime == 0, 0.0004, -0.0002), np.where(regime == 0, 0.009, 0.018))
    else:
        mkt = mkt_rng.normal(0.0, 0.012, n)
    rng = np.random.default_rng(seed + zlib.crc32(symbol.encode()))
    beta = rng.uniform(0.5, 1.5)
    idio = rng.normal(0, rng.uniform(0.006, 0.02), n)
    drift = rng.normal(0.0001, 0.0002) if regimes else 0.0
    if trend_edge:
        shocks = rng.normal(0, trend_edge * np.sqrt(1 - 0.995 ** 2), n)
        persistent = np.zeros(n)
        for i in range(1, n):
            persistent[i] = 0.995 * persistent[i - 1] + shocks[i]
        drift = drift + persistent
    r = drift + beta * mkt + idio
    close = 50 * np.exp(np.cumsum(r)) * rng.uniform(0.5, 4)
    gap = rng.normal(0, 0.003, n)
    open_ = np.r_[close[0], close[:-1]] * np.exp(gap)
    hi = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
    lo = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
    vol = rng.uniform(2e6, 2e7) * np.exp(rng.normal(0, 0.3, n))
    return pd.DataFrame({"open": open_, "high": hi, "low": lo, "close": close, "volume": vol}, index=idx)


class SyntheticProvider:
    def __init__(self, seed: int = 7, trend_edge: float = 0.0, regimes: bool = True):
        self.seed = seed
        self.trend_edge = trend_edge
        self.regimes = regimes

    def fetch(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        return synthetic_bars(symbol, start, end, self.seed, self.trend_edge, self.regimes)
