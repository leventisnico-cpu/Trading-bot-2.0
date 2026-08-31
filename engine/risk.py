"""Risk layer (§3.6, §7). Signals propose; risk disposes.

Structural veto: brokers only accept ApprovedOrders, and only RiskEngine
constructs ApprovedOrders. There is no path from signal to venue that
bypasses this module.

The daily-loss check takes PRIOR state explicitly (§5.1) — the caller reads
state before overwriting it, and the comparison can never see today's
equity on both sides.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from .config import RiskConfig
from .costs import CostModel
from .errors import HaltError
from .orders import DroppedOrder, Order, truncate_to_cap
from .state import EngineState


class PreTradeDecision(Enum):
    OK = "OK"
    STAND_DOWN = "STAND_DOWN"      # soft halt: no trades today
    HARD_KILL = "HARD_KILL"        # liquidate + halt permanently; manual reset only


@dataclass(frozen=True)
class PreTradeResult:
    decision: PreTradeDecision
    reason: str
    daily_return: float
    drawdown_from_peak: float


class ApprovedOrders:
    """Only RiskEngine may construct this. Brokers require it."""

    _token = object()

    def __init__(self, orders: list[Order], token=None):
        if token is not RiskEngine._approval_token:
            raise TypeError(
                "ApprovedOrders may only be created by RiskEngine (§3.6: "
                "no path from signal to exchange bypasses the risk layer)"
            )
        self.orders = list(orders)


class RiskEngine:
    _approval_token = object()

    def __init__(self, cfg: RiskConfig, cost_model: CostModel):
        self.cfg = cfg
        self.cost_model = cost_model

    # ---- pre-trade gate -------------------------------------------------

    def check_not_halted(self, prior_state: EngineState) -> None:
        if prior_state.halted:
            raise HaltError(
                f"system is HALTED ({prior_state.halt_reason}); "
                "manual reset required — no automatic recovery, ever (§7)"
            )

    def pre_trade(self, prior_state: EngineState, current_equity: float, today: date) -> PreTradeResult:
        """Evaluate kill/halt conditions BEFORE state is overwritten (§5.1).

        prior_state must be the state as loaded at the start of the cycle.
        """
        self.check_not_halted(prior_state)

        peak = max(prior_state.peak_equity, current_equity)
        drawdown = 0.0 if peak <= 0 else (peak - current_equity) / peak

        daily_return = 0.0
        if prior_state.last_equity > 0 and prior_state.last_equity_date != today.isoformat():
            daily_return = current_equity / prior_state.last_equity - 1.0

        if current_equity < self.cfg.min_equity_floor:
            return PreTradeResult(
                PreTradeDecision.HARD_KILL,
                f"equity {current_equity:.2f} below floor {self.cfg.min_equity_floor:.2f}",
                daily_return, drawdown,
            )
        if drawdown > self.cfg.max_drawdown_pct:
            return PreTradeResult(
                PreTradeDecision.HARD_KILL,
                f"drawdown {drawdown:.1%} exceeds max {self.cfg.max_drawdown_pct:.1%}",
                daily_return, drawdown,
            )
        if daily_return < -self.cfg.max_daily_loss_pct:
            return PreTradeResult(
                PreTradeDecision.STAND_DOWN,
                f"daily loss {daily_return:.1%} exceeds max {self.cfg.max_daily_loss_pct:.1%}",
                daily_return, drawdown,
            )
        return PreTradeResult(PreTradeDecision.OK, "ok", daily_return, drawdown)

    # ---- weight clamps (§3.4: structural, not advisory) -----------------

    def clamp_weights(self, weights: dict[str, float]) -> dict[str, float]:
        clamped = {}
        for sym, w in weights.items():
            if not self.cfg.allow_short:
                w = max(0.0, w)
            w = min(w, self.cfg.max_position_weight)
            clamped[sym] = w
        gross = sum(abs(w) for w in clamped.values())
        cap = self.cfg.max_gross_exposure if self.cfg.allow_leverage else min(1.0, self.cfg.max_gross_exposure)
        if gross > cap and gross > 0:
            scale = cap / gross
            clamped = {s: w * scale for s, w in clamped.items()}
        return clamped

    # ---- order-level backstops (§7) ------------------------------------

    def filter_orders(
        self, orders: list[Order], prices: dict[str, float]
    ) -> tuple[ApprovedOrders, list[DroppedOrder]]:
        """The single gate every order passes to reach a broker."""
        dropped: list[DroppedOrder] = []
        kept: list[Order] = []
        for o in orders:
            px = prices.get(o.symbol)
            if px is None or px <= 0:
                dropped.append(DroppedOrder(o, f"no valid price for {o.symbol}"))
                continue
            notional = o.shares * px
            # Full exits are exempt from EVERY minimum-size filter (§5.4);
            # otherwise positions ratchet down but never close.
            if notional < self.cfg.min_order_notional and not o.is_full_exit:
                dropped.append(DroppedOrder(
                    o, f"below min_order_notional {self.cfg.min_order_notional:.2f} "
                       f"(notional {notional:.2f}); full exits are exempt"))
                continue
            frac = self.cost_model.all_in_fraction(shares=o.shares, price=px)
            if frac > self.cfg.max_cost_fraction and not o.is_full_exit:
                dropped.append(DroppedOrder(
                    o, f"all-in cost {frac:.2%} of notional exceeds max_cost_fraction "
                       f"{self.cfg.max_cost_fraction:.2%}"))
                continue
            kept.append(o)
        kept, cap_dropped = truncate_to_cap(kept, self.cfg.max_orders_per_day)
        dropped.extend(cap_dropped)
        return ApprovedOrders(kept, token=RiskEngine._approval_token), dropped
