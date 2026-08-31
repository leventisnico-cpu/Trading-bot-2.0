"""Daily cycle orchestration.

Ordering is the point (§5.1): prior state is READ and passed to every risk
check BEFORE anything overwrites it. The kill switch that could never fire
recorded today's equity first and then compared today to today.

The cycle also refuses to trade if the engine's own test suite fails
(§8, run via preflight_selftest) — a daily job wires that in before this.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from datetime import date

import pandas as pd

from .backtest import Strategy
from .broker import Broker
from .config import EngineConfig
from .costs import CostModel
from .data import latest_prices, validate_prices
from .errors import HaltError
from .execution import RebalanceOutcome, execute_rebalance
from .journal import Journal
from .orders import Order, Side
from .portfolio import compute_orders, converged
from .report import build_report
from .risk import PreTradeDecision, RiskEngine
from .state import StateStore


@dataclass
class CycleResult:
    traded: bool
    report: str
    outcome: RebalanceOutcome | None


def preflight_selftest(repo_root: str) -> bool:
    """Run the engine's own test suite; the daily job must not place an
    order if it fails (§8)."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-x", "tests"],
        cwd=repo_root, capture_output=True, text=True, timeout=1800,
    )
    return proc.returncode == 0


def run_cycle(
    *,
    today: date,
    cfg: EngineConfig,
    store: StateStore,
    broker: Broker,
    strategy: Strategy,
    prices: pd.DataFrame,
    journal: Journal,
    decision_day: bool,
) -> CycleResult:
    # 1. READ prior state first; it is passed, not re-derived (§5.1).
    prior = store.load()

    # 2. Halted means halted. Manual reset only (§7).
    risk = RiskEngine(cfg.risk, CostModel(cfg.costs))
    risk.check_not_halted(prior)  # raises HaltError

    # 3. Fresh account snapshot from the venue, not from local state.
    account = broker.get_account()
    equity = account.equity
    positions = dict(account.positions)

    # 4. Validate data BEFORE any decision (§5.7).
    required = set(cfg.universe) | {s for s, sh in positions.items() if sh > 0}
    validate_prices(prices, required, today, cfg.data.max_staleness_days)
    px = latest_prices(prices, required)

    # 5. Pre-trade risk gate against PRIOR equity (§5.1).
    pre = risk.pre_trade(prior, equity, today)
    journal.record("pre_trade", decision=pre.decision.value, reason=pre.reason,
                   daily_return=pre.daily_return, drawdown=pre.drawdown_from_peak)

    outcome: RebalanceOutcome | None = None
    target_weights: dict[str, float] = {}
    notes: list[str] = []
    state = prior  # mutated below, saved LAST

    if pre.decision is PreTradeDecision.HARD_KILL:
        state.halted = True
        state.halt_reason = pre.reason
        liquidation = [Order(symbol=s, side=Side.SELL, shares=sh, is_full_exit=True)
                       for s, sh in positions.items() if sh > 0]
        if liquidation:
            outcome = execute_rebalance(
                broker, risk, liquidation, px,
                escalation_max_hops=cfg.execution.escalation_max_hops, journal=journal)
        notes.append("HARD KILL fired: liquidated and halted; manual reset required")
        traded = bool(liquidation)
    elif pre.decision is PreTradeDecision.STAND_DOWN:
        notes.append(f"soft halt: {pre.reason} — standing down for the day")
        traded = False
    elif decision_day:
        target_weights = risk.clamp_weights(strategy.target_weights(prices, today))
        orders = compute_orders(positions, target_weights, px, equity,
                                no_trade_band=cfg.risk.no_trade_band)
        period = today.strftime("%Y-%m")
        if state.last_completed_period == period:
            notes.append(f"period {period} already converged; not re-trading (§5.9)")
            traded = False
        elif not orders:
            traded = False
        elif state.rebalance_retries >= cfg.risk.max_rebalance_retries:
            notes.append(
                f"LOUD WARNING: rebalance retry cap ({cfg.risk.max_rebalance_retries}) "
                f"reached for {period} without convergence — manual attention needed (§5.9)")
            traded = False
        else:
            outcome = execute_rebalance(
                broker, risk, orders, px,
                escalation_max_hops=cfg.execution.escalation_max_hops, journal=journal)
            traded = True
    else:
        traded = False

    # 6. Re-read the account AFTER trading; completion = convergence (§5.9).
    account = broker.get_account()
    equity = account.equity
    positions = dict(account.positions)
    if decision_day and target_weights and not state.halted:
        if converged(positions, target_weights, px, equity, cfg.risk.rebalance_tolerance):
            state.last_completed_period = today.strftime("%Y-%m")
            state.rebalance_retries = 0
        elif traded:
            state.rebalance_retries += 1

    # 7. Only NOW overwrite state (§5.1: prior was read first, passed explicitly).
    state.peak_equity = max(state.peak_equity, equity)
    state.last_equity = equity
    state.last_equity_date = today.isoformat()
    state.positions = positions
    state.cash = account.cash
    store.save(state)

    report = build_report(
        today=today, state=state, equity=equity, positions=positions,
        target_weights=target_weights, prices=px, outcome=outcome,
        tolerance=cfg.risk.rebalance_tolerance, notes=notes)
    journal.record("cycle_done", traded=traded, equity=equity, halted=state.halted)
    return CycleResult(traded=traded, report=report, outcome=outcome)
