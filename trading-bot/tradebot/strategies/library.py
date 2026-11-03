"""Strategy families grounded in well-documented, peer-reviewed market effects.

Why these: the anomalies with the longest out-of-sample record on liquid assets
are trend/time-series momentum, cross-sectional momentum, and short-horizon mean
reversion in instruments that are in a long-term uptrend. None is guaranteed to
work going forward; the discovery engine decides what survives on your data.
"""
from __future__ import annotations

import pandas as pd

from .. import indicators as ind
from ..data.base import Bars
from .base import Param, Strategy, hold_until_exit, rebalance_every


class TrendSMA(Strategy):
    """Hold assets trading above their N-day moving average (Faber 2007 style)."""

    name = "trend_sma"
    description = "Long assets above their long moving average; cash otherwise."
    params_space = (
        Param("sma", (100, 150, 200, 250)),
        Param("rebalance", (1, 5, 21)),
    )

    @property
    def warmup(self) -> int:
        return int(self.params["sma"]) + 5

    def signals(self, bars: Bars):
        c = bars.close
        m = ind.sma(c, int(self.params["sma"]))
        active = c > m
        score = c / m - 1
        return rebalance_every(active, score, int(self.params["rebalance"]))


class TimeSeriesMomentum(Strategy):
    """Long assets whose own trailing return is positive (Moskowitz, Ooi, Pedersen 2012)."""

    name = "ts_momentum"
    description = "Long assets with positive trailing return over the lookback."
    params_space = (
        Param("lookback", (63, 126, 189, 252)),
        Param("rebalance", (5, 21)),
    )

    @property
    def warmup(self) -> int:
        return int(self.params["lookback"]) + 5

    def signals(self, bars: Bars):
        r = ind.total_return(bars.close, int(self.params["lookback"]))
        return rebalance_every(r > 0, r, int(self.params["rebalance"]))


class CrossSectionalMomentum(Strategy):
    """Rotate into the top-K trailing performers, skipping the last month
    (Jegadeesh & Titman 1993), with an absolute-momentum filter (Antonacci)."""

    name = "xs_momentum"
    description = "Top-K relative strength rotation with absolute momentum filter."
    params_space = (
        Param("lookback", (63, 126, 252)),
        Param("skip", (0, 21)),
        Param("rebalance", (21, 42)),
        Param("abs_filter", (True, False)),
    )

    @property
    def warmup(self) -> int:
        return int(self.params["lookback"]) + 5

    def signals(self, bars: Bars):
        r = ind.total_return(bars.close, int(self.params["lookback"]), int(self.params["skip"]))
        active = r.notna()
        if self.params["abs_filter"]:
            active &= r > 0
        return rebalance_every(active, r, int(self.params["rebalance"]))


class RSIReversion(Strategy):
    """Buy short-term oversold dips in long-term uptrends; sell into strength
    (short-horizon reversal, popularised by Connors' RSI(2))."""

    name = "rsi_reversion"
    description = "Buy RSI dips above the 200-day MA, exit on RSI rebound."
    params_space = (
        Param("rsi_len", (2, 3, 4)),
        Param("entry", (5, 10, 15, 20)),
        Param("exit", (50, 60, 70)),
        Param("trend_sma", (100, 200)),
        Param("max_hold", (5, 10, 20)),
    )

    @property
    def warmup(self) -> int:
        return int(self.params["trend_sma"]) + 5

    def signals(self, bars: Bars):
        c = bars.close
        r = ind.rsi(c, int(self.params["rsi_len"]))
        trend = c > ind.sma(c, int(self.params["trend_sma"]))
        entry = (r < self.params["entry"]) & trend
        exit_ = (r > self.params["exit"]) | ~trend
        held = hold_until_exit(entry, exit_)
        held = _time_stop(held, int(self.params["max_hold"]))
        return held, -r


class BollingerReversion(Strategy):
    """Buy closes far below the rolling mean (z-score) in uptrends; exit at the mean."""

    name = "bollinger_reversion"
    description = "Buy z-score < -k in uptrends, exit at z > 0."
    params_space = (
        Param("window", (10, 20)),
        Param("entry_z", (1.5, 2.0, 2.5)),
        Param("exit_z", (0.0, 0.5)),
        Param("trend_sma", (100, 200)),
        Param("max_hold", (10, 20)),
    )

    @property
    def warmup(self) -> int:
        return int(self.params["trend_sma"]) + 5

    def signals(self, bars: Bars):
        c = bars.close
        z = ind.zscore(c, int(self.params["window"]))
        trend = c > ind.sma(c, int(self.params["trend_sma"]))
        entry = (z < -float(self.params["entry_z"])) & trend
        exit_ = (z > float(self.params["exit_z"])) | ~trend
        held = _time_stop(hold_until_exit(entry, exit_), int(self.params["max_hold"]))
        return held, -z


class DonchianBreakout(Strategy):
    """Enter on an N-day closing high, exit on an M-day closing low (Turtle-style)."""

    name = "donchian_breakout"
    description = "Buy N-day highs, exit at M-day lows."
    params_space = (
        Param("entry_n", (20, 55, 100)),
        Param("exit_n", (10, 20, 50)),
    )

    @property
    def warmup(self) -> int:
        return int(self.params["entry_n"]) + 5

    def signals(self, bars: Bars):
        c = bars.close
        hi = ind.rolling_max(c, int(self.params["entry_n"])).shift(1)
        lo = ind.rolling_min(c, int(self.params["exit_n"])).shift(1)
        held = hold_until_exit(c > hi, c < lo)
        score = ind.total_return(c, int(self.params["entry_n"]))
        return held, score


def _time_stop(held: pd.DataFrame, max_hold: int) -> pd.DataFrame:
    """Force exit after max_hold consecutive bars in a position (no re-entry until the
    underlying signal resets)."""
    h = held.astype(int)
    cs = h.cumsum()
    run = cs - cs.where(h == 0).ffill().fillna(0)
    return held & (run <= max_hold)


STRATEGIES: dict[str, type[Strategy]] = {
    cls.name: cls
    for cls in (TrendSMA, TimeSeriesMomentum, CrossSectionalMomentum, RSIReversion,
                BollingerReversion, DonchianBreakout)
}


def build(name: str, params: dict | None = None) -> Strategy:
    if name not in STRATEGIES:
        raise KeyError(f"unknown strategy {name!r}; choose from {sorted(STRATEGIES)}")
    return STRATEGIES[name](**(params or {}))
