"""Optional research data source using yfinance (dividend+split adjusted)."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd


class YahooProvider:
    def fetch(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise RuntimeError("pip install yfinance to use data.source = 'yahoo'") from exc
        df = yf.download(symbol, start=str(start), end=str(end + timedelta(days=1)),
                         auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
