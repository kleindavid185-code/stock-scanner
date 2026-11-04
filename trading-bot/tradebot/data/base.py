"""Daily OHLCV data: providers, on-disk cache, and panel alignment.

Every provider returns, per symbol, a DataFrame indexed by tz-naive trading date
with float columns: open, high, low, close, volume.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Protocol

import pandas as pd

log = logging.getLogger(__name__)
FIELDS = ["open", "high", "low", "close", "volume"]


class DataProvider(Protocol):
    def fetch(self, symbol: str, start: date, end: date) -> pd.DataFrame: ...


@dataclass
class Bars:
    """Aligned panel: one DataFrame per field, index = dates, columns = symbols."""

    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    close: pd.DataFrame
    volume: pd.DataFrame

    @property
    def index(self) -> pd.DatetimeIndex:
        return self.close.index

    @property
    def symbols(self) -> list[str]:
        return list(self.close.columns)

    def slice(self, start=None, end=None) -> "Bars":
        return Bars(*(getattr(self, f).loc[start:end] for f in FIELDS))

    def select(self, symbols: list[str]) -> "Bars":
        return Bars(*(getattr(self, f)[symbols] for f in FIELDS))


def clean_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=str.lower)
    missing = [c for c in FIELDS if c not in df.columns]
    if missing:
        raise ValueError(f"bars missing columns {missing}")
    df = df[FIELDS].astype(float)
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df[(df["close"] > 0) & df["close"].notna()]


def align_panel(frames: dict[str, pd.DataFrame]) -> Bars:
    if not frames:
        raise ValueError("no data")
    idx = sorted(set().union(*(f.index for f in frames.values())))
    idx = pd.DatetimeIndex(idx)
    parts = {}
    for fld in FIELDS:
        parts[fld] = pd.DataFrame({s: f[fld].reindex(idx) for s, f in frames.items()}, index=idx)
    return Bars(**parts)


class CachedProvider:
    """Wraps a provider with a per-symbol CSV cache; only fetches missing recent days."""

    def __init__(self, inner: DataProvider, cache_dir: Path):
        self.inner = inner
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, symbol: str) -> Path:
        return self.cache_dir / f"{symbol.replace('/', '_')}.csv"

    def fetch(self, symbol: str, start: date, end: date, refresh: bool = False) -> pd.DataFrame:
        p = self._path(symbol)
        cached = None
        if p.exists() and not refresh:
            cached = pd.read_csv(p, index_col=0, parse_dates=True)
            if len(cached):
                have_from, have_to = cached.index[0].date(), cached.index[-1].date()
                if have_from <= start + timedelta(days=7) and have_to >= end - timedelta(days=1):
                    return cached.loc[str(start):str(end)]
                # Fetch overlapping tail so corporate-action adjustments refresh.
                fetch_start = have_to - timedelta(days=10) if have_from <= start + timedelta(days=7) else start
                new = clean_frame(self.inner.fetch(symbol, fetch_start, end))
                merged = pd.concat([cached[cached.index < pd.Timestamp(fetch_start)], new])
                merged = merged[~merged.index.duplicated(keep="last")].sort_index()
                merged.to_csv(p)
                return merged.loc[str(start):str(end)]
        df = clean_frame(self.inner.fetch(symbol, start, end))
        df.to_csv(p)
        return df


def make_provider(cfg) -> DataProvider:
    d = cfg.section("data")
    src = d["source"]
    if src == "schwab":
        from .schwab_data import SchwabDataProvider
        from ..broker.schwab_broker import make_schwab_client

        inner: DataProvider = SchwabDataProvider(make_schwab_client(cfg))
    elif src == "yahoo":
        from .yahoo import YahooProvider

        inner = YahooProvider()
    elif src == "csv":
        from .csv_provider import CsvProvider

        return CsvProvider(cfg.path(d["csv_dir"]))
    elif src == "synthetic":
        from .synthetic import SyntheticProvider

        return SyntheticProvider()
    else:
        raise ValueError(f"unknown data source {src!r}")
    # Separate cache per source so adjusted (Yahoo) and unadjusted data never mix.
    return CachedProvider(inner, cfg.path(d["cache_dir"]) / src)


def load_bars(cfg, symbols: list[str] | None = None, start: str | None = None,
              end: str | None = None, provider: DataProvider | None = None,
              refresh: bool = False) -> Bars:
    symbols = symbols or cfg.symbols
    provider = provider or make_provider(cfg)
    s = pd.Timestamp(start or cfg.section("data")["history_start"]).date()
    e = pd.Timestamp(end).date() if end else datetime.now().date()
    frames = {}
    for sym in symbols:
        try:
            if isinstance(provider, CachedProvider):
                df = provider.fetch(sym, s, e, refresh=refresh)
            else:
                df = clean_frame(provider.fetch(sym, s, e))
        except Exception as exc:  # one bad symbol shouldn't kill a run
            log.warning("data fetch failed for %s: %s", sym, exc)
            continue
        if len(df) < 50:
            log.warning("skipping %s: only %d bars", sym, len(df))
            continue
        frames[sym] = df
    return align_panel(frames)
