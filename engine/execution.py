"""Execution sequencing (§5.2, §5.3, §5.10).

- Sells are submitted first and each must reach a TERMINAL state before any
  buy is sized. The account is then re-read, and buys are sized off cash
  that demonstrably exists — never off cash a pending sell was supposed to
  free.
- Escalation (unfilled limit -> market) is ONE hop, enforced by config
  (escalation_max_hops == 1) and by structure: the escalated order carries
  no further escalation budget.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .broker import Broker, OrderResult
from .errors import ExecutionError
from .journal import Journal, NullJournal
from .orders import DroppedOrder, Order, Side, is_success, is_terminal
from .risk import RiskEngine


@dataclass
class RebalanceOutcome:
    results: list[OrderResult] = field(default_factory=list)
    dropped: list[DroppedOrder] = field(default_factory=list)
    escalations: int = 0

    @property
    def any_failures(self) -> bool:
        return any(not is_success(r.status) for r in self.results)


def _submit_single(broker: Broker, risk: RiskEngine, order: Order,
                   prices: dict[str, float]) -> tuple[list[OrderResult], list[DroppedOrder]]:
    approved, dropped = risk.filter_orders([order], prices)
    if not approved.orders:
        return [], dropped
    results = broker.submit(approved)
    for r in results:
        if not is_terminal(r.status):
            # A real async broker adapter must block here until terminal
            # (§5.2). The engine refuses to treat a pending order as done.
            raise ExecutionError(
                f"order {r.order.id} returned non-terminal status {r.status}; "
                "broker adapters must wait for a terminal state"
            )
    return results, dropped


def _submit_with_escalation(broker: Broker, risk: RiskEngine, order: Order,
                            prices: dict[str, float], max_hops: int,
                            journal: Journal) -> tuple[list[OrderResult], list[DroppedOrder], int]:
    """Submit; if a LIMIT order ends unfilled, escalate to market ONCE.

    The escalated order is a market order with no remaining budget — there
    is structurally no second hop (§5.10).
    """
    results, dropped = _submit_single(broker, risk, order, prices)
    escalations = 0
    # Escalate only a limit order that got NOTHING: a partial fill must not
    # be re-sent at full size.
    if (order.limit_price is not None and max_hops >= 1
            and results and not any(is_success(r.status) for r in results)
            and all(r.filled_shares == 0 for r in results)):
        market = Order(symbol=order.symbol, side=order.side, shares=order.shares,
                       is_full_exit=order.is_full_exit, limit_price=None)
        journal.record("escalation", original_id=order.id, escalated_id=market.id,
                       symbol=order.symbol, note="limit unfilled -> market, single hop")
        more, more_dropped = _submit_single(broker, risk, market, prices)
        escalations = 1
        if more and not any(is_success(r.status) for r in more):
            journal.record("escalation_failed", order_id=market.id, symbol=order.symbol,
                           note="market escalation did not fill; giving up (no further hops)")
        results += more
        dropped += more_dropped
    return results, dropped, escalations


def execute_rebalance(
    broker: Broker,
    risk: RiskEngine,
    orders: list[Order],
    prices: dict[str, float],
    *,
    escalation_max_hops: int = 1,
    journal: Journal | None = None,
) -> RebalanceOutcome:
    journal = journal or NullJournal()
    outcome = RebalanceOutcome()

    sells = [o for o in orders if o.side is Side.SELL]
    buys = [o for o in orders if o.side is Side.BUY]

    # 1. Sells first, each to a terminal state (§5.2, §5.3).
    for o in sells:
        results, dropped, esc = _submit_with_escalation(
            broker, risk, o, prices, escalation_max_hops, journal)
        outcome.results += results
        outcome.dropped += dropped
        outcome.escalations += esc

    # 2. Re-read the account: buys are sized off cash that DEMONSTRABLY
    #    exists, not cash the sells were supposed to free (§5.2).
    account = broker.get_account()
    available = account.cash

    for o in buys:
        px = prices.get(o.symbol)
        if px is None or px <= 0:
            outcome.dropped.append(DroppedOrder(o, "no valid price at buy sizing"))
            continue
        cost = risk.cost_model.order_cost(shares=o.shares, price=px)
        needed = o.shares * px + cost.total
        order = o
        if needed > available:
            resized = math.floor((available - cost.total) / px) if px > 0 else 0
            if resized <= 0:
                outcome.dropped.append(DroppedOrder(
                    o, f"insufficient confirmed cash ({available:.2f}) after sells"))
                continue
            journal.record("buy_resized", order_id=o.id, symbol=o.symbol,
                           planned=o.shares, resized=resized, cash=available)
            order = Order(symbol=o.symbol, side=Side.BUY, shares=resized,
                          limit_price=o.limit_price)
        results, dropped, esc = _submit_with_escalation(
            broker, risk, order, prices, escalation_max_hops, journal)
        outcome.results += results
        outcome.dropped += dropped
        outcome.escalations += esc
        for r in results:
            if is_success(r.status):
                available -= r.filled_shares * r.fill_price + r.commission

    for r in outcome.results:
        journal.record("order_result", order_id=r.order.id, symbol=r.order.symbol,
                       side=r.order.side.value, status=r.status.value,
                       filled=r.filled_shares, price=r.fill_price)
    for dr in outcome.dropped:
        journal.record("order_dropped", order_id=dr.order.id, symbol=dr.order.symbol,
                       side=dr.order.side.value, reason=dr.reason)
    return outcome
