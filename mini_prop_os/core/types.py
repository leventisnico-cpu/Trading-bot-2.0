"""Broker-agnostic domain types shared by strategy, risk, and execution layers.

Nothing in this module imports ``ib_insync``; translation to/from IBKR API
objects happens exclusively in the application layer (``app.py``).
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class Action(str, Enum):
    """Direction of an order intent."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Supported order types."""

    MARKET = "MKT"
    LIMIT = "LMT"


class IntentSource(str, Enum):
    """Who generated an intent — used by the risk layer to allow
    risk-initiated flattening orders through while the kill switch is active.
    """

    STRATEGY = "STRATEGY"
    RISK_FLATTEN = "RISK_FLATTEN"
    OPERATOR = "OPERATOR"


_intent_counter = itertools.count(1)


def utc_now() -> datetime:
    """Timezone-aware current UTC time (single point of truth for the app)."""
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Bar:
    """One completed OHLCV bar for a single symbol."""

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        if not (self.low <= self.open <= self.high
                and self.low <= self.close <= self.high):
            raise ValueError(
                f"inconsistent bar for {self.symbol} @ {self.timestamp}: "
                f"O={self.open} H={self.high} L={self.low} C={self.close}"
            )


@dataclass(frozen=True)
class OrderIntent:
    """A clean, validated *request* to trade.

    Strategies emit these; the risk layer approves or rejects them; only the
    OMS turns an approved intent into a broker order. An intent is immutable —
    any amendment is a new intent.
    """

    action: Action
    symbol: str
    quantity: int
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[float] = None
    source: IntentSource = IntentSource.STRATEGY
    strategy_id: str = ""
    reason: str = ""
    intent_id: int = field(default_factory=lambda: next(_intent_counter))
    created_at: datetime = field(default_factory=utc_now)

    @property
    def signed_quantity(self) -> int:
        """Positive for BUY, negative for SELL."""
        return self.quantity if self.action is Action.BUY else -self.quantity


@dataclass
class Position:
    """Net position in one symbol, maintained by the OMS from fills."""

    symbol: str
    quantity: int = 0
    avg_price: float = 0.0
    realized_pnl: float = 0.0

    def apply_fill(self, signed_qty: int, price: float) -> None:
        """Update quantity/average price/realized PnL for a fill.

        Uses standard average-cost accounting; a fill that crosses through
        flat is split into the closing part and the opening part.
        """
        if signed_qty == 0:
            return
        if self.quantity == 0 or (self.quantity > 0) == (signed_qty > 0):
            # Opening or adding: new weighted-average price.
            total = self.quantity + signed_qty
            self.avg_price = (
                (self.avg_price * abs(self.quantity) + price * abs(signed_qty))
                / abs(total)
            )
            self.quantity = total
            return
        # Reducing / closing / reversing.
        closing = min(abs(signed_qty), abs(self.quantity))
        direction = 1 if self.quantity > 0 else -1
        self.realized_pnl += closing * direction * (price - self.avg_price)
        remainder = abs(signed_qty) - closing
        self.quantity += signed_qty
        if remainder > 0:
            # Reversed through flat: remainder opens at the fill price.
            self.avg_price = price
        elif self.quantity == 0:
            self.avg_price = 0.0

    def unrealized_pnl(self, last_price: float) -> float:
        """Mark-to-market PnL of the open quantity at ``last_price``."""
        return self.quantity * (last_price - self.avg_price)


@dataclass(frozen=True)
class Fill:
    """One execution (possibly partial) against a broker order."""

    order_id: int
    symbol: str
    signed_quantity: int
    price: float
    timestamp: datetime = field(default_factory=utc_now)
    exec_id: str = ""


def monotonic() -> float:
    """Monotonic clock — indirection point so tests can patch time."""
    return time.monotonic()
