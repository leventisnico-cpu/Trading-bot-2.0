"""Broker interface and a paper broker whose fakes can FAIL (§8).

The paper broker has knobs — per-symbol fill fractions, scripted statuses,
mid-flight outages — because a fake that always fills cannot detect
ordering bugs, partial fills, or stale-data bugs.

get_account() returns a SNAPSHOT (deep copy), never a live reference: a
test that mutates broker internals through a returned object is testing
nothing.
"""
from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from .costs import CostModel
from .errors import ExecutionError
from .orders import Order, OrderStatus, Side
from .risk import ApprovedOrders


@dataclass
class AccountSnapshot:
    cash: float
    positions: dict[str, float]
    equity: float


@dataclass
class OrderResult:
    order: Order
    status: OrderStatus
    filled_shares: float = 0.0
    fill_price: float = 0.0
    commission: float = 0.0


class Broker(ABC):
    """All submission goes through ApprovedOrders — the risk layer's stamp."""

    @abstractmethod
    def get_account(self) -> AccountSnapshot: ...

    @abstractmethod
    def submit(self, approved: ApprovedOrders) -> list[OrderResult]: ...

    def _require_approval(self, approved) -> list[Order]:
        if not isinstance(approved, ApprovedOrders):
            raise TypeError(
                "broker only accepts ApprovedOrders from the risk layer (§3.6)"
            )
        return approved.orders


@dataclass
class PaperBrokerKnobs:
    """Failure injection for tests. Defaults are benign."""
    fill_fraction: dict[str, float] = field(default_factory=dict)   # symbol -> fraction filled
    scripted_status: dict[int, OrderStatus] = field(default_factory=dict)  # order id -> status
    scripted_status_by_symbol: dict[str, OrderStatus] = field(default_factory=dict)
    outage_after_n_orders: int | None = None                        # raise on the Nth submission
    reject_all: bool = False


class PaperBroker(Broker):
    def __init__(self, cash: float, prices: dict[str, float], cost_model: CostModel,
                 positions: dict[str, float] | None = None,
                 knobs: PaperBrokerKnobs | None = None):
        self._cash = float(cash)
        self._positions: dict[str, float] = dict(positions or {})
        self._prices = dict(prices)
        self._cost_model = cost_model
        self.knobs = knobs or PaperBrokerKnobs()
        self._orders_seen = 0
        self.submissions: list[Order] = []   # audit trail for tests

    def set_prices(self, prices: dict[str, float]) -> None:
        self._prices.update(prices)

    def get_account(self) -> AccountSnapshot:
        equity = self._cash + sum(
            sh * self._prices.get(sym, 0.0) for sym, sh in self._positions.items()
        )
        # Deep copy: callers must never hold a live reference (§8).
        return AccountSnapshot(
            cash=self._cash, positions=copy.deepcopy(self._positions), equity=equity
        )

    def submit(self, approved: ApprovedOrders) -> list[OrderResult]:
        orders = self._require_approval(approved)
        results = []
        for o in orders:
            self._orders_seen += 1
            if (self.knobs.outage_after_n_orders is not None
                    and self._orders_seen > self.knobs.outage_after_n_orders):
                raise ExecutionError("simulated venue outage mid-flight")
            self.submissions.append(o)
            results.append(self._execute_one(o))
        return results

    def _execute_one(self, o: Order) -> OrderResult:
        status = self.knobs.scripted_status.get(o.id)
        if status is None:
            status = self.knobs.scripted_status_by_symbol.get(o.symbol)
        if status is None and self.knobs.reject_all:
            status = OrderStatus.REJECTED
        if status is not None and status is not OrderStatus.FILLED:
            return OrderResult(order=o, status=status)

        px = self._prices.get(o.symbol)
        if px is None or px <= 0:
            return OrderResult(order=o, status=OrderStatus.REJECTED)
        frac = self.knobs.fill_fraction.get(o.symbol, 1.0)
        filled = o.shares * frac
        if filled <= 0:
            return OrderResult(order=o, status=OrderStatus.CANCELLED)
        cost = self._cost_model.order_cost(shares=filled, price=px)
        if o.side is Side.BUY:
            needed = filled * px + cost.total
            if needed > self._cash + 1e-9:
                return OrderResult(order=o, status=OrderStatus.REJECTED)
            self._cash -= needed
            self._positions[o.symbol] = self._positions.get(o.symbol, 0.0) + filled
        else:
            held = self._positions.get(o.symbol, 0.0)
            if filled > held + 1e-9:
                return OrderResult(order=o, status=OrderStatus.REJECTED)
            if cost.total > filled * px:
                # Adapter contract: never execute a sell whose costs exceed
                # its own proceeds — a 40%-filled dust exit once paid a $1
                # minimum fee out of $0.88 proceeds and drove cash negative
                # (audit round 2, finding #6). Real adapters enforce this too.
                return OrderResult(order=o, status=OrderStatus.REJECTED)
            self._cash += filled * px - cost.total
            self._positions[o.symbol] = held - filled
            if self._positions[o.symbol] <= 1e-9:   # float dust is not a position
                del self._positions[o.symbol]
        status = OrderStatus.FILLED if frac >= 1.0 else OrderStatus.PARTIALLY_FILLED
        return OrderResult(order=o, status=status, filled_shares=filled,
                           fill_price=px, commission=cost.commission)
