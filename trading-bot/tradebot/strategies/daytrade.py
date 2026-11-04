"""Day-trading strategy families (enter at the open, exit at the close, same day).

Each uses only information available at the open of day t: prior closes, and
the day-t opening price (for gap signals). Ideas come from documented effects:
  * day_gap_fade      -- large opening gaps in liquid stocks/ETFs partially fill
  * day_gap_go        -- the opposite: strong gaps continue (tests momentum)
  * day_reversal      -- buy the open after a big down day (short-term reversal)
  * day_rsi           -- buy the open when RSI(2-4) of prior closes is oversold
  * day_always        -- BASELINE: hold every trading day open->close. Shows how
                         much of the market's return happens during the day vs
                         overnight (historically most of it is overnight).
"""
from __future__ import annotations

import pandas as pd

from .. import indicators as ind
from ..data.base import Bars
from .base import Param, Strategy, positions_to_weights


class DayStrategy(Strategy):
    intraday = True
    common_space = (
        Param("max_positions", (1, 3, 5)),
        Param("sizing", ("equal", "inverse_vol")),
    )

    @property
    def warmup(self) -> int:
        return int(self.params.get("trend_sma") or 0) + 25

    def _trend(self, bars: Bars) -> pd.DataFrame:
        n = int(self.params.get("trend_sma") or 0)
        pc = bars.close.shift(1)
        if n <= 0:
            return pc.notna()
        return pc > ind.sma(bars.close, n).shift(1)

    def target_weights(self, bars: Bars) -> pd.DataFrame:
        active, score = self.signals(bars)
        active = active.fillna(False).astype(bool) & bars.open.notna()
        # Size using PRIOR closes only (vol through t-1), so nothing after the open leaks in.
        w = positions_to_weights(active, score, bars.close.shift(1), int(self.params["max_positions"]),
                                 self.params["sizing"])
        w.iloc[: self.warmup] = 0.0
        return w


def _gap(bars: Bars) -> pd.DataFrame:
    return bars.open / bars.close.shift(1) - 1


class DayGapFade(DayStrategy):
    name = "day_gap_fade"
    description = "Buy at the open after a gap down; sell at the close."
    params_space = (Param("gap", (0.005, 0.01, 0.02, 0.03)), Param("trend_sma", (0, 100, 200)))

    def signals(self, bars):
        g = _gap(bars)
        return (g < -float(self.params["gap"])) & self._trend(bars), -g


class DayGapGo(DayStrategy):
    name = "day_gap_go"
    description = "Buy at the open after a gap up; sell at the close."
    params_space = (Param("gap", (0.005, 0.01, 0.02, 0.03)), Param("trend_sma", (0, 100, 200)))

    def signals(self, bars):
        g = _gap(bars)
        return (g > float(self.params["gap"])) & self._trend(bars), g


class DayReversal(DayStrategy):
    name = "day_reversal"
    description = "Buy at the open after a big down day; sell at the close."
    params_space = (Param("drop", (0.01, 0.02, 0.03, 0.05)), Param("trend_sma", (0, 100, 200)))

    def signals(self, bars):
        r1 = bars.close.shift(1) / bars.close.shift(2) - 1
        return (r1 < -float(self.params["drop"])) & self._trend(bars), -r1


class DayRSI(DayStrategy):
    name = "day_rsi"
    description = "Buy at the open when prior-close RSI is oversold; sell at the close."
    params_space = (Param("rsi_len", (2, 3, 4)), Param("entry", (5, 10, 20, 30)),
                    Param("trend_sma", (0, 100, 200)))

    def signals(self, bars):
        r = ind.rsi(bars.close, int(self.params["rsi_len"])).shift(1)
        return (r < float(self.params["entry"])) & self._trend(bars), -r


class DayAlways(DayStrategy):
    name = "day_always"
    description = "Baseline: buy every open, sell every close."
    params_space = (Param("trend_sma", (0, 200)),)

    def signals(self, bars):
        return self._trend(bars), -ind.realized_vol(bars.close, 20).shift(1)


DAY_STRATEGIES = {cls.name: cls for cls in (DayGapFade, DayGapGo, DayReversal, DayRSI, DayAlways)}
