"""5-minute regular-session bars (09:30-16:00 ET) for intraday research.

Data comes from Alpaca's free Market Data API (the same keys the scanner app
uses: ALPACA_API_KEY / ALPACA_API_SECRET), which has 5-minute history back to
2016. Bars are cached per symbol per year under data/cache/alpaca_5min/.

IntradayData stores arrays shaped (days, 78 slots, symbols); slot 0 is the
09:30-09:35 bar, slot 77 is 15:55-16:00. Half days leave later slots NaN.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)
SLOTS = 78                      # 6.5h / 5 min
SESSION_START_MIN = 9 * 60 + 30
ALPACA_DATA_URL = "https://data.alpaca.markets/v2/stocks/{symbol}/bars"


def slot_of(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return (h * 60 + m - SESSION_START_MIN) // 5


@dataclass
class IntradayData:
    days: pd.DatetimeIndex
    symbols: list[str]
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray  # noqa: E741
    c: np.ndarray
    v: np.ndarray

    @property
    def index(self) -> pd.DatetimeIndex:
        return self.days

    @property
    def last_close(self) -> np.ndarray:
        """Each day's final valid close, shape (days, symbols)."""
        filled = pd.DataFrame(self.c.transpose(0, 2, 1).reshape(-1, SLOTS)).ffill(axis=1).to_numpy()
        return filled[:, -1].reshape(len(self.days), len(self.symbols))

    @property
    def close(self) -> pd.DataFrame:
        """Daily closes (for benchmarks and discovery's bookkeeping)."""
        return pd.DataFrame(self.last_close, index=self.days, columns=self.symbols)

    def slice(self, start=None, end=None) -> "IntradayData":
        mask = np.ones(len(self.days), dtype=bool)
        if start is not None:
            mask &= self.days >= pd.Timestamp(start)
        if end is not None:
            mask &= self.days <= pd.Timestamp(end)
        return IntradayData(self.days[mask], list(self.symbols), *(a[mask] for a in (self.o, self.h, self.l, self.c, self.v)))

    def select(self, symbols: list[str]) -> "IntradayData":
        ix = [self.symbols.index(s) for s in symbols]
        return IntradayData(self.days, list(symbols), *(a[:, :, ix] for a in (self.o, self.h, self.l, self.c, self.v)))


def frames_to_intraday(frames: dict[str, pd.DataFrame]) -> IntradayData:
    """frames: symbol -> DataFrame indexed by tz-aware or ET-naive bar START times."""
    per = {}
    for sym, df in frames.items():
        idx = pd.DatetimeIndex(df.index)
        if idx.tz is not None:
            idx = idx.tz_convert("America/New_York").tz_localize(None)
        minutes = idx.hour * 60 + idx.minute
        keep = (minutes >= SESSION_START_MIN) & (minutes < SESSION_START_MIN + SLOTS * 5)
        d = df.loc[keep].copy()
        d["day"] = idx[keep].normalize()
        d["slot"] = (minutes[keep] - SESSION_START_MIN) // 5
        per[sym] = d
    days = pd.DatetimeIndex(sorted(set().union(*(set(d["day"]) for d in per.values()))))
    arrays = {f: np.full((len(days), SLOTS, len(per)), np.nan) for f in "ohlcv"}
    day_pos = {d: i for i, d in enumerate(days)}
    for j, (sym, d) in enumerate(per.items()):
        di = d["day"].map(day_pos).to_numpy()
        si = d["slot"].to_numpy().astype(int)
        for f in "ohlcv":
            arrays[f][di, si, j] = d[f].to_numpy(float)
    return IntradayData(days, list(per), arrays["o"], arrays["h"], arrays["l"], arrays["c"], arrays["v"])


