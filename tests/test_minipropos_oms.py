"""Unit tests for the OMS state machine, partial fills, and position ledger.

Uses a fake broker; runs coroutines via asyncio.run so no pytest-asyncio
plugin is required.
"""

from __future__ import annotations

import asyncio
import json
from typing import Awaitable, List, TypeVar

import pytest

from mini_prop_os.core.types import (Action, Fill, IntentSource, OrderIntent,
                                     OrderType)
from mini_prop_os.execution.oms import (OrderManagementSystem, OrderState)

T = TypeVar("T")


def run(coro: Awaitable[T]) -> T:
    return asyncio.run(coro)  # type: ignore[arg-type]


class FakeBroker:
    """Records placements/cancels; assigns sequential order ids."""

    def __init__(self, fail_place: bool = False) -> None:
        self.next_id = 100
        self.placed: List[OrderIntent] = []
        self.cancelled: List[int] = []
        self.fail_place = fail_place

    async def place_order(self, intent: OrderIntent) -> int:
        if self.fail_place:
            raise ConnectionError("socket down")
        self.placed.append(intent)
        self.next_id += 1
        return self.next_id

    async def cancel_order(self, order_id: int) -> None:
        self.cancelled.append(order_id)


def intent(action=Action.BUY, qty=10, symbol="SPY") -> OrderIntent:
    return OrderIntent(action=action, symbol=symbol, quantity=qty,
                       order_type=OrderType.MARKET,
                       source=IntentSource.STRATEGY, strategy_id="test")


def fill(order_id: int, signed_qty: int, price: float, symbol="SPY",
         exec_id: str = "") -> Fill:
    return Fill(order_id=order_id, symbol=symbol, signed_quantity=signed_qty,
                price=price, exec_id=exec_id)


def make_oms(tmp_path=None, **kw):
    broker = FakeBroker(**kw)
    log_path = (tmp_path / "exec.jsonl") if tmp_path is not None else None
    return broker, OrderManagementSystem(broker, execution_log_path=log_path)


# ----------------------------------------------------------- submission

def test_submit_transitions_to_submitted():
    broker, oms = make_oms()
    mo = run(oms.submit(intent()))
    assert mo.state is OrderState.SUBMITTED
    assert mo.order_id == 101
    assert broker.placed[0].symbol == "SPY"
    assert oms.open_orders() == [mo]


def test_broker_failure_records_rejection_and_reraises():
    broker, oms = make_oms(fail_place=True)
    with pytest.raises(ConnectionError):
        run(oms.submit(intent()))
    rejected = list(oms.orders.values())
    assert len(rejected) == 1
    assert rejected[0].state is OrderState.REJECTED
    assert oms.open_orders() == []


# ------------------------------------------------------- fills / partials

def test_full_fill_lifecycle_and_position():
    _, oms = make_oms()
    mo = run(oms.submit(intent(qty=10)))
    oms.on_fill(fill(mo.order_id, 10, 500.0, exec_id="e1"))
    assert mo.state is OrderState.FILLED
    assert mo.filled_quantity == 10
    assert mo.avg_fill_price == 500.0
    assert oms.positions["SPY"].quantity == 10
    assert oms.position_quantities() == {"SPY": 10}


def test_partial_fills_accumulate_with_vwap():
    _, oms = make_oms()
    mo = run(oms.submit(intent(qty=10)))
    oms.on_fill(fill(mo.order_id, 4, 500.0, exec_id="e1"))
    assert mo.state is OrderState.PARTIALLY_FILLED
    assert mo.remaining_quantity == 6
    oms.on_fill(fill(mo.order_id, 6, 510.0, exec_id="e2"))
    assert mo.state is OrderState.FILLED
    assert mo.avg_fill_price == pytest.approx(506.0)  # (4*500+6*510)/10
    assert oms.positions["SPY"].quantity == 10
    assert oms.positions["SPY"].avg_price == pytest.approx(506.0)


def test_duplicate_exec_id_ignored():
    _, oms = make_oms()
    mo = run(oms.submit(intent(qty=10)))
    oms.on_fill(fill(mo.order_id, 4, 500.0, exec_id="dup"))
    oms.on_fill(fill(mo.order_id, 4, 500.0, exec_id="dup"))
    assert mo.filled_quantity == 4
    assert oms.positions["SPY"].quantity == 4


def test_overfill_rejected():
    _, oms = make_oms()
    mo = run(oms.submit(intent(qty=10)))
    oms.on_fill(fill(mo.order_id, 11, 500.0, exec_id="e1"))
    assert mo.filled_quantity == 0
    assert mo.state is OrderState.SUBMITTED


def test_fill_for_unknown_order_ignored():
    _, oms = make_oms()
    oms.on_fill(fill(9999, 5, 100.0))
    assert oms.position_quantities() == {}


def test_sell_fill_reduces_position_and_realizes_pnl():
    _, oms = make_oms()
    buy = run(oms.submit(intent(action=Action.BUY, qty=10)))
    oms.on_fill(fill(buy.order_id, 10, 500.0, exec_id="b1"))
    sell = run(oms.submit(intent(action=Action.SELL, qty=10)))
    # Broker reports SLD side; OMS applies the intent's direction.
    oms.on_fill(fill(sell.order_id, -10, 510.0, exec_id="s1"))
    pos = oms.positions["SPY"]
    assert pos.quantity == 0
    assert pos.realized_pnl == pytest.approx(100.0)  # 10 * (510-500)


