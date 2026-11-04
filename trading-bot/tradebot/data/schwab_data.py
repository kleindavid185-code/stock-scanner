"""Daily price history from the Schwab Market Data API (via schwab-py)."""
from __future__ import annotations

import time
from datetime import date, datetime

import pandas as pd


class SchwabDataProvider:
    def __init__(self, client, pause_sec: float = 0.5):
        self.client = client
        self.pause_sec = pause_sec  # Schwab allows ~120 market-data calls/min

    def fetch(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        resp = self.client.get_price_history_every_day(
            symbol,
            start_datetime=datetime.combine(start, datetime.min.time()),
            end_datetime=datetime.combine(end, datetime.max.time().replace(microsecond=0)),
        )
        time.sleep(self.pause_sec)
        resp.raise_for_status()
        candles = resp.json().get("candles", [])
        if not candles:
            raise ValueError(f"no candles for {symbol}")
        df = pd.DataFrame(candles)
        # Schwab timestamps are ms epoch at midnight US/Central-ish; convert to ET date.
        df.index = (pd.to_datetime(df["datetime"], unit="ms", utc=True)
                    .dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize())
        return df[["open", "high", "low", "close", "volume"]]
