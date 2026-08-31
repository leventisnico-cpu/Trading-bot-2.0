"""Order model (§5.3, §5.6).

Success is a WHITELIST: only FILLED counts. Any status the code has never
heard of is a failure — REJECTED once slipped through a blacklist and a
broken rebalance was marked done.

Ordering: sells always precede buys. Sells free buying power and reduce
risk; when an order cap bites, buys are dropped first and sells are
dropped last.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from enum import Enum


class Side(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(Enum):
    NEW = "NEW"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


# Whitelist success; never blacklist failure (§5.6).
SUCCESS_STATUSES = frozenset({OrderStatus.FILLED})
# PARTIALLY_FILLED here means "done, with a partial fill" (e.g. IOC) — a
# terminal outcome that is NOT success: the rebalance did not reach target.
TERMINAL_STATUSES = frozenset(
    {OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED, OrderStatus.CANCELLED,
     OrderStatus.REJECTED, OrderStatus.EXPIRED, OrderStatus.ERROR}
)


def is_success(status: OrderStatus) -> bool:
    return status in SUCCESS_STATUSES


def is_terminal(status: OrderStatus) -> bool:
    return status in TERMINAL_STATUSES


_order_ids = itertools.count(1)


@dataclass
class Order:
    symbol: str
    side: Side
    shares: float
    is_full_exit: bool = False       # exempt from min-size filters (§5.4)
    limit_price: float | None = None
    id: int = field(default_factory=lambda: next(_order_ids))

    def __post_init__(self):
        if self.shares <= 0:
            raise ValueError(f"order shares must be > 0, got {self.shares}")


@dataclass(frozen=True)
class DroppedOrder:
    order: Order
    reason: str


def sort_for_submission(orders: list[Order]) -> list[Order]:
    """Sells first, then buys; stable within each side."""
    return [o for o in orders if o.side is Side.SELL] + [o for o in orders if o.side is Side.BUY]


def truncate_to_cap(orders: list[Order], cap: int) -> tuple[list[Order], list[DroppedOrder]]:
    """Enforce a max-order cap. Sells are kept preferentially; buys are
    dropped first (§5.3 — the original bug did exactly the opposite)."""
    ordered = sort_for_submission(orders)
    kept = ordered[:cap]
    dropped = [DroppedOrder(o, f"max_orders_per_day cap ({cap}) — buys dropped before sells")
               for o in ordered[cap:]]
    return kept, dropped
