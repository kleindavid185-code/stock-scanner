"""Intraday strategies on 5-minute bars. Every trade opens and closes the same day.

  intraday_orb        Opening-range breakout (Zarattini, Barbon & Aziz 2023):
                      trade in the direction of the first N minutes, stop at the
                      other side of the range, optional profit target, else exit
                      at the close.
  intraday_momentum   Gao, Han, Li & Zhou (2018, JFE): the first half-hour return
                      predicts the last half-hour return. Enter at 15:00/15:30
                      in the direction of the morning move, exit at the close.
  intraday_noise      Zarattini, Aziz & Barbon (2024): enter only when price breaks
                      out of its usual intraday "noise area" (avg move by time of
                      day over recent days); trail with the band or VWAP.

A strategy's plan(data) returns per (day, symbol): direction (+1/-1/0), entry
price, exit price and a ranking score. Decisions only use bars that have closed
before the entry bar opens; tests check this.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data.intraday import SLOTS, IntradayData, slot_of
from .base import Param, Strategy


def first_true(mask: np.ndarray) -> np.ndarray:
    """(days, slots, n) bool -> index of first True along slots, -1 if none."""
    return np.where(mask.any(axis=1), mask.argmax(axis=1), -1)


def take(arr: np.ndarray, idx: np.ndarray) -> np.ndarray:
    """arr (days, slots, n), idx (days, n) -> arr[d, idx, n]; NaN where idx < 0."""
    safe = np.clip(idx, 0, arr.shape[1] - 1)
    out = np.take_along_axis(arr, safe[:, None, :], axis=1)[:, 0, :]
    return np.where(idx >= 0, out, np.nan)


def prev_day(x: np.ndarray) -> np.ndarray:
    out = np.full_like(x, np.nan)
    out[1:] = x[:-1]
    return out


def trailing_mean_days(x: np.ndarray, n: int) -> np.ndarray:
    """Mean over the PREVIOUS n days (excludes today). x: (days, ...)."""
    flat = pd.DataFrame(x.reshape(len(x), -1))
    m = flat.rolling(n, min_periods=n).mean().shift(1).to_numpy()
    return m.reshape(x.shape)


class MinuteStrategy(Strategy):
    intraday = True
    minute_data = True
    common_space = (Param("max_positions", (1, 3, 5)),)

    @property
    def warmup(self) -> int:
        return int(self.params.get("lookback") or 14) + 2

    def _side(self, direction: np.ndarray) -> np.ndarray:
        if not self.params.get("allow_short", False):
            direction = np.where(direction > 0, direction, 0)
        return direction

    def plan(self, d: IntradayData):
        raise NotImplementedError


class IntradayORB(MinuteStrategy):
    name = "intraday_orb"
    description = "Opening-range breakout: follow the first N minutes, stop at the range."
    params_space = (
        Param("range_bars", (1, 3, 6)),          # 5, 15, 30 minutes
        Param("target_r", (0.0, 2.0, 5.0)),      # profit target in multiples of risk; 0 = hold to close
        Param("rvol_min", (0.0, 1.5, 2.5)),      # opening volume vs its 14-day average
        Param("allow_short", (False, True)),
    )

    def plan(self, d: IntradayData):
        k = int(self.params["range_bars"])
        ro, rc = d.o[:, 0, :], d.c[:, k - 1, :]
        rh = np.nanmax(d.h[:, :k, :], axis=1)
        rl = np.nanmin(d.l[:, :k, :], axis=1)
        direction = np.sign(rc - ro)
        rv = np.nansum(d.v[:, :k, :], axis=1)
        avg_rv = trailing_mean_days(rv, 14)
        rvol = rv / avg_rv
        if self.params["rvol_min"] > 0:
            direction = np.where(rvol >= self.params["rvol_min"], direction, 0)
        direction = self._side(direction)
        entry = d.o[:, k, :]
        stop = np.where(direction > 0, rl, rh)
        risk = np.abs(entry - stop)
        ok = (direction != 0) & np.isfinite(entry) & (risk > 0) & ((entry - stop) * direction > 0)
        direction = np.where(ok, direction, 0)
        tr = float(self.params["target_r"])
        target = entry + direction * tr * risk

        after = np.zeros((1, SLOTS, 1), dtype=bool)
        after[:, k:, :] = True
        dl, dh = direction[:, None, :] > 0, direction[:, None, :] < 0
        stop_hit = after & ((dl & (d.l <= stop[:, None, :])) | (dh & (d.h >= stop[:, None, :])))
        s_stop = first_true(stop_hit)
        if tr > 0:
            tgt_hit = after & ((dl & (d.h >= target[:, None, :])) | (dh & (d.l <= target[:, None, :])))
            s_tgt = first_true(tgt_hit)
        else:
            s_tgt = np.full_like(s_stop, -1)
        exit_px = d.last_close.copy()
        o_stop = take(d.o, s_stop)
        stop_fill = np.where(direction > 0, np.fmin(o_stop, stop), np.fmax(o_stop, stop))
        o_tgt = take(d.o, s_tgt)
        tgt_fill = np.where(direction > 0, np.fmax(o_tgt, target), np.fmin(o_tgt, target))
        use_stop = (s_stop >= 0) & ((s_tgt < 0) | (s_stop <= s_tgt))   # same bar -> assume stop first
        use_tgt = (s_tgt >= 0) & ~use_stop
        exit_px = np.where(use_stop, stop_fill, np.where(use_tgt, tgt_fill, exit_px))
        score = np.abs(rc / ro - 1) * np.nan_to_num(rvol, nan=1.0)
        return direction, entry, exit_px, score


class IntradayMomentum(MinuteStrategy):
    name = "intraday_momentum"
    description = "First half-hour return predicts the last half-hour (enter late, exit at close)."
    params_space = (
        Param("threshold", (0.0, 0.0025, 0.005)),
        Param("entry_time", ("15:00", "15:30")),
        Param("allow_short", (False, True)),
    )

    @property
    def warmup(self) -> int:
        return 2

    def plan(self, d: IntradayData):
        pc = prev_day(d.last_close)
        r1 = d.c[:, 5, :] / pc - 1                      # previous close -> 10:00
        direction = np.where(np.abs(r1) > float(self.params["threshold"]), np.sign(r1), 0)
        direction = self._side(np.nan_to_num(direction))
        e = slot_of(self.params["entry_time"])
        entry = d.o[:, e, :]
        exit_px = d.last_close
        direction = np.where(np.isfinite(entry) & np.isfinite(exit_px), direction, 0)
        return direction, entry, exit_px, np.abs(np.nan_to_num(r1))


class IntradayNoise(MinuteStrategy):
    name = "intraday_noise"
    description = "Trade breakouts beyond the usual intraday noise band; trail with band/VWAP."
    params_space = (
        Param("lookback", (10, 14, 21)),
        Param("band_mult", (1.0, 1.5)),
        Param("check_every", (3, 6)),            # every 15 or 30 minutes
        Param("trail", ("band", "vwap")),
        Param("allow_short", (False, True)),
    )

    def plan(self, d: IntradayData):
        n = int(self.params["lookback"])
        open0 = d.o[:, 0, :]
        move = np.abs(d.c / open0[:, None, :] - 1)
        sigma = trailing_mean_days(move, n) * float(self.params["band_mult"])
        pc = prev_day(d.last_close)
        hi_ref = np.fmax(open0, pc)[:, None, :]
        lo_ref = np.fmin(open0, pc)[:, None, :]
        upper, lower = hi_ref * (1 + sigma), lo_ref * (1 - sigma)
        typ = (d.h + d.l + d.c) / 3
        vol = np.nan_to_num(d.v)
        vwap = np.cumsum(np.nan_to_num(typ) * vol, axis=1) / np.where(np.cumsum(vol, axis=1) > 0,
                                                                      np.cumsum(vol, axis=1), np.nan)
        ce = int(self.params["check_every"])
        checks = np.zeros((1, SLOTS, 1), dtype=bool)
        checks[:, ce - 1:SLOTS - 1:ce, :] = True        # bar closes at :00/:15/:30/:45, not the last bar
        long_c = checks & (d.c > upper)
        short_c = checks & (d.c < lower) if self.params["allow_short"] else np.zeros_like(long_c)
        s_entry = first_true(long_c | short_c)
        direction = np.where(s_entry >= 0, np.where(take(long_c.astype(float), s_entry) > 0, 1, -1), 0)
        entry = take(d.o, np.where(s_entry >= 0, s_entry + 1, -1))
        if self.params["trail"] == "vwap":
            long_stop, short_stop = np.fmax(upper, vwap), np.fmin(lower, vwap)
        else:
            long_stop, short_stop = upper, lower
        dl, ds = direction[:, None, :] > 0, direction[:, None, :] < 0
        later = np.arange(SLOTS)[None, :, None] > s_entry[:, None, :]
        exit_c = checks & later & ((dl & (d.c < long_stop)) | (ds & (d.c > short_stop)))
        s_exit = first_true(exit_c)
        exit_open = take(d.o, np.where(s_exit >= 0, s_exit + 1, -1))
        exit_px = np.where(np.isfinite(exit_open), exit_open, d.last_close)
        direction = np.where(np.isfinite(entry) & np.isfinite(exit_px), direction, 0)
        brk = take(d.c / np.where(direction[:, None, :] >= 0, upper, lower) - 1, s_entry)
        return direction, entry, exit_px, np.abs(np.nan_to_num(brk))


MINUTE_STRATEGIES = {cls.name: cls for cls in (IntradayORB, IntradayMomentum, IntradayNoise)}
