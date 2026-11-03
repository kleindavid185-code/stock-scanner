"""Load daily bars from a folder of SYMBOL.csv files (date,open,high,low,close,volume)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd


class CsvProvider:
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def fetch(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        p = self.directory / f"{symbol}.csv"
        df = pd.read_csv(p, index_col=0, parse_dates=True)
        return df.loc[str(start):str(end)]
