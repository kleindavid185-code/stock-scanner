"""Load and validate settings.toml.

The settings are loaded into frozen (read-only) dataclasses. Once loaded,
nothing in the bot can modify them -- that is part of how the risk limits
stay "hard": the strategy code literally has no way to change them.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

from .paths import SETTINGS_FILE

VALID_MODES = ("dryrun", "manual", "auto")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class SettingsError(ValueError):
    """Raised when settings.toml is missing a value or has an unsafe one."""


@dataclass(frozen=True)
class AppSettings:
    mode: str
    auto_trading_enabled: bool
    timezone: str


@dataclass(frozen=True)
class DashboardSettings:
    host: str
    port: int


@dataclass(frozen=True)
class ScannerSettings:
    min_price: float
    max_price: float
    max_float_shares: int
    min_relative_volume: float
    min_day_volume: int
    require_short_interest_flag: bool
    min_short_interest_pct_float: float
    min_pct_change: float
    scan_interval_seconds: int


@dataclass(frozen=True)
class EntrySettings:
    bar_minutes: int
    breakout_lookback_bars: int
    volume_confirm_multiple: float
    require_above_vwap: bool
    max_spread_pct: float
    entry_limit_offset_pct: float
    no_entries_before: str
    no_entries_after: str


@dataclass(frozen=True)
class ExitSettings:
    profit_target_pct: float
    stop_loss_pct: float
    trailing_stop_pct: float
    trailing_activation_pct: float
    exit_limit_offset_pct: float
    flatten_at: str


@dataclass(frozen=True)
class RiskSettings:
    max_position_dollars: float
    max_account_pct_per_trade: float
    max_daily_loss_dollars: float
    max_trades_per_day: int
    max_open_positions: int


@dataclass(frozen=True)
class BacktestSettings:
    start_date: str
    end_date: str
    starting_cash: float
    slippage_pct: float
    commission_per_order: float


@dataclass(frozen=True)
class Settings:
    app: AppSettings
    dashboard: DashboardSettings
    scanner: ScannerSettings
    entry: EntrySettings
    exit: ExitSettings
    risk: RiskSettings
    backtest: BacktestSettings

    @property
    def auto_trading_active(self) -> bool:
        """True only when BOTH switches are on."""
        return self.app.mode == "auto" and self.app.auto_trading_enabled


_SECTIONS = {
    "app": AppSettings,
    "dashboard": DashboardSettings,
    "scanner": ScannerSettings,
    "entry": EntrySettings,
    "exit": ExitSettings,
    "risk": RiskSettings,
    "backtest": BacktestSettings,
}


def _build_section(name: str, cls, raw: dict, errors: list[str]):
    data = raw.get(name)
    if not isinstance(data, dict):
        errors.append(f"[{name}] section is missing")
        return None
    kwargs = {}
    for f in fields(cls):
        if f.name not in data:
            errors.append(f"[{name}] {f.name} is missing")
            continue
        value = data[f.name]
        expected = f.type
        # TOML gives ints for "5" and floats for "5.0"; accept ints for floats.
        if expected == "float" and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        type_ok = {
            "float": isinstance(value, float),
            "int": isinstance(value, int) and not isinstance(value, bool),
            "bool": isinstance(value, bool),
            "str": isinstance(value, str),
        }[expected]
        if not type_ok:
            errors.append(f"[{name}] {f.name} must be a {expected}, got {value!r}")
            continue
        kwargs[f.name] = value
    unknown = set(data) - {f.name for f in fields(cls)}
    for key in sorted(unknown):
        errors.append(f"[{name}] {key} is not a known setting (typo?)")
    if len(kwargs) != len(fields(cls)):
        return None
    return cls(**kwargs)


def _validate(s: Settings, errors: list[str]) -> None:
    def positive(section: str, obj, *names: str) -> None:
        for n in names:
            if getattr(obj, n) <= 0:
                errors.append(f"[{section}] {n} must be greater than 0")

    def pct(section: str, obj, *names: str) -> None:
        for n in names:
            v = getattr(obj, n)
            if not 0 < v <= 100:
                errors.append(f"[{section}] {n} must be between 0 and 100 (it is a percent)")

    def hhmm(section: str, obj, *names: str) -> None:
        for n in names:
            if not _TIME_RE.match(getattr(obj, n)):
                errors.append(f'[{section}] {n} must look like "HH:MM" (24-hour)')

    if s.app.mode not in VALID_MODES:
        errors.append(f"[app] mode must be one of {VALID_MODES}, got {s.app.mode!r}")

    if not 1024 <= s.dashboard.port <= 65535:
        errors.append("[dashboard] port must be between 1024 and 65535")
    if s.dashboard.port in (4000, 5173):
        errors.append("[dashboard] port collides with your existing scanner (4000/5173)")

    sc = s.scanner
    positive("scanner", sc, "min_price", "max_price", "max_float_shares",
             "min_relative_volume", "min_day_volume", "scan_interval_seconds")
    if sc.min_price >= sc.max_price:
        errors.append("[scanner] min_price must be below max_price")
    if not 0 <= sc.min_short_interest_pct_float <= 100:
        errors.append("[scanner] min_short_interest_pct_float must be 0-100")

    en = s.entry
    positive("entry", en, "bar_minutes", "breakout_lookback_bars", "volume_confirm_multiple")
    pct("entry", en, "max_spread_pct", "entry_limit_offset_pct")
    hhmm("entry", en, "no_entries_before", "no_entries_after")

    ex = s.exit
    pct("exit", ex, "profit_target_pct", "stop_loss_pct", "trailing_stop_pct",
        "trailing_activation_pct", "exit_limit_offset_pct")
    hhmm("exit", ex, "flatten_at")
    if _TIME_RE.match(ex.flatten_at) and ex.flatten_at >= "16:00":
        errors.append("[exit] flatten_at must be before 16:00 so you are flat by the close")
    if _TIME_RE.match(ex.flatten_at) and _TIME_RE.match(en.no_entries_after):
        if en.no_entries_after >= ex.flatten_at:
            errors.append("[entry] no_entries_after must be earlier than [exit] flatten_at")

    rk = s.risk
    positive("risk", rk, "max_position_dollars", "max_daily_loss_dollars",
             "max_trades_per_day", "max_open_positions")
    pct("risk", rk, "max_account_pct_per_trade")

    bt = s.backtest
    positive("backtest", bt, "starting_cash")
    if bt.slippage_pct < 0 or bt.commission_per_order < 0:
        errors.append("[backtest] slippage_pct and commission_per_order cannot be negative")


def load_settings(path: Path | str = SETTINGS_FILE) -> Settings:
    path = Path(path)
    if not path.exists():
        raise SettingsError(f"Settings file not found: {path}")
    with path.open("rb") as fh:
        try:
            raw = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            raise SettingsError(f"{path.name} is not valid TOML: {exc}") from exc

    errors: list[str] = []
    built = {name: _build_section(name, cls, raw, errors) for name, cls in _SECTIONS.items()}
    for key in sorted(set(raw) - set(_SECTIONS)):
        errors.append(f"[{key}] is not a known section (typo?)")
    if errors:
        raise SettingsError("settings.toml has problems:\n  - " + "\n  - ".join(errors))

    settings = Settings(**built)
    _validate(settings, errors)
    if errors:
        raise SettingsError("settings.toml has problems:\n  - " + "\n  - ".join(errors))
    return settings
