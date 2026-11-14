"""Typed loaders for ``config/strategy.yaml`` and ``config/ftmo_*.yaml``.

Config is the only source of parameters: strategy, sizing, limits and the
backtest all read from these dataclasses, never from literals.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from ftmo_bot.risk.ftmo_rules import Limits
from ftmo_bot.risk.sizing import ContractSpec

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def _t(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


@dataclass(frozen=True)
class Window:
    start: time
    end: time

    def contains(self, t: time) -> bool:
        return self.start <= t < self.end


@dataclass(frozen=True)
class InstrumentParams:
    symbol: str
    range: Window
    session: Window
    currencies: tuple[str, ...]


@dataclass(frozen=True)
class StrategyParams:
    name: str
    timezone: str
    instruments: dict[str, InstrumentParams]
    bar_minutes: int
    trend_minutes: int
    ema_period: int
    slope_bars: int
    trend_atr_period: int
    flat_atr_mult: float
    h4_lookback: int
    stop_atr_period: int
    atr_cap_mult: float
    target_r: float
    breakeven_r: float
    time_exit_minutes: int
    news_window_minutes: int
    news_impact: str
    risk_per_trade_pct: float
    max_open_slots: int
    correlated_groups: tuple[frozenset[str], ...]
    max_consecutive_losses: int
    splits: dict[str, tuple[date, date | None]]
    params_hash: str


@dataclass(frozen=True)
class Phase:
    name: str
    profit_target_pct: float


@dataclass(frozen=True)
class FtmoProfile:
    profile: str
    account_currency: str
    initial_balance: float
    reset_timezone: str
    challenge_fee: float
    phases: tuple[Phase, ...]
    min_trading_days: int
    ftmo_daily_loss_pct: float
    ftmo_overall_loss_pct: float
    overall_mode: str
    engine_daily_loss_pct: float
    engine_overall_loss_pct: float
    friday_cutoff: time
    poll_seconds: float
    heartbeat_stale_seconds: float
    daily_summary_time: time
    server_timezone: str
    magic: int
    signal_max_age_seconds: float
    contracts: dict[str, ContractSpec]
    dukascopy: dict[str, tuple[str, float]]  # symbol -> (instrument, price divisor)
    mt5_symbols: dict[str, str]


def _load_yaml(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping at top level")
    return data, raw


def load_strategy(path: Path | None = None) -> StrategyParams:
    path = path or DEFAULT_CONFIG_DIR / "strategy.yaml"
    d, raw = _load_yaml(path)
    instruments = {
        sym: InstrumentParams(
            symbol=sym,
            range=Window(_t(v["range"]["start"]), _t(v["range"]["end"])),
            session=Window(_t(v["session"]["start"]), _t(v["session"]["end"])),
            currencies=tuple(v["currencies"]),
        )
        for sym, v in d["instruments"].items()
    }
    splits: dict[str, tuple[date, date | None]] = {}
    for name, (start, end) in d["splits"].items():
        splits[name] = (
            date.fromisoformat(str(start)),
            date.fromisoformat(str(end)) if end else None,
        )
    risk = d["risk"]
    return StrategyParams(
        name=d["name"],
        timezone=d["timezone"],
        instruments=instruments,
        bar_minutes=int(d["bar_minutes"]),
        trend_minutes=int(d["trend"]["timeframe_minutes"]),
        ema_period=int(d["trend"]["ema_period"]),
        slope_bars=int(d["trend"]["slope_bars"]),
        trend_atr_period=int(d["trend"]["atr_period"]),
        flat_atr_mult=float(d["trend"]["flat_atr_mult"]),
        h4_lookback=int(d["trend"]["lookback_bars"]),
        stop_atr_period=int(d["stop"]["atr_period"]),
        atr_cap_mult=float(d["stop"]["atr_cap_mult"]),
        target_r=float(d["target_r"]),
        breakeven_r=float(d["breakeven_r"]),
        time_exit_minutes=int(d["time_exit_minutes_before_end"]),
        news_window_minutes=int(d["news"]["window_minutes"]),
        news_impact=str(d["news"]["impact"]),
        risk_per_trade_pct=float(risk["risk_per_trade_pct"]),
        max_open_slots=int(risk["max_open_slots"]),
        correlated_groups=tuple(frozenset(g) for g in risk["correlated_groups"]),
        max_consecutive_losses=int(risk["max_consecutive_losses"]),
        splits=splits,
        params_hash=hashlib.sha256(raw).hexdigest()[:16],
    )


def load_profile(path: Path | None = None) -> FtmoProfile:
    path = path or DEFAULT_CONFIG_DIR / "ftmo_2step.yaml"
    d, _ = _load_yaml(path)
    contracts: dict[str, ContractSpec] = {}
    dukascopy: dict[str, tuple[str, float]] = {}
    mt5_symbols: dict[str, str] = {}
    for sym, c in d["contracts"].items():
        contracts[sym] = ContractSpec(
            symbol=sym,
            contract_size=float(c["contract_size"]),
            pip_size=float(c["pip_size"]),
            slippage=float(c["slippage"]),
            commission_per_lot_side=float(c["commission_per_lot_side"]),
            typical_spread=float(c["typical_spread"]),
            min_lot=float(c["min_lot"]),
            lot_step=float(c["lot_step"]),
            max_lot=float(c["max_lot"]),
            quote_to_account=float(c.get("quote_to_account", 1.0)),
        )
        dukascopy[sym] = (str(c["dukascopy"]["instrument"]), float(c["dukascopy"]["price_divisor"]))
        mt5_symbols[sym] = str(c["mt5_symbol"])
    return FtmoProfile(
        profile=d["profile"],
        account_currency=d["account_currency"],
        initial_balance=float(d["initial_balance"]),
        reset_timezone=d["reset_timezone"],
        challenge_fee=float(d["challenge_fee"]),
        phases=tuple(Phase(p["name"], float(p["profit_target_pct"])) for p in d["phases"]),
        min_trading_days=int(d["min_trading_days"]),
        ftmo_daily_loss_pct=float(d["ftmo_limits"]["daily_loss_pct"]),
        ftmo_overall_loss_pct=float(d["ftmo_limits"]["overall_loss_pct"]),
        overall_mode=str(d["ftmo_limits"]["overall_mode"]),
        engine_daily_loss_pct=float(d["engine_limits"]["daily_loss_pct"]),
        engine_overall_loss_pct=float(d["engine_limits"]["overall_loss_pct"]),
        friday_cutoff=_t(d["friday_cutoff"]),
        poll_seconds=float(d["guard"]["poll_seconds"]),
        heartbeat_stale_seconds=float(d["guard"]["heartbeat_stale_seconds"]),
        daily_summary_time=_t(d["guard"]["daily_summary_time"]),
        server_timezone=str(d["mt5"]["server_timezone"]),
        magic=int(d["mt5"]["magic"]),
        signal_max_age_seconds=float(d["mt5"]["signal_max_age_seconds"]),
        contracts=contracts,
        dukascopy=dukascopy,
        mt5_symbols=mt5_symbols,
    )


def _limits(
    profile: FtmoProfile, params: StrategyParams, daily_pct: float, overall_pct: float
) -> Limits:
    return Limits(
        initial_balance=profile.initial_balance,
        daily_loss_pct=daily_pct,
        overall_loss_pct=overall_pct,
        max_open_slots=params.max_open_slots,
        correlated_groups=params.correlated_groups,
        max_consecutive_losses=params.max_consecutive_losses,
        reset_tz=profile.reset_timezone,
        friday_cutoff=profile.friday_cutoff,
    )


def engine_limits(profile: FtmoProfile, params: StrategyParams) -> Limits:
    """The limits the bot enforces (2.5% / 6% for the 2-Step profile)."""
    return _limits(profile, params, profile.engine_daily_loss_pct, profile.engine_overall_loss_pct)


def ftmo_limits(profile: FtmoProfile, params: StrategyParams) -> Limits:
    """The limits FTMO enforces (5% / 10% for the 2-Step profile)."""
    return _limits(profile, params, profile.ftmo_daily_loss_pct, profile.ftmo_overall_loss_pct)


def risk_amount(profile: FtmoProfile, params: StrategyParams) -> float:
    """Fixed risk per trade: a fraction of the INITIAL balance (SPEC: keeps sizing stable)."""
    return profile.initial_balance * params.risk_per_trade_pct


def flatten_time_utc(day: date, inst: InstrumentParams, params: StrategyParams) -> datetime:
    """Session end minus the time-exit buffer on CE(S)T ``day``, as aware UTC."""
    end = datetime.combine(day, inst.session.end, tzinfo=ZoneInfo(params.timezone))
    return (end - timedelta(minutes=params.time_exit_minutes)).astimezone(UTC)


def session_start_utc(day: date, inst: InstrumentParams, params: StrategyParams) -> datetime:
    start = datetime.combine(day, inst.session.start, tzinfo=ZoneInfo(params.timezone))
    return start.astimezone(UTC)
