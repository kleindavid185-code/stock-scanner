import pandas as pd
import pytest

from tradebot.config import load_config
from tradebot.data.base import align_panel, load_bars
from tradebot.data.synthetic import SyntheticProvider

SYMS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "SPY"]


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.delenv("TRADEBOT_LIVE_CONFIRM", raising=False)
    monkeypatch.delenv("TRADEBOT_WEBHOOK_URL", raising=False)
    return load_config(tmp_path / "none.toml", overrides={
        "bot": {"state_dir": str(tmp_path / "state")},
        "universe": {"symbols": SYMS},
        "risk": {"min_dollar_volume": 1e6},
    })


@pytest.fixture(scope="session")
def bars():
    from tradebot.config import load_config as lc

    c = lc("none.toml", overrides={"universe": {"symbols": SYMS}})
    return load_bars(c, start="2012-01-01", end="2024-12-31", provider=SyntheticProvider(seed=3))


def flat_bars(n=30, price=100.0, symbols=("X",)):
    idx = pd.bdate_range("2024-01-01", periods=n)
    frames = {s: pd.DataFrame({"open": price, "high": price, "low": price, "close": price,
                               "volume": 1e7}, index=idx) for s in symbols}
    return align_panel(frames)
