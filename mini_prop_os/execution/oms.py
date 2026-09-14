"""Order Management System: deterministic order state machine + fill ledger.

The OMS is broker-agnostic. It talks to the outside world through the
:class:`BrokerAdapter` protocol (implemented for ib_insync in ``app.py`` and
by a fake in the tests), and receives normalized status / fill callbacks:

    submit(intent)                      -> ManagedOrder (state SUBMITTED)
    on_order_status(order_id, state)    -> broker status transitions
    on_fill(Fill)                       -> partial/complete executions
    cancel(order_id) / cancel_all()     -> PENDING_CANCEL, then CANCELLED

State machine (transitions outside this table are rejected and logged,
never applied — a late or duplicate broker event cannot corrupt state)::

    CREATED ─▶ SUBMITTED ─▶ PARTIALLY_FILLED ─▶ FILLED
        │          │   │            │  ├──▶ PENDING_CANCEL ─▶ CANCELLED
        │          │   ├────────────┼──┴──────────▲   │
        │          │   └──▶ FILLED  │             │   └─▶ PARTIALLY_FILLED / FILLED
        │          └──▶ REJECTED / CANCELLED      │
        └──▶ REJECTED (risk)        └─▶ CANCELLED (remainder cancelled)

Every event is appended to a JSON-lines execution log for audit and also
emitted through standard logging (console/file per app config).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import (Callable, Dict, List, Mapping, Optional, Protocol,
                    Tuple)

from ..core.types import Fill, OrderIntent, Position, utc_now

log = logging.getLogger(__name__)


class OrderState(str, Enum):
    """Lifecycle states of a managed order."""

    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    PENDING_CANCEL = "PENDING_CANCEL"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


#: Allowed transitions: state -> set of next states.
_TRANSITIONS: Mapping[OrderState, frozenset] = {
    OrderState.CREATED: frozenset(
        {OrderState.SUBMITTED, OrderState.REJECTED}),
    OrderState.SUBMITTED: frozenset(
        {OrderState.PARTIALLY_FILLED, OrderState.FILLED,
         OrderState.PENDING_CANCEL, OrderState.CANCELLED,
         OrderState.REJECTED}),
    OrderState.PARTIALLY_FILLED: frozenset(
        {OrderState.PARTIALLY_FILLED, OrderState.FILLED,
         OrderState.PENDING_CANCEL, OrderState.CANCELLED}),
    OrderState.PENDING_CANCEL: frozenset(
        # Fills can still race a cancel request.
        {OrderState.PARTIALLY_FILLED, OrderState.FILLED,
         OrderState.CANCELLED}),
    OrderState.FILLED: frozenset(),
    OrderState.CANCELLED: frozenset(),
    OrderState.REJECTED: frozenset(),
}

TERMINAL_STATES = frozenset(
    {OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED})


class BrokerAdapter(Protocol):
    """Minimal async surface the OMS needs from a broker."""

    async def place_order(self, intent: OrderIntent) -> int:
        """Submit; returns the broker order id."""
        ...

    async def cancel_order(self, order_id: int) -> None:
        """Request cancellation of a working order."""
        ...


@dataclass
class ManagedOrder:
    """OMS-side record of one broker order."""

    order_id: int
    intent: OrderIntent
    state: OrderState = OrderState.CREATED
    filled_quantity: int = 0
    avg_fill_price: float = 0.0
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    history: List[Tuple[OrderState, datetime]] = field(default_factory=list)

    @property
    def remaining_quantity(self) -> int:
        return self.intent.quantity - self.filled_quantity

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES


FillCallback = Callable[[Fill, ManagedOrder], None]


class OrderManagementSystem:
    """Tracks all orders and positions; the only component that submits to
    the broker.

    Args:
        broker: transport used to place/cancel orders.
        execution_log_path: JSON-lines audit file (parent dirs are created);
            pass ``None`` to log to console/log-file only.
        on_fill: optional callback invoked after each fill is applied
            (used by the app to feed fills back to strategies).
    """

    def __init__(
        self,
        broker: BrokerAdapter,
        execution_log_path: Optional[str | Path] = None,
        on_fill: Optional[FillCallback] = None,
    ) -> None:
        self._broker = broker
        self._orders: Dict[int, ManagedOrder] = {}
        self._positions: Dict[str, Position] = {}
        self._on_fill = on_fill
        self._seen_exec_ids: set[str] = set()
        self._exec_log_path: Optional[Path] = None
        if execution_log_path is not None:
            self._exec_log_path = Path(execution_log_path)
            self._exec_log_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------- queries

    @property
    def orders(self) -> Mapping[int, ManagedOrder]:
        return self._orders

    @property
    def positions(self) -> Mapping[str, Position]:
        return self._positions

    def position_quantities(self) -> Dict[str, int]:
        """Net signed shares per symbol (for risk snapshots / flattening)."""
        return {s: p.quantity for s, p in self._positions.items()
                if p.quantity != 0}

    def open_orders(self) -> List[ManagedOrder]:
        return [o for o in self._orders.values() if not o.is_terminal]

    def get(self, order_id: int) -> Optional[ManagedOrder]:
        return self._orders.get(order_id)

    # ------------------------------------------------------------ commands

    async def submit(self, intent: OrderIntent) -> ManagedOrder:
        """Place an (already risk-approved) intent with the broker.

        On broker failure the order is recorded as REJECTED and the
        exception is re-raised so the caller can decide what to do.
        """
        try:
            order_id = await self._broker.place_order(intent)
        except Exception as exc:
            failed = ManagedOrder(order_id=-intent.intent_id, intent=intent)
            self._orders[failed.order_id] = failed
            self._transition(failed, OrderState.REJECTED,
                             note=f"broker error: {exc}")
            raise
        mo = ManagedOrder(order_id=order_id, intent=intent)
        self._orders[order_id] = mo
        self._transition(mo, OrderState.SUBMITTED)
        return mo

    async def cancel(self, order_id: int) -> None:
        """Request cancellation of one working order (no-op if terminal)."""
        mo = self._orders.get(order_id)
        if mo is None:
            log.warning("cancel requested for unknown order %d", order_id)
            return
        if mo.is_terminal:
            log.debug("cancel skipped; order %d already %s",
                      order_id, mo.state.value)
            return
        self._transition(mo, OrderState.PENDING_CANCEL)
        try:
            await self._broker.cancel_order(order_id)
        except Exception:
            log.exception("broker cancel failed for order %d", order_id)

    async def cancel_all(self) -> int:
        """Cancel every non-terminal order; returns how many were requested."""
        open_ids = [o.order_id for o in self.open_orders()]
        for oid in open_ids:
            await self.cancel(oid)
        return len(open_ids)

    # -------------------------------------------------------------- events

    def on_order_status(self, order_id: int, state: OrderState) -> None:
        """Normalized broker status update (no fill quantities — fills come
        through :meth:`on_fill`)."""
        mo = self._orders.get(order_id)
        if mo is None:
            log.warning("status %s for unknown order %d", state.value,
                        order_id)
            return
        if state in (OrderState.PARTIALLY_FILLED, OrderState.FILLED):
            # Fill-derived states are owned by on_fill; a status echo that
            # matches current knowledge is fine, anything else is suspect.
            if state != mo.state:
                log.debug("ignoring fill-state status echo %s for order %d "
                          "(state=%s)", state.value, order_id, mo.state.value)
            return
        self._transition(mo, state)

    def on_fill(self, fill: Fill) -> None:
        """Apply one execution. Handles partial fills, duplicate exec ids,
        and fills racing a cancel."""
        if fill.exec_id and fill.exec_id in self._seen_exec_ids:
            log.debug("duplicate execution %s ignored", fill.exec_id)
            return
        mo = self._orders.get(fill.order_id)
        if mo is None:
            log.error("fill for unknown order %d: %+d %s @ %.4f",
                      fill.order_id, fill.signed_quantity, fill.symbol,
                      fill.price)
            return
        if mo.state in (OrderState.CANCELLED, OrderState.REJECTED,
                        OrderState.FILLED):
            log.error("fill arrived for order %d in terminal state %s — "
                      "ignored (exec_id=%s)", fill.order_id, mo.state.value,
                      fill.exec_id)
            return
        qty = abs(fill.signed_quantity)
        if qty == 0 or qty > mo.remaining_quantity:
            log.error("fill quantity %d invalid for order %d (remaining %d) "
                      "— ignored", qty, fill.order_id, mo.remaining_quantity)
            return
        if fill.exec_id:
            self._seen_exec_ids.add(fill.exec_id)

        # Volume-weighted average fill price.
        prev = mo.filled_quantity
        mo.avg_fill_price = (
            (mo.avg_fill_price * prev + fill.price * qty) / (prev + qty))
        mo.filled_quantity = prev + qty

        # Position ledger uses the *intent's* direction, not the sign the
        # broker reported, so a mis-signed upstream event cannot flip a book.
        signed = qty if mo.intent.signed_quantity > 0 else -qty
        pos = self._positions.setdefault(fill.symbol, Position(fill.symbol))
        pos.apply_fill(signed, fill.price)

        new_state = (OrderState.FILLED if mo.remaining_quantity == 0
                     else OrderState.PARTIALLY_FILLED)
        self._transition(mo, new_state, note=(
            f"fill {signed:+d} @ {fill.price:.4f} "
            f"({mo.filled_quantity}/{mo.intent.quantity}, "
            f"avg {mo.avg_fill_price:.4f})"))
        self._log_event("fill", {
            "order_id": mo.order_id,
            "exec_id": fill.exec_id,
            "symbol": fill.symbol,
            "signed_quantity": signed,
            "price": fill.price,
            "filled": mo.filled_quantity,
            "remaining": mo.remaining_quantity,
            "avg_fill_price": round(mo.avg_fill_price, 6),
            "position": pos.quantity,
            "realized_pnl": round(pos.realized_pnl, 6),
        })
        if self._on_fill is not None:
            try:
                self._on_fill(fill, mo)
            except Exception:
                log.exception("on_fill callback failed for order %d",
                              mo.order_id)

    # ------------------------------------------------------------ internal

    def _transition(self, mo: ManagedOrder, new_state: OrderState,
                    note: str = "") -> bool:
        """Apply a state transition if the table allows it; returns success."""
        allowed = _TRANSITIONS[mo.state]
        if new_state not in allowed:
            log.error("ILLEGAL transition %s -> %s for order %d ignored%s",
                      mo.state.value, new_state.value, mo.order_id,
                      f" ({note})" if note else "")
            return False
        old = mo.state
        mo.state = new_state
        mo.updated_at = utc_now()
        mo.history.append((new_state, mo.updated_at))
        log.info("order %d [%s %d %s]: %s -> %s%s",
                 mo.order_id, mo.intent.action.value, mo.intent.quantity,
                 mo.intent.symbol, old.value, new_state.value,
                 f" | {note}" if note else "")
        self._log_event("state", {
            "order_id": mo.order_id,
            "symbol": mo.intent.symbol,
            "action": mo.intent.action.value,
            "quantity": mo.intent.quantity,
            "from": old.value,
            "to": new_state.value,
            "note": note,
            "source": mo.intent.source.value,
            "strategy_id": mo.intent.strategy_id,
        })
        return True

    def _log_event(self, kind: str, payload: Dict[str, object]) -> None:
        """Append one JSON line to the execution audit log."""
        if self._exec_log_path is None:
            return
        record = {"ts": utc_now().isoformat(), "kind": kind, **payload}
        try:
            with self._exec_log_path.open("a") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
        except OSError:
            log.exception("failed writing execution log %s",
                          self._exec_log_path)
