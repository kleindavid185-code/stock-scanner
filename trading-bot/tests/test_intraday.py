import io
import json
import random
import urllib.error

import numpy as np
import pandas as pd
import pytest

from tradebot.backtest.engine import CostModel
from tradebot.backtest.intraday import run_intraday_backtest
from tradebot.cli import main
from tradebot.data.intraday import (SLOTS, AlpacaMinuteProvider, IntradayData, frames_to_intraday,
                                    synthetic_intraday)
from tradebot.research.discovery import discover
from tradebot.store import Store
from tradebot.strategies import MINUTE_STRATEGIES, build


def scripted(day_paths: list[list[float]], opens: list[float] | None = None) -> IntradayData:
    """One symbol; each day is a list of 78 closes; open of bar i = close of bar i-1,
    and the day's first open is `opens[d]` (defaults to the first close)."""
    n = len(day_paths)
    c = np.array(day_paths, dtype=float)[:, :, None]
    o = np.concatenate([c[:, :1, :], c[:, :-1, :]], axis=1)
    if opens is not None:
        o[:, 0, 0] = opens
    h, l = np.maximum(o, c), np.minimum(o, c)  # noqa: E741
    v = np.full_like(c, 1e5)
    return IntradayData(pd.bdate_range("2024-01-01", periods=n), ["X"], o, h, l, c, v)


def flat_days(n, px=100.0):
    return [[px] * SLOTS for _ in range(n)]


def test_orb_stop_and_close_exits():
    # First 5-min bar opens 100, closes 101 (bullish, range low 100). Entry = next open = 101.
    up_then_stop = [101.0] + [101.5] * 10 + [99.0] * 67      # later breaks the 100 range low
    up_and_hold = [101.0] + [102.0] * 77
    d = scripted(flat_days(20) + [up_then_stop, up_and_hold], opens=[100.0] * 22)
    s = build("intraday_orb", {"range_bars": 1, "target_r": 0.0, "rvol_min": 0.0, "allow_short": False,
                               "max_positions": 1})
    direction, entry, exit_px, _ = s.plan(d)
    assert direction[20, 0] == 1 and entry[20, 0] == 101.0
    assert exit_px[20, 0] == pytest.approx(100.0)        # stopped at the range low
    assert direction[21, 0] == 1 and exit_px[21, 0] == pytest.approx(102.0)   # held to the close


def test_momentum_enters_late_in_direction_of_morning():
    morning_up = [100.0 + 0.2 * i for i in range(6)] + [101.0] * 66 + [103.0] * 6
    d = scripted(flat_days(3) + [morning_up])
    s = build("intraday_momentum", {"threshold": 0.0, "entry_time": "15:30", "allow_short": True, "max_positions": 1})
    direction, entry, exit_px, _ = s.plan(d)
    assert direction[3, 0] == 1
    assert entry[3, 0] == pytest.approx(101.0) and exit_px[3, 0] == pytest.approx(103.0)


