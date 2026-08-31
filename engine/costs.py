"""Per-order cost model (§6).

Costs are computed per order from the actual dollar notional, price, and
share count — never as flat basis points on turnover. A fixed per-order
minimum is scale-dependent; that fact must survive into the numbers, which
is why initial equity is a real input everywhere upstream.

Spread and slippage are modeled separately from commission. The half-spread
is charged per side (crossing the spread costs half of it on entry and half
on exit).
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import CostConfig


@dataclass(frozen=True)
class OrderCost:
    commission: float
    spread_cost: float
    slippage_cost: float

    @property
    def total(self) -> float:
        return self.commission + self.spread_cost + self.slippage_cost


class CostModel:
    def __init__(self, cfg: CostConfig):
        self.cfg = cfg

    def order_cost(self, *, shares: float, price: float) -> OrderCost:
        if shares < 0 or price < 0:
            raise ValueError("shares and price must be non-negative")
        notional = shares * price
        if self.cfg.fee_model == "fixed_per_order":
            commission = max(self.cfg.fixed_min_fee, self.cfg.per_share_fee * shares) if shares > 0 else 0.0
        else:  # proportional — only configured when venue verified proportional (§3.5)
            commission = self.cfg.proportional_rate * notional
        spread_cost = (self.cfg.spread_bps / 2.0) / 1e4 * notional
        slippage_cost = self.cfg.slippage_bps / 1e4 * notional
        return OrderCost(commission=commission, spread_cost=spread_cost, slippage_cost=slippage_cost)

    def all_in_fraction(self, *, shares: float, price: float) -> float:
        """All-in cost as a fraction of the order's own notional (§7 backstop)."""
        notional = shares * price
        if notional <= 0:
            return float("inf")
        return self.order_cost(shares=shares, price=price).total / notional
