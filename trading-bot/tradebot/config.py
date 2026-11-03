"""Configuration loading: non-secret settings from config.toml, secrets from env/.env."""
from __future__ import annotations

import copy
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "bot": {
        "state_dir": "state",
        "timezone": "America/New_York",
        "run_time": "09:45",
        "discover_every_days": 7,
    },
    "data": {
        "source": "schwab",
        "csv_dir": "data/csv",
        "cache_dir": "data/cache",
        "history_start": "2006-01-01",
    },
    "universe": {
        "symbols": ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "GLD"],
        "benchmark": "SPY",
    },
    "backtest": {
        "commission_bps": 0.0,
        "slippage_bps": 5.0,
        "rebalance_band": 0.02,
        "initial_capital": 100000.0,
    },
    "discovery": {
        "trials_per_run": 300,
        "holdout_years": 2.0,
        "wf_train_years": 4.0,
        "wf_test_years": 1.0,
        "min_trades": 30,
        "min_dsr": 0.95,
        "min_wf_sharpe": 0.5,
        "min_holdout_sharpe": 0.3,
        "max_drawdown": 0.30,
        "max_paper_strategies": 5,
    },
    "promotion": {
        "min_paper_days": 40,
        "demote_dd_multiple": 1.5,
        "min_demote_dd": 0.10,
    },
    "risk": {
        "bot_capital": 10000.0,
        "max_position_pct": 0.20,
        "max_gross_exposure": 1.0,
        "long_only": True,
        "min_price": 5.0,
        "min_dollar_volume": 20_000_000.0,
        "daily_loss_limit_pct": 0.04,
        "max_drawdown_kill_pct": 0.20,
        "max_orders_per_run": 30,
        "blocklist": [],
    },
    "execution": {
        "live_trading_enabled": False,
        "order_type": "limit",
        "limit_collar_bps": 30.0,
        "fill_timeout_sec": 120,
        "paper_starting_cash": 10000.0,
    },
}

LIVE_CONFIRM_VALUE = "I_UNDERSTAND_THIS_TRADES_REAL_MONEY"


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass
class SchwabCredentials:
    app_key: str | None
    app_secret: str | None
    callback_url: str
    token_path: Path
    account_hash: str | None

    @property
    def configured(self) -> bool:
        return bool(self.app_key and self.app_secret)


@dataclass
class Config:
    raw: dict[str, Any]
    root: Path
    schwab: SchwabCredentials = field(init=False)

    def __post_init__(self) -> None:
        token = Path(os.environ.get("SCHWAB_TOKEN_PATH", "state/schwab_token.json"))
        self.schwab = SchwabCredentials(
            app_key=os.environ.get("SCHWAB_APP_KEY"),
            app_secret=os.environ.get("SCHWAB_APP_SECRET"),
            callback_url=os.environ.get("SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182"),
            token_path=token if token.is_absolute() else self.root / token,
            account_hash=os.environ.get("SCHWAB_ACCOUNT_HASH") or None,
        )

    def section(self, name: str) -> dict[str, Any]:
        return self.raw[name]

    def path(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else self.root / p

    @property
    def state_dir(self) -> Path:
        p = self.path(self.raw["bot"]["state_dir"])
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def db_path(self) -> Path:
        return self.state_dir / "tradebot.db"

    @property
    def symbols(self) -> list[str]:
        return [s.upper() for s in self.raw["universe"]["symbols"]]

    @property
    def benchmark(self) -> str:
        return self.raw["universe"]["benchmark"].upper()

    def live_allowed(self) -> tuple[bool, str]:
        if not self.raw["execution"]["live_trading_enabled"]:
            return False, "config [execution] live_trading_enabled is false"
        if os.environ.get("TRADEBOT_LIVE_CONFIRM") != LIVE_CONFIRM_VALUE:
            return False, f"env TRADEBOT_LIVE_CONFIRM is not set to {LIVE_CONFIRM_VALUE}"
        if not self.schwab.configured:
            return False, "SCHWAB_APP_KEY / SCHWAB_APP_SECRET not set"
        return True, "ok"


def load_config(path: str | os.PathLike | None = None, overrides: dict | None = None) -> Config:
    """Load config.toml (if present) on top of defaults, and .env into the environment."""
    cfg_path = Path(path) if path else Path(os.environ.get("TRADEBOT_CONFIG", "config.toml"))
    root = cfg_path.resolve().parent if cfg_path.exists() else Path.cwd()
    try:
        from dotenv import load_dotenv

        load_dotenv(root / ".env")
    except ImportError:  # python-dotenv is optional
        pass
    raw = copy.deepcopy(DEFAULTS)
    if cfg_path.exists():
        with open(cfg_path, "rb") as f:
            raw = _deep_merge(raw, tomllib.load(f))
    if overrides:
        raw = _deep_merge(raw, overrides)
    return Config(raw=raw, root=root)
