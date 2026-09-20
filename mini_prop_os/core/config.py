"""Typed configuration for Mini-Prop OS, loaded from ``config.yaml``.

Every tunable of the system lives here as a frozen dataclass with explicit
validation, so a typo in the YAML fails loudly at startup instead of
producing silent bad behavior at trade time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

import yaml


class ConfigError(ValueError):
    """Raised when config.yaml is missing, malformed, or fails validation."""


@dataclass(frozen=True)
class ConnectionConfig:
    """IBKR TWS / IB Gateway socket settings.

    Default port 7497 is the TWS **paper trading** port (4002 for paper
    IB Gateway). Live ports (7496 / 4001) must be set explicitly.
    """

    host: str = "127.0.0.1"
    port: int = 7497
    client_id: int = 17
    account: str = ""
    connect_timeout_s: float = 15.0
    heartbeat_interval_s: float = 10.0
    heartbeat_timeout_s: float = 5.0
    heartbeat_max_misses: int = 3
    reconnect_backoff_base_s: float = 2.0
    reconnect_backoff_max_s: float = 120.0
    reconnect_max_attempts: int = 0  # 0 = retry forever

    def __post_init__(self) -> None:
        if not (0 < self.port < 65536):
            raise ConfigError(f"connection.port out of range: {self.port}")
        if self.client_id < 0:
            raise ConfigError("connection.client_id must be >= 0")
        for name in ("connect_timeout_s", "heartbeat_interval_s",
                     "heartbeat_timeout_s", "reconnect_backoff_base_s",
                     "reconnect_backoff_max_s"):
            if getattr(self, name) <= 0:
                raise ConfigError(f"connection.{name} must be > 0")
        if self.heartbeat_max_misses < 1:
            raise ConfigError("connection.heartbeat_max_misses must be >= 1")
        if self.reconnect_backoff_max_s < self.reconnect_backoff_base_s:
            raise ConfigError(
                "connection.reconnect_backoff_max_s must be >= backoff_base")


@dataclass(frozen=True)
class ContractConfig:
    """The instrument the sample strategy trades.

    For futures (``sec_type: FUT``):

    * ``last_trade_date`` selects a specific expiry ("202612" or "20261218");
      leave it empty to auto-resolve the current front month via a
      continuous-future lookup at connect time.
    * ``multiplier`` is the contract multiplier used for all notional risk
      math (e.g. 5 for MES, 50 for ES, 2 for MNQ, 20 for NQ). It MUST match
      the venue's real multiplier or every notional cap is wrong.
    """

    symbol: str = "MES"
    sec_type: str = "FUT"
    exchange: str = "CME"
    currency: str = "USD"
    multiplier: float = 5.0
    last_trade_date: str = ""

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ConfigError("contract.symbol must be non-empty")
        if self.sec_type not in ("STK", "FUT"):
            raise ConfigError(
                f"contract.sec_type must be STK or FUT, got {self.sec_type!r}")
        if self.multiplier <= 0:
            raise ConfigError("contract.multiplier must be > 0")
        if self.last_trade_date and not (
                self.last_trade_date.isdigit()
                and len(self.last_trade_date) in (6, 8)):
            raise ConfigError(
                "contract.last_trade_date must be YYYYMM or YYYYMMDD")


@dataclass(frozen=True)
class StrategyConfig:
    """Parameters of the shipped strategies.

    ``name`` selects the strategy: ``adaptive_ema`` (volatility-adaptive:
    regime sizing, EXTREME risk-off, confirmed entries, bounded online
    threshold learning) or ``ema_crossover`` (the plain baseline). The
    ``vol_*`` / ``confirm_window`` / ``learn`` fields apply only to
    ``adaptive_ema``; for it, ``order_quantity`` is the base size in
    LOW/NORMAL volatility (halved in HIGH, zero in EXTREME).
    """

    name: str = "adaptive_ema"
    bar_size: str = "1 min"
    fast_period: int = 9
    slow_period: int = 21
    order_quantity: int = 2
    warmup_bars: int = 0  # 0 = derived by the strategy
    #: Restrict bars to regular trading hours. Keep False for futures
    #: (they trade nearly 24h); True is the sane choice for stocks.
    use_rth: bool = False
    vol_fast_period: int = 10
    vol_slow_period: int = 100
    high_vol_ratio: float = 1.6
    extreme_vol_ratio: float = 2.5
    confirm_window: int = 10
    learn: bool = True
    #: Dollars a 1-sigma adverse move may cost per entry. > 0 enables
    #: Black-Scholes volatility-target sizing (σS√T), which can only size
    #: *down* from order_quantity, never up. 0 disables it.
    risk_per_trade: float = 0.0

    def __post_init__(self) -> None:
        if self.name not in ("adaptive_ema", "ema_crossover"):
            raise ConfigError(f"unknown strategy.name {self.name!r}")
        if self.fast_period < 1 or self.slow_period < 2:
            raise ConfigError("strategy periods must be positive")
        if self.fast_period >= self.slow_period:
            raise ConfigError(
                "strategy.fast_period must be < strategy.slow_period")
        if self.order_quantity < 1:
            raise ConfigError("strategy.order_quantity must be >= 1")
        if self.warmup_bars < 0:
            raise ConfigError("strategy.warmup_bars must be >= 0")
        if self.vol_fast_period < 2 or self.vol_slow_period <= self.vol_fast_period:
            raise ConfigError(
                "need strategy.vol_fast_period >= 2 and vol_slow > vol_fast")
        if not (1.0 < self.high_vol_ratio < self.extreme_vol_ratio):
            raise ConfigError(
                "need 1 < strategy.high_vol_ratio < extreme_vol_ratio")
        if self.confirm_window < 1:
            raise ConfigError("strategy.confirm_window must be >= 1")
        if self.risk_per_trade < 0 or not math.isfinite(self.risk_per_trade):
            raise ConfigError("strategy.risk_per_trade must be >= 0")


@dataclass(frozen=True)
class RiskConfig:
    """Hard limits enforced by the pre-trade risk layer. See guardrails.py.

    Quantities are in units of the traded instrument (shares for stocks,
    contracts for futures); notional caps are |units| * price * multiplier.
    """

    max_position_shares: int = 4
    max_position_notional: float = 150_000.0
    max_order_quantity: int = 2
    max_gross_notional: float = 300_000.0
    max_daily_loss: float = 1_000.0
    max_daily_loss_pct: float = 0.02
    allow_short: bool = False
    kill_switch_flattens: bool = True
    #: JSON file of scheduled economic events; "" disables blackouts.
    event_calendar_path: str = ""
    #: Minutes either side of a HIGH-impact release during which NEW
    #: entries are suppressed. Exits and risk-flattening are never blocked.
    #: MEDIUM-impact events use a third of these; LOW impact none.
    blackout_minutes_before: float = 15.0
    blackout_minutes_after: float = 15.0

    def __post_init__(self) -> None:
        for name in ("max_position_shares", "max_order_quantity"):
            if getattr(self, name) < 1:
                raise ConfigError(f"risk.{name} must be >= 1")
        for name in ("max_position_notional", "max_gross_notional",
                     "max_daily_loss"):
            if getattr(self, name) <= 0:
                raise ConfigError(f"risk.{name} must be > 0")
        if not (0 < self.max_daily_loss_pct < 1):
            raise ConfigError("risk.max_daily_loss_pct must be in (0, 1)")
        for name in ("blackout_minutes_before", "blackout_minutes_after"):
            v = getattr(self, name)
            if v < 0 or not math.isfinite(v):
                raise ConfigError(f"risk.{name} must be >= 0")


@dataclass(frozen=True)
class ExecutionConfig:
    """OMS behavior and execution logging."""

    execution_log_path: str = "state/executions.jsonl"
    order_timeout_s: float = 60.0
    cancel_on_shutdown: bool = True
    flatten_on_shutdown: bool = False

    def __post_init__(self) -> None:
        if self.order_timeout_s <= 0:
            raise ConfigError("execution.order_timeout_s must be > 0")


@dataclass(frozen=True)
class LoggingConfig:
    """Application logging."""

    level: str = "INFO"
    file: str = "state/mini_prop_os.log"

    def __post_init__(self) -> None:
        if self.level.upper() not in (
                "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            raise ConfigError(f"logging.level invalid: {self.level!r}")


@dataclass(frozen=True)
class AppConfig:
    """Root configuration object."""

    connection: ConnectionConfig = field(default_factory=ConnectionConfig)
    contract: ContractConfig = field(default_factory=ContractConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


_SECTIONS: Mapping[str, type] = {
    "connection": ConnectionConfig,
    "contract": ContractConfig,
    "strategy": StrategyConfig,
    "risk": RiskConfig,
    "execution": ExecutionConfig,
    "logging": LoggingConfig,
}


def _build_section(name: str, cls: type, raw: Any) -> Any:
    if raw is None:
        return cls()
    if not isinstance(raw, dict):
        raise ConfigError(f"config section {name!r} must be a mapping")
    valid = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
    unknown = set(raw) - valid
    if unknown:
        raise ConfigError(
            f"unknown key(s) in config section {name!r}: {sorted(unknown)}")
    try:
        return cls(**raw)
    except TypeError as exc:
        raise ConfigError(f"bad config section {name!r}: {exc}") from exc


def load_config(path: str | Path) -> AppConfig:
    """Load and validate ``config.yaml``.

    Raises:
        ConfigError: if the file is missing, not valid YAML, contains unknown
            keys, or any value fails a section's validation.
    """
    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"config file not found: {p}")
    try:
        raw = yaml.safe_load(p.read_text())
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {p}: {exc}") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError(f"top level of {p} must be a mapping")
    unknown = set(raw) - set(_SECTIONS)
    if unknown:
        raise ConfigError(f"unknown top-level config key(s): {sorted(unknown)}")
    kwargs = {
        name: _build_section(name, cls, raw.get(name))
        for name, cls in _SECTIONS.items()
    }
    return AppConfig(**kwargs)  # type: ignore[arg-type]


def default_config_path() -> Optional[Path]:
    """Locate config.yaml: $MINI_PROP_OS_CONFIG, CWD, then the package dir."""
    import os

    env = os.environ.get("MINI_PROP_OS_CONFIG")
    candidates = [Path(env)] if env else []
    candidates += [Path("config.yaml"),
                   Path(__file__).resolve().parents[1] / "config.yaml"]
    for c in candidates:
        if c.is_file():
            return c
    return None
