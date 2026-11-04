"""Performance and robustness statistics."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def sharpe(returns: pd.Series, periods: int = TRADING_DAYS) -> float:
    r = returns.dropna()
    sd = r.std()
    if len(r) < 2 or not sd or not np.isfinite(sd):
        return 0.0
    return float(r.mean() / sd * math.sqrt(periods))


def max_drawdown(equity_or_returns: pd.Series, is_returns: bool = True) -> float:
    eq = (1 + equity_or_returns).cumprod() if is_returns else equity_or_returns
    if len(eq) == 0:
        return 0.0
    dd = eq / eq.cummax() - 1
    return float(-dd.min())


def compute_metrics(returns: pd.Series, trades: pd.DataFrame | None = None,
                    turnover: pd.Series | None = None, weights: pd.DataFrame | None = None) -> dict:
    r = returns.dropna()
    n = len(r)
    if n < 2:
        return {"days": n}
    years = n / TRADING_DAYS
    total = float((1 + r).prod() - 1)
    cagr = (1 + total) ** (1 / years) - 1 if total > -1 else -1.0
    vol = float(r.std() * math.sqrt(TRADING_DAYS))
    downside = r[r < 0].std() * math.sqrt(TRADING_DAYS)
    mdd = max_drawdown(r)
    m = {
        "days": n,
        "years": round(years, 2),
        "total_return": total,
        "cagr": float(cagr),
        "vol": vol,
        "sharpe": sharpe(r),
        "sortino": float(r.mean() * TRADING_DAYS / downside) if downside and downside > 0 else 0.0,
        "max_drawdown": mdd,
        "calmar": float(cagr / mdd) if mdd > 0 else 0.0,
        "skew": float(r.skew()),
        "kurtosis": float(r.kurt() + 3),  # non-excess, as used by PSR/DSR
    }
    if trades is not None:
        m["trades"] = int(len(trades))
        if len(trades):
            wins = trades["pnl"] > 0
            gross_win = trades.loc[wins, "pnl"].sum()
            gross_loss = -trades.loc[~wins, "pnl"].sum()
            m["win_rate"] = float(wins.mean())
            m["profit_factor"] = float(gross_win / gross_loss) if gross_loss > 0 else float("inf")
            m["avg_trade_ret"] = float(trades["ret"].mean())
            m["avg_hold_days"] = float((pd.to_datetime(trades["exit"]) - pd.to_datetime(trades["entry"])).dt.days.mean())
    if turnover is not None:
        m["annual_turnover"] = float(turnover.sum() / years)
    if weights is not None:
        m["avg_exposure"] = float(weights.sum(axis=1).mean())
    return m


def format_metrics(m: dict) -> str:
    pct = {"total_return", "cagr", "vol", "max_drawdown", "win_rate", "avg_trade_ret", "avg_exposure"}
    lines = []
    for k, v in m.items():
        if isinstance(v, float):
            lines.append(f"  {k:<16} {v:>10.2%}" if k in pct else f"  {k:<16} {v:>10.3f}")
        else:
            lines.append(f"  {k:<16} {v!s:>10}")
    return "\n".join(lines)