@pytest.mark.parametrize("name", sorted(MINUTE_STRATEGIES))
def test_no_peeking_after_entry(name):
    data = synthetic_intraday(["A", "B"], "2020-01-01", "2020-12-31", seed=2, momentum=0.002)
    rng = random.Random(4)
    for _ in range(4):
        s = build(name, MINUTE_STRATEGIES[name].sample_params(rng))
        direction, entry, _, _ = s.plan(data)
        cand = np.argwhere(direction != 0)
        if not len(cand):
            continue
        for t, j in cand[:: max(1, len(cand) // 6)][:6]:
            e = int(np.flatnonzero(data.o[t, :, j] == entry[t, j])[0])
            mod = IntradayData(data.days, data.symbols, *(a.copy() for a in (data.o, data.h, data.l, data.c, data.v)))
            for arr in (mod.h, mod.l, mod.c, mod.v):
                arr[t, e:, j] *= 1.3
            mod.o[t, e + 1:, j] *= 1.3
            for arr in (mod.o, mod.h, mod.l, mod.c, mod.v):   # and every later day
                arr[t + 1:, :, j] *= 0.7
            d2, e2, _, _ = s.plan(mod)
            assert d2[t, j] == direction[t, j] and np.isclose(e2[t, j], entry[t, j]), f"{s} peeks on day {t}"


def _research(cfg, momentum):
    return synthetic_intraday(["A", "B", "C", "SPY"], "2016-01-01", "2025-06-30", seed=9, momentum=momentum)


def test_discovery_finds_planted_intraday_momentum(cfg):
    st = Store(cfg.db_path)
    s = discover(cfg, _research(cfg, 0.003), st, n_trials=60, seed=1, families=list(MINUTE_STRATEGIES))
    fams = {c["family"] for c in s["candidates"]}
    assert "intraday_momentum" in fams
    assert s["promoted"] == []                                   # research-only


def test_discovery_rejects_random_intraday_market(cfg):
    st = Store(cfg.db_path)
    s = discover(cfg, _research(cfg, 0.0), st, n_trials=60, seed=1, families=list(MINUTE_STRATEGIES))
    assert s["candidates"] == []


def test_costs_charged_per_trade():
    data = synthetic_intraday(["A"], "2020-01-01", "2020-12-31", seed=3)
    s = build("intraday_momentum", {"threshold": 0.0, "entry_time": "15:00", "allow_short": True, "max_positions": 1})
    cheap = run_intraday_backtest(data, s, CostModel(slippage_bps=0)).metrics["total_return"]
    dear = run_intraday_backtest(data, s, CostModel(slippage_bps=10)).metrics["total_return"]
    assert dear < cheap - 0.3   # ~250 trades x 20 bps


# ---- Alpaca data plumbing (no network) ---------------------------------------
def test_frames_to_intraday_drops_extended_hours():
    idx = pd.DatetimeIndex(["2024-01-02T13:00:00Z", "2024-01-02T14:30:00Z", "2024-01-02T20:55:00Z",
                            "2024-01-02T21:00:00Z"])
    df = pd.DataFrame({"o": [1, 2, 3, 4], "h": [1, 2, 3, 4], "l": [1, 2, 3, 4], "c": [1, 2, 3, 4],
                       "v": [1, 1, 1, 1]}, index=idx, dtype=float)
    d = frames_to_intraday({"X": df})
    assert len(d.days) == 1
    assert d.o[0, 0, 0] == 2 and d.o[0, 77, 0] == 3          # 9:30 and 15:55 ET; pre/post dropped
    assert np.isnan(d.o[0, 1:77, 0]).all()


class FakeHTTP:
    def __init__(self, sip_forbidden=False):
        self.urls = []
        self.sip_forbidden = sip_forbidden

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.urls.append(url)
        if self.sip_forbidden and "feed=sip" in url:
            raise urllib.error.HTTPError(url, 403, "forbidden", {}, io.BytesIO(b"{}"))
        page2 = "page_token=" in url
        bars = [{"t": f"2024-01-0{3 if page2 else 2}T14:30:00Z", "o": 1, "h": 1, "l": 1, "c": 1, "v": 10}]
        body = {"bars": bars, "next_page_token": None if page2 else "tok"}
        return io.BytesIO(json.dumps(body).encode())


def test_alpaca_paging_cache_and_iex_fallback(tmp_path, monkeypatch):
    fake = FakeHTTP(sip_forbidden=True)
    monkeypatch.setattr("tradebot.data.intraday.urllib.request.urlopen", fake)
    monkeypatch.setattr("tradebot.data.intraday.time.sleep", lambda s: None)
    p = AlpacaMinuteProvider(tmp_path, key="k", secret="s")
    df = p.fetch("SPY", 2024, 2024)
    assert len(df) == 2 and p.feed == "iex"
    assert any("feed=iex" in u for u in fake.urls) and any("page_token=tok" in u for u in fake.urls)
    assert (tmp_path / "alpaca_5min" / "SPY_2024.csv.gz").exists()
    n = len(fake.urls)
    p.fetch("SPY", 2024, 2024)
    assert len(fake.urls) == n                                  # served from cache


def test_missing_alpaca_keys_message(tmp_path, monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="ALPACA_API_KEY"):
        AlpacaMinuteProvider(tmp_path)


def test_cli_intraday_backtest_synthetic(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    main(["backtest", "intraday_momentum", "--synthetic", "--symbols", "SPY", "--slippage-bps", "1",
          "--start", "2018-01-01", "--end", "2020-12-31"])
    out = capsys.readouterr().out
    assert "INTRADAY 5-min" in out and "slippage 1 bps" in out and "buy & hold SPY" in out
