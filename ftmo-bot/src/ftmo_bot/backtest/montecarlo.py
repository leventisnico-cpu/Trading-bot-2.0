"""Session-block bootstrap Monte Carlo over the trades table (SPEC "Monte Carlo").

Block = one trading session: all trades of one CE(S)T trading day across the
four instruments, kept together so intra-session correlation (e.g. EURUSD and
GBPUSD breaking out together) survives resampling.

Every path is a fresh $100K challenge (Phase 1 then, if passed, a fresh Phase 2)
and is independently stressed:
- each trade dropped with probability 10% (missed fills),
- spread widened by U(0, 50%) of each trade's entry spread cost,
- U(0, 1) pip extra slippage on entry and exit.

Intraday drawdown per day is approximated from each trade's MAE in exit order:
the day's low is min over trades of (realised so far + that trade's MAE).
The live guard is modelled: if that low reaches the ENGINE daily limit, the day
is flattened at the limit and no further trades are taken. Breaches are judged
with the same ``ftmo_rules`` functions as live.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any

import numpy as np
import pandas as pd

from ftmo_bot.risk.ftmo_rules import (
    AccountState,
    HaltKind,
    Limits,
    should_halt,
    target_reached,
)

_NOON = datetime.combine(date(2026, 1, 7), time(11), tzinfo=UTC)  # a Wednesday


@dataclass(frozen=True)
class Block:
    pnl: np.ndarray
    mae: np.ndarray
    spread: np.ndarray
    pip: np.ndarray


@dataclass(frozen=True)
class Stress:
    drop_p: float = 0.10
    spread_widen_max: float = 0.50
    extra_slip_pips_max: float = 1.0


@dataclass(frozen=True)
class PhaseOutcome:
    passed: bool
    reason: str  # target | ftmo_daily | ftmo_overall | engine_overall | timeout
    days: int
    engine_daily_halts: int


def blocks_from_trades(trades: pd.DataFrame) -> list[Block]:
    if trades.empty:
        return []
    t = trades.sort_values(["date_cest", "exit_ts"], kind="stable")
    out = []
    for _, g in t.groupby("date_cest", sort=True):
        out.append(
            Block(
                g["pnl_usd"].to_numpy(np.float64),
                g["mae"].to_numpy(np.float64),
                g["spread_cost_usd"].to_numpy(np.float64),
                g["pip_value_usd"].to_numpy(np.float64),
            )
        )
    return out


def _state(equity: float, baseline: float, initial: float) -> AccountState:
    return AccountState(_NOON, equity, baseline, initial)


def run_phase(
    rng: np.random.Generator,
    blocks: list[Block],
    target_pct: float,
    engine: Limits,
    ftmo: Limits,
    min_trading_days: int,
    widen: float,
    slip_pips: float,
    stress: Stress,
    max_days: int = 2_000,
) -> PhaseOutcome:
    initial = ftmo.initial_balance
    equity = initial
    trading_days = 0
    engine_daily = 0
    for day in range(1, max_days + 1):
        b = blocks[int(rng.integers(len(blocks)))]
        keep = rng.random(len(b.pnl)) >= stress.drop_p
        if not keep.any():
            continue
        pnl = b.pnl[keep] - widen * b.spread[keep] - 2 * slip_pips * b.pip[keep]
        mae = b.mae[keep] - widen * b.spread[keep] - slip_pips * b.pip[keep]
        start = equity
        cum = 0.0
        low = 0.0
        for k in range(len(pnl)):
            cand = cum + min(mae[k], pnl[k])
            if should_halt(_state(start + cand, start, initial), engine) is not None:
                cum = min(cum, -engine.daily_loss_limit)  # guard flattens at the limit
                low = min(low, cum)
                engine_daily += 1
                break
            low = min(low, cand)
            cum += pnl[k]
            low = min(low, cum)
        trading_days += 1
        equity = start + cum
        worst = _state(start + low, start, initial)
        f = should_halt(worst, ftmo)
        if f is not None:
            reason = "ftmo_daily" if f.kind is HaltKind.DAILY else "ftmo_overall"
            return PhaseOutcome(False, reason, day, engine_daily)
        e = should_halt(worst, engine)
        if e is not None and e.kind is HaltKind.OVERALL:
            return PhaseOutcome(False, "engine_overall", day, engine_daily)
        if target_reached(equity, initial, target_pct) and trading_days >= min_trading_days:
            return PhaseOutcome(True, "target", day, engine_daily)
    return PhaseOutcome(False, "timeout", max_days, engine_daily)


def run(
    trades: pd.DataFrame,
    engine: Limits,
    ftmo: Limits,
    targets: tuple[float, ...],
    min_trading_days: int,
    challenge_fee: float,
    paths: int = 10_000,
    seed: int = 20261005,
    stress: Stress | None = None,
) -> dict[str, Any]:
    stress = stress or Stress()
    blocks = blocks_from_trades(trades)
    if not blocks:
        return {"paths": 0, "error": "no trades"}
    rng = np.random.default_rng(seed)
    p1 = p2 = both = 0
    daily_breach = 0
    reasons: dict[str, int] = {}
    days_to_pass: list[int] = []
    for _ in range(paths):
        widen = float(rng.uniform(0, stress.spread_widen_max))
        slip = float(rng.uniform(0, stress.extra_slip_pips_max))
        o1 = run_phase(rng, blocks, targets[0], engine, ftmo, min_trading_days, widen, slip, stress)
        reasons[f"phase1:{o1.reason}"] = reasons.get(f"phase1:{o1.reason}", 0) + 1
        breached = o1.reason == "ftmo_daily"
        if o1.passed:
            p1 += 1
            if len(targets) > 1:
                o2 = run_phase(
                    rng, blocks, targets[1], engine, ftmo, min_trading_days, widen, slip, stress
                )
                reasons[f"phase2:{o2.reason}"] = reasons.get(f"phase2:{o2.reason}", 0) + 1
                breached = breached or o2.reason == "ftmo_daily"
                if o2.passed:
                    p2 += 1
                    both += 1
                    days_to_pass.append(o1.days + o2.days)
            else:
                both += 1
                days_to_pass.append(o1.days)
        daily_breach += breached
    p_both = both / paths
    return {
        "paths": paths,
        "seed": seed,
        "blocks": len(blocks),
        "stress": {
            "drop_p": stress.drop_p,
            "spread_widen_max": stress.spread_widen_max,
            "extra_slip_pips_max": stress.extra_slip_pips_max,
        },
        "p_phase1": p1 / paths,
        "p_phase2_given_phase1": p2 / p1 if p1 else 0.0,
        "p_both": p_both,
        "p_ftmo_daily_breach": daily_breach / paths,
        "challenge_fee": challenge_fee,
        "expected_cost_to_funded": challenge_fee / p_both if p_both else None,
        "median_days_to_funded": float(np.median(days_to_pass)) if days_to_pass else None,
        "outcomes": dict(sorted(reasons.items())),
    }
