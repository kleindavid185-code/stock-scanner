"""Free research data from Yahoo Finance via yfinance (dividend + split adjusted).

Good for backtesting and discovery. Yahoo is an unofficial source, so for live
trading prefer Schwab data. Install with: pip install yfinance
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta

import pandas as pd

log = logging.getLogger(__name__)


class YahooProvider:
    def __init__(self, pause_sec: float = 0.3, retries: int = 4):
        self.pause_sec = pause_sec
        self.retries = retries

    def fetch(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise RuntimeError("Yahoo data needs yfinance: run `pip install yfinance`") from exc
        last_exc: Exception | None = None
        for attempt in range(self.retries):
            try:
                df = yf.download(symbol, start=str(start), end=str(end + timedelta(days=1)),
                                 auto_adjust=True, progress=False, threads=False)
                time.sleep(self.pause_sec)
                if df is not None and len(df):
                    return normalize_yahoo(df)
                last_exc = ValueError(f"Yahoo returned no data for {symbol}")
            except Exception as exc:  # rate limits / transient network errors
                last_exc = exc
            wait = 2 ** (attempt + 1)
            log.info("Yahoo fetch for %s failed (%s); retrying in %ss", symbol, last_exc, wait)
            time.sleep(wait)
        raise RuntimeError(f"Yahoo fetch failed for {symbol}: {last_exc}")


def normalize_yahoo(df: pd.DataFrame) -> pd.DataFrame:
    """yfinance may return (Price, Ticker) MultiIndex columns and capitalised names."""
    if isinstance(df.columns, pd.MultiIndex):
        lvl = 0 if {"Close", "close"} & set(df.columns.get_level_values(0)) else 1
        df = df.copy()
        df.columns = df.columns.get_level_values(lvl)
    df = df.rename(columns=str.lower)
    if "close" not in df.columns and "adj close" in df.columns:
        df = df.rename(columns={"adj close": "close"})
    return df[["open", "high", "low", "close", "volume"]].dropna(subset=["close"])
