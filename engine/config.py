"""Configuration: loaded from TOML, validated at startup (§7).

Every risk limit and threshold lives here — tests read these values from the
config file rather than hardcoding them (§8), so retuning a limit cannot
silently disable the test guarding it.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ConfigError

VALID_FEE_MODELS = ("fixed_per_order", "proportional")


@dataclass(frozen=True)
class CostConfig:
    fee_model: str
    fixed_min_fee: float
    per_share_fee: float
    proportional_rate: float
    spread_bps: float
    slippage_bps: float


@dataclass(frozen=True)
class RiskConfig:
    max_drawdown_pct: float        # hard kill: drawdown from peak
    min_equity_floor: float        # hard kill: absolute floor
    max_daily_loss_pct: float      # soft halt: stand down for the day
    max_position_weight: float     # clamp
    max_gross_exposure: float      # clamp (1.0 = no leverage)
    allow_short: bool
    allow_leverage: bool
    max_orders_per_day: int        # backstop
    min_order_notional: float      # backstop (full exits exempt, §5.4)
    max_cost_fraction: float       # refuse order if all-in cost exceeds this fraction of notional
    no_trade_band: float           # skip trades below this weight change (full exits exempt)
    rebalance_tolerance: float     # max abs weight deviation to call the portfolio "at target"
    max_rebalance_retries: int


@dataclass(frozen=True)
class ExecutionConfig:
    live_min_equity: float         # automated live execution unlock threshold
    escalation_max_hops: int       # limit->market escalation budget (§5.10)
    order_wait_seconds: float


@dataclass(frozen=True)
class DataConfig:
    max_staleness_days: int


@dataclass(frozen=True)
class EngineConfig:
    base_currency: str
    universe: tuple[str, ...]
    costs: CostConfig
    risk: RiskConfig
    execution: ExecutionConfig
    data: DataConfig
    strategy: dict = field(default_factory=dict)  # opaque to the engine


def _require(table: dict, key: str, section: str):
    if key not in table:
        raise ConfigError(f"missing required config key [{section}].{key}")
    return table[key]


def _check(cond: bool, msg: str) -> None:
    if not cond:
        raise ConfigError(msg)


def load_config(path: str | Path) -> EngineConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    meta = raw.get("meta", {})
    uni = _require(raw, "universe", "root")
    costs_t = _require(raw, "costs", "root")
    risk_t = _require(raw, "risk", "root")
    exec_t = _require(raw, "execution", "root")
    data_t = _require(raw, "data", "root")

    costs = CostConfig(
        fee_model=_require(costs_t, "fee_model", "costs"),
        fixed_min_fee=float(_require(costs_t, "fixed_min_fee", "costs")),
        per_share_fee=float(_require(costs_t, "per_share_fee", "costs")),
        proportional_rate=float(_require(costs_t, "proportional_rate", "costs")),
        spread_bps=float(_require(costs_t, "spread_bps", "costs")),
        slippage_bps=float(_require(costs_t, "slippage_bps", "costs")),
    )
    risk = RiskConfig(
        max_drawdown_pct=float(_require(risk_t, "max_drawdown_pct", "risk")),
        min_equity_floor=float(_require(risk_t, "min_equity_floor", "risk")),
        max_daily_loss_pct=float(_require(risk_t, "max_daily_loss_pct", "risk")),
        max_position_weight=float(_require(risk_t, "max_position_weight", "risk")),
        max_gross_exposure=float(_require(risk_t, "max_gross_exposure", "risk")),
        allow_short=bool(_require(risk_t, "allow_short", "risk")),
        allow_leverage=bool(_require(risk_t, "allow_leverage", "risk")),
        max_orders_per_day=int(_require(risk_t, "max_orders_per_day", "risk")),
        min_order_notional=float(_require(risk_t, "min_order_notional", "risk")),
        max_cost_fraction=float(_require(risk_t, "max_cost_fraction", "risk")),
        no_trade_band=float(_require(risk_t, "no_trade_band", "risk")),
        rebalance_tolerance=float(_require(risk_t, "rebalance_tolerance", "risk")),
        max_rebalance_retries=int(_require(risk_t, "max_rebalance_retries", "risk")),
    )
    execution = ExecutionConfig(
        live_min_equity=float(_require(exec_t, "live_min_equity", "execution")),
        escalation_max_hops=int(_require(exec_t, "escalation_max_hops", "execution")),
        order_wait_seconds=float(exec_t.get("order_wait_seconds", 60.0)),
    )
    data = DataConfig(
        max_staleness_days=int(_require(data_t, "max_staleness_days", "data")),
    )

    cfg = EngineConfig(
        base_currency=str(meta.get("base_currency", "CAD")),
        universe=tuple(_require(uni, "symbols", "universe")),
        costs=costs,
        risk=risk,
        execution=execution,
        data=data,
        strategy=raw.get("strategy", {}),
    )
    validate_config(cfg)
    return cfg


def validate_config(cfg: EngineConfig) -> None:
    c, r, e, d = cfg.costs, cfg.risk, cfg.execution, cfg.data
    _check(len(cfg.universe) > 0, "universe.symbols must be non-empty")
    _check(len(set(cfg.universe)) == len(cfg.universe), "universe.symbols has duplicates")
    _check(c.fee_model in VALID_FEE_MODELS, f"costs.fee_model must be one of {VALID_FEE_MODELS}")
    _check(c.fixed_min_fee >= 0 and c.per_share_fee >= 0, "fees must be >= 0")
    _check(0 <= c.proportional_rate < 0.05, "costs.proportional_rate out of range [0, 5%)")
    if c.fee_model == "proportional":
        _check(c.proportional_rate > 0,
               "proportional fee model requires proportional_rate > 0 — only use this "
               "model if the venue's published schedule is verified proportional (§3.5)")
    _check(0 <= c.spread_bps < 500 and 0 <= c.slippage_bps < 500, "spread/slippage bps out of range")
    _check(0 < r.max_drawdown_pct < 1, "risk.max_drawdown_pct must be in (0,1)")
    _check(r.min_equity_floor >= 0, "risk.min_equity_floor must be >= 0")
    _check(0 < r.max_daily_loss_pct < 1, "risk.max_daily_loss_pct must be in (0,1)")
    _check(0 < r.max_position_weight <= 1, "risk.max_position_weight must be in (0,1]")
    # Positivity holds regardless of the leverage flag — allow_leverage=true
    # once disabled ALL gross validation and a negative cap flipped the
    # clamp into emitting shorts (audit round 2, finding #11).
    _check(0 < r.max_gross_exposure <= 10, "risk.max_gross_exposure must be in (0,10]")
    _check(r.max_gross_exposure <= 1 or r.allow_leverage,
           "risk.max_gross_exposure > 1 requires allow_leverage=true (which §3.4 forbids by default)")
    _check(r.max_orders_per_day >= 1, "risk.max_orders_per_day must be >= 1")
    _check(r.min_order_notional >= 0, "risk.min_order_notional must be >= 0")
    _check(0 < r.max_cost_fraction < 1, "risk.max_cost_fraction must be in (0,1)")
    _check(0 <= r.no_trade_band < 1, "risk.no_trade_band must be in [0,1)")
    _check(0 < r.rebalance_tolerance < 1, "risk.rebalance_tolerance must be in (0,1)")
    _check(r.max_rebalance_retries >= 1, "risk.max_rebalance_retries must be >= 1")
    _check(e.live_min_equity >= 0, "execution.live_min_equity must be >= 0")
    _check(e.escalation_max_hops == 1,
           "execution.escalation_max_hops must be exactly 1 (§5.10: one hop, never a chain)")
    _check(d.max_staleness_days >= 1, "data.max_staleness_days must be >= 1")
