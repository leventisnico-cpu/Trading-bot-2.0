"""Reporting contract (§11).

A partial rebalance is never describable in the same words as a complete
one: the at-target / NOT-at-target statement is the report's first line.
"""
from __future__ import annotations

from datetime import date

from .execution import RebalanceOutcome
from .orders import is_success
from .portfolio import converged, deviations
from .state import EngineState

AT_TARGET_HEADER = "PORTFOLIO AT TARGET"
NOT_AT_TARGET_HEADER = "PARTIAL REBALANCE — PORTFOLIO NOT AT TARGET"


def build_report(
    *,
    today: date,
    state: EngineState,
    equity: float,
    positions: dict[str, float],
    target_weights: dict[str, float],
    prices: dict[str, float],
    outcome: RebalanceOutcome | None,
    tolerance: float,
    notes: list[str] | None = None,
) -> str:
    at_target = converged(positions, target_weights, prices, equity, tolerance)
    devs = deviations(positions, target_weights, prices, equity) if equity > 0 else {}
    worst = max(devs.items(), key=lambda kv: kv[1]) if devs else ("-", 0.0)
    peak = max(state.peak_equity, equity)
    dd = 0.0 if peak <= 0 else (peak - equity) / peak

    lines = []
    lines.append(AT_TARGET_HEADER if at_target else NOT_AT_TARGET_HEADER)
    lines.append(f"date: {today.isoformat()}")
    if state.halted:
        lines.append(f"*** SYSTEM HALTED: {state.halt_reason} — manual reset required ***")
    lines.append(f"equity: {equity:,.2f}")
    lines.append(f"drawdown from peak: {dd:.2%} (peak {peak:,.2f})")
    lines.append(f"largest deviation from target: {worst[0]} at {worst[1]:.2%}")
    lines.append("")
    lines.append("positions:")
    if positions:
        for sym in sorted(positions):
            sh = positions[sym]
            px = prices.get(sym, float("nan"))
            w = sh * px / equity if equity > 0 and px == px else 0.0
            lines.append(f"  {sym}: {sh:g} shares @ {px:,.2f} = {w:.2%}")
    else:
        lines.append("  (none)")
    lines.append("target allocation:")
    for sym in sorted(target_weights):
        lines.append(f"  {sym}: {target_weights[sym]:.2%}")
    lines.append("")
    if outcome is not None:
        lines.append("orders this cycle:")
        if not outcome.results and not outcome.dropped:
            lines.append("  (none)")
        for r in outcome.results:
            tag = "ok" if is_success(r.status) else "FAILED"
            lines.append(
                f"  [{tag}] {r.order.side.value} {r.order.shares:g} {r.order.symbol} "
                f"-> {r.status.value} filled {r.filled_shares:g} @ {r.fill_price:,.2f}")
        for d in outcome.dropped:
            lines.append(
                f"  [DROPPED] {d.order.side.value} {d.order.shares:g} {d.order.symbol} — {d.reason}")
        if outcome.escalations:
            lines.append(f"  escalations used: {outcome.escalations} (single-hop policy)")
    for note in notes or []:
        lines.append(f"note: {note}")
    return "\n".join(lines)
