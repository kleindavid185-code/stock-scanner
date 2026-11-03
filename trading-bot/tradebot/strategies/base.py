"""Strategy interface.

A strategy maps aligned daily bars to a DataFrame of *target portfolio weights*
(date x symbol, fraction of equity). Row t may only use information available at
the close of day t; the engine executes it at the open of day t+1. Weights are
long-only in [0, 1] and each row sums to <= 1.
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from typing import Any, ClassVar

import numpy as np
import pandas as pd

from ..data.base import Bars
from .. import indicators as ind


@dataclass(frozen=True)
class Param:
    """A tunable parameter: discrete choices keep the search space (and overfitting) small."""

    name: str
    choices: tuple

    def sample(self, rng: random.Random):
        return rng.choice(self.choices)


class Strategy:
    name: ClassVar[str] = "base"
    description: ClassVar[str] = ""
    params_space: ClassVar[tuple[Param, ...]] = ()
    # Common sizing params appended to every strategy's space.
    common_space: ClassVar[tuple[Param, ...]] = (
        Param("max_positions", (3, 5, 8, 10)),
        Param("sizing", ("equal", "inverse_vol")),
        # Portfolio volatility target (0 = off). Scales gross exposure down when the
        # strategy's own recent volatility is high (Moreira & Muir 2017).
        Param("vol_target", (0.0, 0.12, 0.18)),
    )

    def __init__(self, **params: Any):
        defaults = {p.name: p.choices[len(p.choices) // 2] for p in self.space()}
        unknown = set(params) - set(defaults)
        if unknown:
            raise ValueError(f"{self.name}: unknown params {sorted(unknown)}")
        self.params = {**defaults, **params}

    @classmethod
    def space(cls) -> tuple[Param, ...]:
        return cls.params_space + cls.common_space

    @classmethod
    def sample_params(cls, rng: random.Random) -> dict[str, Any]:
        return {p.name: p.sample(rng) for p in cls.space()}

    @classmethod
    def space_size(cls) -> int:
        return int(np.prod([len(p.choices) for p in cls.space()]))

    @property
    def warmup(self) -> int:
        """Bars needed before signals are valid."""
        return 252

    def key(self, symbols: list[str]) -> str:
        blob = json.dumps({"s": self.name, "p": self.params, "u": sorted(symbols)}, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def __repr__(self) -> str:
        return f"{self.name}({', '.join(f'{k}={v}' for k, v in self.params.items())})"

    # ---- to implement -------------------------------------------------
    def signals(self, bars: Bars) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Return (active, score): boolean 'want to hold' and a ranking score (higher = better)."""
        raise NotImplementedError

    # ---- shared machinery ---------------------------------------------
    def target_weights(self, bars: Bars) -> pd.DataFrame:
        active, score = self.signals(bars)
        active = active.fillna(False).astype(bool) & bars.close.notna()
        w = positions_to_weights(active, score, bars.close, int(self.params["max_positions"]),
                                 self.params["sizing"])
        vt = float(self.params.get("vol_target") or 0.0)
        if vt > 0:
            w = vol_target_overlay(w, bars.close, vt)
        w.iloc[: self.warmup] = 0.0
        return w


def positions_to_weights(active: pd.DataFrame, score: pd.DataFrame, close: pd.DataFrame,
                         max_positions: int, sizing: str) -> pd.DataFrame:
    """Pick up to max_positions active names by score and size them.

    Each slot is worth 1/max_positions of equity (so unused slots stay in cash);
    inverse_vol scales slots by (median vol / own vol), capped at 1.5x a slot.
    """
    sc = score.where(active)
    rank = sc.rank(axis=1, ascending=False, method="first")
    chosen = (rank <= max_positions) & active
    slot = 1.0 / max_positions
    if sizing == "inverse_vol":
        vol = ind.realized_vol(close, 20)
        inv = (1.0 / vol.replace(0, np.nan)).where(chosen)
        rel = inv.div(inv.median(axis=1), axis=0).clip(upper=1.5)
        w = (rel * slot).where(chosen, 0.0).fillna(0.0)
    else:
        w = chosen.astype(float) * slot
    gross = w.sum(axis=1)
    scale = np.where(gross > 1.0, 1.0 / gross.replace(0, np.nan), 1.0)
    return w.mul(pd.Series(scale, index=w.index).fillna(1.0), axis=0)


def vol_target_overlay(w: pd.DataFrame, close: pd.DataFrame, target: float, window: int = 20) -> pd.DataFrame:
    """Scale weights by min(1, target / realised vol of the strategy's own returns).
    Uses returns up to t only (weights held from t-1), so no look-ahead."""
    asset_r = close.pct_change().fillna(0.0)
    strat_r = (w.shift(1).fillna(0.0) * asset_r).sum(axis=1)
    vol = strat_r.rolling(window, min_periods=window).std() * np.sqrt(252)
    scale = (target / vol.replace(0, np.nan)).clip(upper=1.0).fillna(1.0)
    # Quantise to 10% steps so tiny vol changes don't cause daily churn.
    scale = (scale * 10).round() / 10
    return w.mul(scale, axis=0)


def hold_until_exit(entry: pd.DataFrame, exit_: pd.DataFrame) -> pd.DataFrame:
    """Stateful position: 1 from an entry day until an exit day (exit wins ties)."""
    state = pd.DataFrame(np.nan, index=entry.index, columns=entry.columns)
    state = state.mask(entry.fillna(False).astype(bool), 1.0)
    state = state.mask(exit_.fillna(False).astype(bool), 0.0)
    return state.ffill().fillna(0.0).astype(bool)


def rebalance_every(active: pd.DataFrame, score: pd.DataFrame, every: int):
    """Only change holdings every `every` bars (e.g. monthly ~ 21)."""
    if every <= 1:
        return active, score
    mask = np.arange(len(active)) % every == 0
    a = active.astype(float).where(pd.Series(mask, index=active.index), np.nan).ffill().fillna(0).astype(bool)
    s = score.where(pd.Series(mask, index=score.index)).ffill()
    return a, s
