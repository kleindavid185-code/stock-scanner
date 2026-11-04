"""Vectorised indicators on (date x symbol) DataFrames. All use only past data."""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(x: pd.DataFrame, n: int) -> pd.DataFrame:
    return x.rolling(n, min_periods=n).mean()


def ema(x: pd.DataFrame, n: int) -> pd.DataFrame:
    return x.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(close: pd.DataFrame, n: int) -> pd.DataFrame:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = up / dn.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(dn != 0, 100.0).where(up.notna())


def realized_vol(close: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """Annualised close-to-close volatility."""
    return np.log(close).diff().rolling(n, min_periods=n).std() * np.sqrt(252)


def zscore(close: pd.DataFrame, n: int) -> pd.DataFrame:
    m = close.rolling(n, min_periods=n).mean()
    s = close.rolling(n, min_periods=n).std()
    return (close - m) / s.replace(0, np.nan)


def rolling_max(x: pd.DataFrame, n: int) -> pd.DataFrame:
    return x.rolling(n, min_periods=n).max()


def rolling_min(x: pd.DataFrame, n: int) -> pd.DataFrame:
    return x.rolling(n, min_periods=n).min()


def total_return(close: pd.DataFrame, lookback: int, skip: int = 0) -> pd.DataFrame:
    """Return from t-lookback to t-skip (skip>0 implements e.g. 12-1 momentum)."""
    return close.shift(skip) / close.shift(lookback) - 1


def atr(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    pc = close.shift(1)
    tr = pd.concat([(high - low), (high - pc).abs(), (low - pc).abs()]).groupby(level=0).max()
    tr = tr.reindex(close.index)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
