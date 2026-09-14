"""Strict pre-trade risk layer.

Every :class:`OrderIntent` MUST pass :meth:`RiskGuardrails.validate` before
the OMS may submit it. The layer enforces, in order:

1. **Kill switch** — once tripped, only risk-generated flattening orders
   pass; everything else is rejected until a human calls :meth:`reset`.
2. **Parameter validity** — positive integer quantity, known order types,
   a positive limit price on limit orders, a sane reference price.
3. **Per-order cap** — ``max_order_quantity``.
4. **Shorting policy** — sells that would take the net position below zero
   are rejected unless ``allow_short``.
5. **Position caps** — resulting |position| in shares and notional.
6. **Gross exposure cap** — portfolio-wide notional after the order.

Separately, :meth:`update_equity` implements the **daily-loss circuit
breaker**: when equity drops more than ``max_daily_loss`` (currency) or
``max_daily_loss_pct`` (fraction of start-of-day equity) below the
start-of-day mark, the kill switch trips and — if configured — the caller
receives flattening intents for every open position.

This module is pure: no broker imports, no I/O beyond logging.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import List, Mapping, Optional

from ..core.types import Action, IntentSource, OrderIntent, OrderType

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RiskDecision:
    """Outcome of a pre-trade check. Falsy-safe: ``if decision.approved``."""

    approved: bool
    reason: str = "ok"

    @staticmethod
    def ok() -> "RiskDecision":
        return RiskDecision(True)

    @staticmethod
    def reject(reason: str) -> "RiskDecision":
        return RiskDecision(False, reason)


@dataclass(frozen=True)
class PortfolioSnapshot:
    """What the risk layer needs to know about the world for one check.

    Args:
        positions: net signed shares per symbol.
        last_prices: most recent trade/close price per symbol; the reference
            price for market orders and for all notional math.
    """

    positions: Mapping[str, int] = field(default_factory=dict)
    last_prices: Mapping[str, float] = field(default_factory=dict)

    def position(self, symbol: str) -> int:
        return int(self.positions.get(symbol, 0))

    def price(self, symbol: str) -> Optional[float]:
        p = self.last_prices.get(symbol)
        return float(p) if p is not None else None

    def gross_notional(self) -> Optional[float]:
        """Sum of |qty| * price across positions; None if any price missing."""
        total = 0.0
        for sym, qty in self.positions.items():
            if qty == 0:
                continue
            price = self.price(sym)
            if price is None or not math.isfinite(price) or price <= 0:
                return None
            total += abs(qty) * price
        return total


class RiskGuardrails:
    """Stateful pre-trade risk gate + daily-loss circuit breaker.

    The class deliberately has **no** method that both trips and silently
    clears the kill switch: :meth:`reset` is the only way back, and it is
    meant to be called by a human operator, never by trading logic.
    """

    def __init__(self, config: "RiskConfigLike") -> None:
        self._cfg = config
        self._kill_switch = False
        self._kill_reason = ""
        self._start_of_day_equity: Optional[float] = None
        self._last_equity: Optional[float] = None

    # ---------------------------------------------------------- properties

    @property
    def kill_switch_active(self) -> bool:
        return self._kill_switch

    @property
    def kill_reason(self) -> str:
        return self._kill_reason

    @property
    def start_of_day_equity(self) -> Optional[float]:
        return self._start_of_day_equity

    @property
    def daily_pnl(self) -> Optional[float]:
        if self._start_of_day_equity is None or self._last_equity is None:
            return None
        return self._last_equity - self._start_of_day_equity

    # ------------------------------------------------------- kill switch

    def trip(self, reason: str) -> None:
        """Activate the kill switch. Idempotent; only logs the first trip."""
        if not self._kill_switch:
            self._kill_switch = True
            self._kill_reason = reason
            log.critical("KILL SWITCH TRIPPED: %s", reason)

    def reset(self, operator: str) -> None:
        """Clear the kill switch. Requires a non-empty operator tag so every
        reset is attributable in the logs."""
        if not operator:
            raise ValueError("kill switch reset requires an operator tag")
        log.warning("kill switch reset by %s (was: %s)",
                    operator, self._kill_reason or "-")
        self._kill_switch = False
        self._kill_reason = ""

    # -------------------------------------------------- equity / drawdown

    def mark_start_of_day(self, equity: float) -> None:
        """Record the equity mark all daily-loss checks are measured from."""
        if not math.isfinite(equity) or equity <= 0:
            raise ValueError(f"start-of-day equity must be positive: {equity}")
        self._start_of_day_equity = equity
        self._last_equity = equity
        log.info("start-of-day equity marked: %.2f", equity)

    def update_equity(self, equity: float) -> bool:
        """Feed a fresh equity mark; returns True if this update tripped the
        daily-loss circuit breaker (kill switch is then active)."""
        if not math.isfinite(equity):
            log.warning("ignoring non-finite equity update: %r", equity)
            return False
        self._last_equity = equity
        if self._start_of_day_equity is None or self._kill_switch:
            return False
        loss = self._start_of_day_equity - equity
        limit = min(self._cfg.max_daily_loss,
                    self._cfg.max_daily_loss_pct * self._start_of_day_equity)
        if loss >= limit:
            self.trip(
                f"daily loss {loss:.2f} breached limit {limit:.2f} "
                f"(start {self._start_of_day_equity:.2f} -> {equity:.2f})")
            return True
        return False

    def flatten_intents(
        self, positions: Mapping[str, int]
    ) -> List[OrderIntent]:
        """Market orders that close every open position (kill-switch path)."""
        intents: List[OrderIntent] = []
        for symbol, qty in sorted(positions.items()):
            qty = int(qty)
            if qty == 0:
                continue
            intents.append(OrderIntent(
                action=Action.SELL if qty > 0 else Action.BUY,
                symbol=symbol,
                quantity=abs(qty),
                order_type=OrderType.MARKET,
                source=IntentSource.RISK_FLATTEN,
                strategy_id="risk",
                reason=f"kill-switch flatten ({self._kill_reason or 'manual'})",
            ))
        return intents

    # ------------------------------------------------------------ validate

    def validate(
        self, intent: OrderIntent, snapshot: PortfolioSnapshot
    ) -> RiskDecision:
        """The mandatory pre-trade gate. See module docstring for the order
        of checks. Rejections never raise — they return a decision so the
        caller can log and move on."""
        # 1. Kill switch.
        if self._kill_switch and intent.source is not IntentSource.RISK_FLATTEN:
            return RiskDecision.reject(
                f"kill switch active: {self._kill_reason}")

        # 2. Parameter validity.
        if not intent.symbol or not intent.symbol.strip():
            return RiskDecision.reject("empty symbol")
        if not isinstance(intent.quantity, int) or isinstance(intent.quantity, bool):
            return RiskDecision.reject(
                f"quantity must be an integer, got {type(intent.quantity).__name__}")
        if intent.quantity <= 0:
            return RiskDecision.reject(
                f"quantity must be positive, got {intent.quantity}")
        if intent.order_type not in (OrderType.MARKET, OrderType.LIMIT):
            return RiskDecision.reject(
                f"unsupported order type {intent.order_type!r}")
        if intent.order_type is OrderType.LIMIT:
            lp = intent.limit_price
            if lp is None or not math.isfinite(lp) or lp <= 0:
                return RiskDecision.reject(
                    f"limit order requires positive limit price, got {lp!r}")

        price = (intent.limit_price
                 if intent.order_type is OrderType.LIMIT
                 else snapshot.price(intent.symbol))
        if price is None or not math.isfinite(price) or price <= 0:
            return RiskDecision.reject(
                f"no valid reference price for {intent.symbol} "
                f"(got {price!r}) — refusing to size blind")

        # Risk-generated flattening orders skip the caps below: their whole
        # purpose is to reduce exposure, and blocking them would strand risk.
        if intent.source is IntentSource.RISK_FLATTEN:
            return RiskDecision.ok()

        # 3. Per-order cap.
        if intent.quantity > self._cfg.max_order_quantity:
            return RiskDecision.reject(
                f"order quantity {intent.quantity} exceeds max_order_quantity "
                f"{self._cfg.max_order_quantity}")

        # 4. Shorting policy.
        current = snapshot.position(intent.symbol)
        resulting = current + intent.signed_quantity
        if resulting < 0 and not self._cfg.allow_short:
            return RiskDecision.reject(
                f"order would short {intent.symbol} "
                f"({current} -> {resulting}) and allow_short is false")

        # 5. Position caps (shares and notional).
        if abs(resulting) > self._cfg.max_position_shares:
            return RiskDecision.reject(
                f"resulting position {resulting} exceeds max_position_shares "
                f"{self._cfg.max_position_shares}")
        resulting_notional = abs(resulting) * price
        if resulting_notional > self._cfg.max_position_notional:
            return RiskDecision.reject(
                f"resulting notional {resulting_notional:.2f} exceeds "
                f"max_position_notional {self._cfg.max_position_notional:.2f}")

        # 6. Gross exposure cap.
        gross = snapshot.gross_notional()
        if gross is None:
            return RiskDecision.reject(
                "cannot price existing positions — refusing to add exposure")
        current_leg = abs(current) * price
        new_gross = gross - current_leg + resulting_notional
        if new_gross > self._cfg.max_gross_notional:
            return RiskDecision.reject(
                f"gross notional {new_gross:.2f} would exceed "
                f"max_gross_notional {self._cfg.max_gross_notional:.2f}")

        return RiskDecision.ok()


class RiskConfigLike:
    """Structural protocol documentation for what ``RiskGuardrails`` reads.

    Any object with these attributes works (the dataclass in core.config,
    or a stub in tests):

    * ``max_position_shares: int``
    * ``max_position_notional: float``
    * ``max_order_quantity: int``
    * ``max_gross_notional: float``
    * ``max_daily_loss: float``
    * ``max_daily_loss_pct: float``
    * ``allow_short: bool``
    * ``kill_switch_flattens: bool``
    """

    max_position_shares: int
    max_position_notional: float
    max_order_quantity: int
    max_gross_notional: float
    max_daily_loss: float
    max_daily_loss_pct: float
    allow_short: bool
    kill_switch_flattens: bool
