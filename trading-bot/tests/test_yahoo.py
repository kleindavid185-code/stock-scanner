"""Yahoo provider + `--source yahoo` CLI path, with yfinance mocked (no network)."""
import sys
import types

import numpy as np
import pandas as pd

from tradebot.cli import main
from tradebot.data.yahoo import YahooProvider, normalize_yahoo


def fake_download(symbol, start, end, **kw):
    idx = pd.bdate_range("2015-01-01", "2024-12-31")
    rng = np.random.default_rng(abs(hash(symbol)) % 2**32)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(idx))))
    cols = pd.MultiIndex.from_product([["Close", "High", "Low", "Open", "Volume"], [symbol]],
                                      names=["Price", "Ticker"])
    data = np.column_stack([close, close * 1.01, close * 0.99, close, np.full(len(idx), 5e7)])
    return pd.DataFrame(data, index=pd.DatetimeIndex(idx, name="Date"), columns=cols)


def install_fake_yf(monkeypatch, fn=fake_download):
    mod = types.ModuleType("yfinance")
    mod.download = fn
    monkeypatch.setitem(sys.modules, "yfinance", mod)


def test_normalize_multiindex():
    df = normalize_yahoo(fake_download("SPY", None, None))
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def flaky(symbol, start, end, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Too Many Requests")
        return fake_download(symbol, start, end)

    install_fake_yf(monkeypatch, flaky)
    monkeypatch.setattr("tradebot.data.yahoo.time.sleep", lambda s: None)
    df = YahooProvider().fetch("SPY", pd.Timestamp("2015-01-01").date(), pd.Timestamp("2024-12-31").date())
    assert calls["n"] == 2 and len(df) > 2000


def test_cli_backtest_with_yahoo_source(monkeypatch, tmp_path, capsys):
    install_fake_yf(monkeypatch)
    monkeypatch.setattr("tradebot.data.yahoo.time.sleep", lambda s: None)
    monkeypatch.chdir(tmp_path)
    main(["backtest", "trend_sma", "--source", "yahoo", "--symbols", "SPY", "QQQ", "--start", "2015-01-01"])
    out = capsys.readouterr().out
    assert "sharpe" in out and "buy & hold SPY" in out and "$10,000 ->" in out
    assert (tmp_path / "data" / "cache" / "yahoo" / "SPY.csv").exists()
