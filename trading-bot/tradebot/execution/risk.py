"""Hard risk limits. These sit between strategies and the broker and cannot be
overridden by a strategy. Anything the risk manager is unsure about -> no trade."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..data.base import Bars

log = logging.getLogger(__name__)


@dataclass
class RiskDecision:
    targets: dict[str, float]
    allow_buys: bool = True
    halt: bool = False          # no orders at all
    flatten: bool = False       # sell everything the bot owns
    notes: list[str] = field(default_factory=list)


class RiskManager:
    def __init__(self, cfg, store):
        self.r = cfg.section("risk")
        self.cfg = cfg
        self.store = store
        self.kill_file: Path = cfg.state_dir / "KILL"

    # ---- kill switch ----------------------------------------------------
    def killed(self, mode: str) -> str | None:
        if self.kill_file.exists():
            return f"kill file present: {self.kill_file}"
        k = self.store.get(f"kill:{mode}")
        return k or None

    def trip_kill(self, mode: str, reason: str) -> None:
        log.error("KILL SWITCH TRIPPED (%s): %s", mode, reason)
        self.store.set(f"kill:{mode}", reason)

    def reset_kill(self, mode: str) -> None:
        self.store.set(f"kill:{mode}", None)
        self.store.set(f"peak:{mode}", None)
        if self.kill_file.exists():
            self.kill_file.unlink()

    # ---- main check -----------------------------------------------------
    def evaluate(self, mode: str, targets: dict[str, float], equity: float, bars: Bars) -> RiskDecision:
        dec = RiskDecision(targets=dict(targets))
        killed = self.killed(mode)
        if killed:
            dec.halt, dec.targets = True, {}
            dec.notes.append(f"halted: {killed}")
            return dec

        # Drawdown kill switch on the bot's own book.
        peak = max(float(self.store.get(f"peak:{mode}") or 0.0), equity)
        self.store.set(f"peak:{mode}", peak)
        dd = 1 - equity / peak if peak > 0 else 0.0
        if dd > self.r["max_drawdown_kill_pct"]:
            reason = f"drawdown {dd:.1%} > {self.r['max_drawdown_kill_pct']:.0%} limit"
            self.trip_kill(mode, reason)
            dec.flatten, dec.targets = True, {}
            dec.notes.append(f"flattening: {reason}")
            return dec

        # Daily loss limit: compare with last recorded equity.
        hist = self.store.equity_history(mode)
        if hist:
            prev = hist[-1]["equity"]
            if prev > 0 and equity / prev - 1 < -self.r["daily_loss_limit_pct"]:
                dec.allow_buys = False
                dec.notes.append(f"daily loss {equity / prev - 1:.1%} breached limit; buys disabled today")

        # Per-symbol filters.
        block = {s.upper() for s in self.r.get("blocklist", [])}
        close = bars.close.ffill()
        dollar_vol = (bars.close * bars.volume).rolling(20, min_periods=10).mean()
        for sym in list(dec.targets):
            w = dec.targets[sym]
            why = None
            if sym in block:
                why = "blocklisted"
            elif self.r["long_only"] and w < 0:
                why = "short not allowed"
            elif sym not in close.columns or np.isnan(close[sym].iloc[-1]):
                why = "no price data"
            elif close[sym].iloc[-1] < self.r["min_price"]:
                why = f"price < ${self.r['min_price']}"
            elif dollar_vol[sym].iloc[-1] < self.r["min_dollar_volume"]:
                why = f"illiquid (20d $vol {dollar_vol[sym].iloc[-1]:,.0f})"
            if why:
                dec.notes.append(f"{sym}: dropped ({why})")
                dec.targets[sym] = 0.0
            elif w > self.r["max_position_pct"]:
                dec.notes.append(f"{sym}: capped {w:.1%} -> {self.r['max_position_pct']:.0%}")
                dec.targets[sym] = self.r["max_position_pct"]
        gross = sum(abs(w) for w in dec.targets.values())
        if gross > self.r["max_gross_exposure"]:
            k = self.r["max_gross_exposure"] / gross
            dec.targets = {s: w * k for s, w in dec.targets.items()}
            dec.notes.append(f"gross {gross:.2f} scaled to {self.r['max_gross_exposure']}")
        return dec