# --------------------------------------------------------------- cancels

def test_cancel_flow():
    broker, oms = make_oms()
    mo = run(oms.submit(intent()))
    run(oms.cancel(mo.order_id))
    assert mo.state is OrderState.PENDING_CANCEL
    assert broker.cancelled == [mo.order_id]
    oms.on_order_status(mo.order_id, OrderState.CANCELLED)
    assert mo.state is OrderState.CANCELLED
    assert oms.open_orders() == []


def test_fill_racing_cancel_is_accepted():
    _, oms = make_oms()
    mo = run(oms.submit(intent(qty=10)))
    run(oms.cancel(mo.order_id))
    oms.on_fill(fill(mo.order_id, 3, 500.0, exec_id="race"))
    assert mo.state is OrderState.PARTIALLY_FILLED
    oms.on_order_status(mo.order_id, OrderState.CANCELLED)  # remainder dies
    assert mo.state is OrderState.CANCELLED
    assert mo.filled_quantity == 3
    assert oms.positions["SPY"].quantity == 3


def test_cancel_all_only_touches_open_orders():
    broker, oms = make_oms()
    done = run(oms.submit(intent(qty=5)))
    oms.on_fill(fill(done.order_id, 5, 500.0, exec_id="f"))
    working = run(oms.submit(intent(qty=5)))
    n = run(oms.cancel_all())
    assert n == 1
    assert broker.cancelled == [working.order_id]


def test_cancel_unknown_or_terminal_is_noop():
    broker, oms = make_oms()
    run(oms.cancel(4242))
    mo = run(oms.submit(intent(qty=5)))
    oms.on_fill(fill(mo.order_id, 5, 500.0, exec_id="f"))
    run(oms.cancel(mo.order_id))
    assert broker.cancelled == []


# ---------------------------------------------------- state machine guards

def test_illegal_transitions_are_ignored():
    _, oms = make_oms()
    mo = run(oms.submit(intent(qty=5)))
    oms.on_fill(fill(mo.order_id, 5, 500.0, exec_id="f"))
    assert mo.state is OrderState.FILLED
    # Late/duplicate broker events must not corrupt a terminal order.
    oms.on_order_status(mo.order_id, OrderState.CANCELLED)
    assert mo.state is OrderState.FILLED
    oms.on_fill(fill(mo.order_id, 5, 500.0, exec_id="g"))
    assert mo.filled_quantity == 5
    assert oms.positions["SPY"].quantity == 5


def test_same_state_broker_echo_is_a_noop():
    # IBKR emits PendingSubmit -> PreSubmitted -> Submitted, which all map
    # to SUBMITTED; the repeats must not be treated as illegal transitions.
    _, oms = make_oms()
    mo = run(oms.submit(intent(qty=10)))
    oms.on_order_status(mo.order_id, OrderState.SUBMITTED)
    oms.on_order_status(mo.order_id, OrderState.SUBMITTED)
    assert mo.state is OrderState.SUBMITTED
    assert [s for s, _ in mo.history] == [OrderState.SUBMITTED]


def test_status_echo_of_fill_states_does_not_transition():
    _, oms = make_oms()
    mo = run(oms.submit(intent(qty=10)))
    oms.on_order_status(mo.order_id, OrderState.FILLED)  # status w/o fill
    assert mo.state is OrderState.SUBMITTED  # fills own fill states
    assert mo.filled_quantity == 0


def test_history_records_every_transition():
    _, oms = make_oms()
    mo = run(oms.submit(intent(qty=10)))
    oms.on_fill(fill(mo.order_id, 4, 500.0, exec_id="a"))
    oms.on_fill(fill(mo.order_id, 6, 501.0, exec_id="b"))
    states = [s for s, _ in mo.history]
    assert states == [OrderState.SUBMITTED, OrderState.PARTIALLY_FILLED,
                      OrderState.FILLED]


# ---------------------------------------------------------- execution log

def test_execution_log_written_as_jsonl(tmp_path):
    _, oms = make_oms(tmp_path=tmp_path)
    mo = run(oms.submit(intent(qty=10)))
    oms.on_fill(fill(mo.order_id, 10, 500.0, exec_id="e1"))
    lines = [json.loads(l) for l in
             (tmp_path / "exec.jsonl").read_text().splitlines()]
    kinds = [l["kind"] for l in lines]
    assert kinds == ["state", "state", "fill"]  # SUBMITTED, FILLED, fill
    fill_rec = lines[-1]
    assert fill_rec["symbol"] == "SPY"
    assert fill_rec["signed_quantity"] == 10
    assert fill_rec["position"] == 10


# -------------------------------------------------------- position ledger

def test_position_crossing_through_flat():
    from mini_prop_os.core.types import Position

    p = Position("SPY")
    p.apply_fill(10, 100.0)
    p.apply_fill(-15, 110.0)  # close 10 (+100 pnl), open -5 @ 110
    assert p.quantity == -5
    assert p.avg_price == 110.0
    assert p.realized_pnl == pytest.approx(100.0)
    p.apply_fill(5, 105.0)  # buy back short: +5 * (110-105) = +25
    assert p.quantity == 0
    assert p.realized_pnl == pytest.approx(125.0)
    assert p.avg_price == 0.0