class AlpacaMinuteProvider:
    """Fetches 5-minute bars from Alpaca with paging, retries and a yearly CSV cache."""

    def __init__(self, cache_dir: Path, key: str | None = None, secret: str | None = None,
                 feed: str | None = None, pause_sec: float = 0.35):
        self.key = key or os.environ.get("ALPACA_API_KEY")
        self.secret = secret or os.environ.get("ALPACA_API_SECRET")
        if not (self.key and self.secret):
            raise RuntimeError("Intraday data needs ALPACA_API_KEY and ALPACA_API_SECRET in trading-bot/.env "
                               "(the same free keys the scanner app uses; see .env.example)")
        self.feed = feed or os.environ.get("ALPACA_DATA_FEED_HISTORY", "sip")
        self.cache_dir = Path(cache_dir) / "alpaca_5min"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.pause_sec = pause_sec

    # -- HTTP -----------------------------------------------------------------
    def _get(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"APCA-API-KEY-ID": self.key, "APCA-API-SECRET-KEY": self.secret,
                                                   "Accept": "application/json"})
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                if e.code == 429 or e.code >= 500:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise
            except urllib.error.URLError:
                time.sleep(2 ** (attempt + 1))
        raise RuntimeError(f"Alpaca request kept failing: {url}")

    def _fetch_range(self, symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
        rows, token = [], None
        while True:
            q = {"timeframe": "5Min", "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"), "limit": 10000, "adjustment": "all",
                 "feed": self.feed, "sort": "asc"}
            if token:
                q["page_token"] = token
            url = ALPACA_DATA_URL.format(symbol=urllib.parse.quote(symbol)) + "?" + urllib.parse.urlencode(q)
            try:
                data = self._get(url)
            except urllib.error.HTTPError as e:
                if e.code == 403 and self.feed == "sip":
                    log.warning("Alpaca plan doesn't allow SIP history; falling back to the IEX feed "
                                "(IEX volume is partial but prices are fine for liquid ETFs)")
                    self.feed = "iex"
                    continue
                raise
            rows += data.get("bars") or []
            token = data.get("next_page_token")
            time.sleep(self.pause_sec)
            if not token:
                break
        if not rows:
            return pd.DataFrame(columns=list("ohlcv"))
        df = pd.DataFrame(rows)
        df.index = pd.to_datetime(df["t"], utc=True)
        return df[list("ohlcv")].astype(float)

    # -- cache ----------------------------------------------------------------
    def fetch(self, symbol: str, start_year: int, end_year: int | None = None) -> pd.DataFrame:
        now = datetime.now(timezone.utc)
        end_year = end_year or now.year
        parts = []
        for year in range(start_year, end_year + 1):
            p = self.cache_dir / f"{symbol}_{year}.csv.gz"
            current = year == now.year
            stale = current and (not p.exists() or time.time() - p.stat().st_mtime > 12 * 3600)
            if p.exists() and not stale:
                df = pd.read_csv(p, index_col=0)
                df.index = pd.to_datetime(df.index, utc=True)
            else:
                s = datetime(year, 1, 1, tzinfo=timezone.utc)
                e = min(datetime(year + 1, 1, 1, tzinfo=timezone.utc), now - timedelta(minutes=20))
                log.info("downloading %s 5-min bars for %d", symbol, year)
                df = self._fetch_range(symbol, s, e)
                df.to_csv(p)
            parts.append(df)
        out = pd.concat(parts) if parts else pd.DataFrame(columns=list("ohlcv"))
        return out[~out.index.duplicated(keep="last")].sort_index()


def load_intraday(cfg, symbols: list[str], start: str | None = None, end: str | None = None,
                  provider=None) -> IntradayData:
    start_year = pd.Timestamp(start or "2016-01-01").year
    provider = provider or AlpacaMinuteProvider(cfg.path(cfg.section("data")["cache_dir"]))
    frames = {}
    for sym in symbols:
        try:
            df = provider.fetch(sym, max(start_year, 2016))
        except Exception as exc:
            log.warning("intraday fetch failed for %s: %s", sym, exc)
            continue
        if len(df) < 1000:
            log.warning("skipping %s: only %d intraday bars", sym, len(df))
            continue
        frames[sym] = df
    if not frames:
        raise RuntimeError("no intraday data loaded")
    data = frames_to_intraday(frames)
    return data.slice(start, end)


def synthetic_intraday(symbols: list[str], start: str = "2018-01-01", end: str = "2024-12-31", seed: int = 5,
                       momentum: float = 0.0) -> IntradayData:
    """Random 5-min bars for tests. momentum > 0 plants a real intraday effect: the
    last half hour drifts in the direction of the first half hour's move."""
    days = pd.bdate_range(start, end)
    rng = np.random.default_rng(seed)
    n, k = len(days), len(symbols)
    r = rng.normal(0, 0.0012, (n, SLOTS, k))
    gap = rng.normal(0, 0.004, (n, 1, k))
    if momentum:
        first = r[:, :6, :].sum(axis=1) + gap[:, 0, :]
        r[:, 72:, :] += momentum * np.sign(first)[:, None, :] / 6
    path = np.cumsum(r, axis=1) + gap
    day_start = np.cumsum(np.r_[np.zeros((1, k)), path[:-1, -1, :]], axis=0)
    logp = day_start[:, None, :] + path + np.log(100)
    c = np.exp(logp)
    o = np.concatenate([np.exp(day_start[:, None, :] + gap + np.log(100)), c[:, :-1, :]], axis=1)
    noise = np.abs(rng.normal(0, 0.0006, c.shape))
    h = np.maximum(o, c) * (1 + noise)
    l = np.minimum(o, c) * (1 - noise)  # noqa: E741
    v = rng.uniform(1e5, 1e6, c.shape)
    return IntradayData(days, list(symbols), o, h, l, c, v)
