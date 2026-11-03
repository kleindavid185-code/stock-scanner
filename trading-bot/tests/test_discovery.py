from tradebot.data.base import load_bars
from tradebot.data.synthetic import SyntheticProvider
from tradebot.research.discovery import discover
from tradebot.store import Store

SYMS = ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "SPY"]


def _bars(cfg, edge, regimes=True):
    return load_bars(cfg, SYMS, start="2008-01-01", end="2025-06-30",
                     provider=SyntheticProvider(seed=11, trend_edge=edge, regimes=regimes))


def test_random_walk_market_promotes_nothing(cfg):
    """False-positive check: on a market with no edge at all, nothing may pass."""
    st = Store(cfg.db_path)
    s = discover(cfg, _bars(cfg, 0.0, regimes=False), st, n_trials=90, seed=5)
    assert s["candidates"] == [] and s["promoted"] == []
    assert st.trial_count() == s["trials"]


def test_planted_trend_edge_is_found(cfg):
    st = Store(cfg.db_path)
    s = discover(cfg, _bars(cfg, 0.0015), st, n_trials=90, seed=5)
    fams = {c["family"] for c in s["candidates"]}
    assert fams & {"trend_sma", "ts_momentum", "donchian_breakout", "xs_momentum"}
    assert not fams & {"rsi_reversion", "bollinger_reversion"}
    assert s["promoted"]
    assert all(st.strategy(i)["status"] == "paper" for i in s["promoted"])


def test_trial_counter_accumulates_across_runs(cfg):
    st = Store(cfg.db_path)
    b = _bars(cfg, 0.0, regimes=False)
    s1 = discover(cfg, b, st, n_trials=30, seed=1)
    s2 = discover(cfg, b, st, n_trials=30, seed=2)
    assert s2["total_trials_ever"] == s1["trials"] + s2["trials"]
