"""Fixed-fractional position sizing and contract specs.

Position size = risk_amount / (stop distance in price × contract value), with
risk_amount = initial balance × risk_per_trade_pct (SPEC "Risk sizing").
Pure arithmetic; shared by backtest and live.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Protocol

Side = Literal["long", "short"]


class PricedSignal(Protocol):
    @property
    def side(self) -> Side: ...

    @property
    def entry(self) -> float: ...

    @property
    def stop(self) -> float: ...


@dataclass(frozen=True)
class ContractSpec:
    symbol: str
    contract_size: float  # units per lot; P&L/lot = contract_size × price move
    pip_size: float  # one "pip" for stress tests (forex 0.0001, gold 0.1, NAS 1)
    slippage: float  # price units, applied to market and stop fills
    commission_per_lot_side: float
    typical_spread: float  # floor on the tick spread in backtests
    min_lot: float
    lot_step: float
    max_lot: float
    quote_to_account: float = 1.0

    def value_per_price_unit(self, lots: float) -> float:
        """Account-currency P&L for a 1.0 price move on ``lots`` lots."""
        return lots * self.contract_size * self.quote_to_account

    def pip_value(self, lots: float) -> float:
        return self.value_per_price_unit(lots) * self.pip_size


def stop_distance(signal: PricedSignal) -> float:
    dist = abs(signal.entry - signal.stop)
    if dist <= 0 or not math.isfinite(dist):
        raise ValueError(f"invalid stop distance {dist}")
    return dist


def size_for(signal: PricedSignal, spec: ContractSpec, risk_amount: float) -> float:
    """Lots for ``risk_amount`` at the signal's stop, rounded DOWN to ``lot_step``.

    Returns 0.0 when the result is below ``min_lot`` (the trade is then skipped,
    never rounded up into more risk than allowed).
    """
    if risk_amount <= 0:
        raise ValueError("risk_amount must be positive")
    raw = risk_amount / (stop_distance(signal) * spec.value_per_price_unit(1.0))
    steps = math.floor(raw / spec.lot_step + 1e-9)
    lots = round(steps * spec.lot_step, 8)
    if lots < spec.min_lot:
        return 0.0
    return min(lots, spec.max_lot)


def round_trip_costs(spec: ContractSpec, lots: float, spread: float) -> float:
    """Commission both sides + one spread crossing + slippage on entry and exit."""
    effective_spread = max(spread, spec.typical_spread)
    return 2 * spec.commission_per_lot_side * lots + spec.value_per_price_unit(lots) * (
        effective_spread + 2 * spec.slippage
    )


def projected_loss(
    signal: PricedSignal, spec: ContractSpec, risk_amount: float, spread: float
) -> float:
    """Upper bound of the loss if the trade hits its stop, costs included.

    Computed at the unrounded size, which ``size_for`` can only round down from,
    so the pre-trade check can run before sizing (SPEC: can_open, then size_for).
    """
    max_lots = risk_amount / (stop_distance(signal) * spec.value_per_price_unit(1.0))
    return risk_amount + round_trip_costs(spec, max_lots, spread)


def risk_to_stop(side: Side, lots: float, mark: float, stop: float, spec: ContractSpec) -> float:
    """Additional loss from the current liquidation mark to the stop, plus exit costs."""
    move = (mark - stop) if side == "long" else (stop - mark)
    exit_costs = (
        spec.commission_per_lot_side * lots + spec.value_per_price_unit(lots) * spec.slippage
    )
    return max(move, 0.0) * spec.value_per_price_unit(lots) + exit_costs
