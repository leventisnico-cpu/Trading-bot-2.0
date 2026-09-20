"""Historical paper-trading harness for Mini-Prop OS.

Replays historical bars through the *production* pipeline — the real
:class:`RiskGuardrails`, the real :class:`OrderManagementSystem`, and a real
strategy instance — with only the broker simulated. This is deliberately not
a separate backtester: it validates the operating system's order flow,
risk gating, kill-switch behavior, and accounting, using the same objects
``app.py`` wires to ib_insync.

Execution model (conservative, deterministic):

* Market orders submitted on bar T fill at bar T+1's open, adjusted by
  ``slippage_ticks`` against the trader, rounded to the tick.
* Orders of 2+ units are filled in two partial fills at the same price to
  exercise the OMS partial-fill path on every multi-unit order.
* Commission is charged per unit per side.
* Equity = initial cash + multiplier * (realized + unrealized OMS PnL)
  - commissions; the OMS ledger is the accounting source of truth and the
  simulator independently cross-checks it (see ``accounting_error``).

No broker library is imported; the module runs in CI.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence, Tuple

from .core.types import Action, Bar, Fill, IntentSource, OrderIntent
from .execution.oms import ManagedOrder, OrderManagementSystem, OrderState
from .risk.guardrails import PortfolioSnapshot, RiskGuardrails
from .strategy.base import BaseStrategy

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SimConfig:
    """Simulator economics."""

    multiplier: float = 5.0          # MES: $5 per index point
    tick_size: float = 0.25
    slippage_ticks: int = 1          # adverse slippage per fill
    commission_per_unit: float = 0.62  # IBKR micro-future, per side
    initial_cash: float = 100_000.0
    split_fills: bool = True         # 2+ unit orders fill in two partials


@dataclass
class SimOrder:
    order_id: int
    intent: OrderIntent
    cancelled: bool = False


@dataclass
class RoundTrip:
    """One completed entry->flat cycle, for win-rate statistics."""

    entry_time: datetime
    exit_time: datetime
    units: int
    pnl: float  # currency, net of commissions attributed to the cycle


class SimulatedBroker:
    """BrokerAdapter that fills market orders at the next bar's open."""

    def __init__(self, cfg: SimConfig) -> None:
        self.cfg = cfg
        self.oms: Optional[OrderManagementSystem] = None
        self._next_id = 1000
        self._pending: List[SimOrder] = []
        self._exec_seq = 0
        self.commissions_paid = 0.0
        self.orders_received: List[OrderIntent] = []

    async def place_order(self, intent: OrderIntent) -> int:
        self._next_id += 1
        self._pending.append(SimOrder(self._next_id, intent))
        self.orders_received.append(intent)
        return self._next_id

    async def cancel_order(self, order_id: int) -> None:
        for order in self._pending:
            if order.order_id == order_id and not order.cancelled:
                order.cancelled = True
                if self.oms is not None:
                    self.oms.on_order_status(order_id, OrderState.CANCELLED)
                return

    # ------------------------------------------------------------- engine

    def _fill_price(self, intent: OrderIntent, open_price: float) -> float:
        slip = self.cfg.slippage_ticks * self.cfg.tick_size
        raw = open_price + slip if intent.action is Action.BUY else \
            open_price - slip
        return round(raw / self.cfg.tick_size) * self.cfg.tick_size

    def process_bar_open(self, bar: Bar) -> int:
        """Fill all pending orders at this bar's open; returns fill count."""
        assert self.oms is not None
        fills = 0
        pending, self._pending = self._pending, []
        for order in pending:
            if order.cancelled:
                continue
            price = self._fill_price(order.intent, bar.open)
            qty = order.intent.quantity
            parts = ([qty // 2, qty - qty // 2]
                     if self.cfg.split_fills and qty >= 2 else [qty])
            for part in parts:
                self._exec_seq += 1
                signed = part if order.intent.action is Action.BUY else -part
                self.oms.on_fill(Fill(
                    order_id=order.order_id, symbol=order.intent.symbol,
                    signed_quantity=signed, price=price,
                    timestamp=bar.timestamp,
                    exec_id=f"sim-{self._exec_seq}"))
                self.commissions_paid += part * self.cfg.commission_per_unit
                fills += 1
        return fills

    @property
    def has_pending(self) -> bool:
        return any(not o.cancelled for o in self._pending)


@dataclass
class SimResult:
    """Everything the validation scorecard needs to judge one run."""

    bars: int = 0
    final_equity: float = 0.0
    equity_curve: List[Tuple[datetime, float]] = field(default_factory=list)
    round_trips: List[RoundTrip] = field(default_factory=list)
    max_position: int = 0
    min_position: int = 0
    max_order_quantity: int = 0
    risk_rejections: int = 0
    kill_switch_tripped: bool = False
    kill_switch_reason: str = ""
    position_after_kill: Optional[int] = None
    orders_after_kill: int = 0
    corrupt_bars_skipped: int = 0
    accounting_error: float = 0.0
    open_orders_at_end: int = 0
    final_position: int = 0

    @property
    def wins(self) -> int:
        return sum(1 for t in self.round_trips if t.pnl > 0)

    @property
    def win_rate(self) -> Optional[float]:
        return self.wins / len(self.round_trips) if self.round_trips else None

    @property
    def total_return(self) -> float:
        return self.final_equity - (self.equity_curve[0][1]
                                    if self.equity_curve else 0.0)

    @property
    def max_drawdown(self) -> float:
        peak, dd = float("-inf"), 0.0
        for _, eq in self.equity_curve:
            peak = max(peak, eq)
            dd = max(dd, peak - eq)
        return dd


class HistoricalSession:
    """Replays bars through strategy -> risk -> OMS with a simulated broker.

    Mirrors ``app.TradingApp``'s pipeline: fills happen at the bar open,
    equity is marked at the bar close and fed to the daily-loss breaker,
    then the strategy sees the completed bar and its intents pass through
    the mandatory risk gate before the OMS submits them.
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        risk: RiskGuardrails,
        sim_cfg: Optional[SimConfig] = None,
        execution_log_path: Optional[str] = None,
    ) -> None:
        self.sim_cfg = sim_cfg or SimConfig()
        self.strategy = strategy
        self.risk = risk
        self.broker = SimulatedBroker(self.sim_cfg)
        self.oms = OrderManagementSystem(
            self.broker, execution_log_path=execution_log_path,
            on_fill=self._on_oms_fill)
        self.broker.oms = self.oms
        self.result = SimResult()
        self._last_price: Optional[float] = None
        self._prev_equity: Optional[float] = None
        self._entry_time: Optional[datetime] = None
        self._entry_commission_marker = 0.0
        self._entry_realized_marker = 0.0
        self._flattened = False

    # ---------------------------------------------------------- accounting

    def _equity(self, mark: float) -> float:
        m = self.sim_cfg.multiplier
        realized = sum(p.realized_pnl for p in self.oms.positions.values())
        unrealized = sum(p.unrealized_pnl(mark)
                         for p in self.oms.positions.values())
        return (self.sim_cfg.initial_cash + m * (realized + unrealized)
                - self.broker.commissions_paid)

    def _net_position(self) -> int:
        return sum(self.oms.position_quantities().values())

    def _snapshot(self, symbol: str) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            positions=self.oms.position_quantities(),
            last_prices={symbol: self._last_price or 0.0},
            multipliers={symbol: self.sim_cfg.multiplier},
        )

    def _on_oms_fill(self, fill: Fill, order: ManagedOrder) -> None:
        signed = (abs(fill.signed_quantity)
                  if order.intent.signed_quantity > 0
                  else -abs(fill.signed_quantity))
        if order.intent.strategy_id == self.strategy.strategy_id:
            self.strategy.on_own_fill(signed, fill.price)
        # Round-trip bookkeeping: flat -> open marks an entry; back to flat
        # closes the cycle.
        pos = self._net_position()
        if pos != 0 and self._entry_time is None:
            self._entry_time = fill.timestamp
            self._entry_realized_marker = sum(
                p.realized_pnl for p in self.oms.positions.values())
            self._entry_commission_marker = self.broker.commissions_paid
        elif pos == 0 and self._entry_time is not None:
            realized = sum(p.realized_pnl
                           for p in self.oms.positions.values())
            pnl = (self.sim_cfg.multiplier
                   * (realized - self._entry_realized_marker)
                   - (self.broker.commissions_paid
                      - self._entry_commission_marker))
            self.result.round_trips.append(RoundTrip(
                entry_time=self._entry_time, exit_time=fill.timestamp,
                units=abs(signed), pnl=pnl))
            self._entry_time = None

    # -------------------------------------------------------------- replay

    async def _route(self, intent: OrderIntent) -> None:
        decision = self.risk.validate(intent, self._snapshot(intent.symbol))
        if not decision.approved:
            self.result.risk_rejections += 1
            log.debug("risk reject: %s", decision.reason)
            return
        if self.risk.kill_switch_active:
            self.result.orders_after_kill += (
                intent.source is not IntentSource.RISK_FLATTEN)
        await self.oms.submit(intent)
        self.result.max_order_quantity = max(
            self.result.max_order_quantity, intent.quantity)

    async def _kill_switch_fired(self) -> None:
        if self._flattened:
            return
        self._flattened = True
        await self.oms.cancel_all()
        for intent in self.risk.flatten_intents(
                self.oms.position_quantities()):
            await self._route(intent)

    async def run(self, bars: Sequence[Bar]) -> SimResult:
        """Replay the bar sequence; returns the populated result."""
        res = self.result
        for bar in bars:
            res.bars += 1
            # 1. Fills for orders submitted on the previous bar.
            self.broker.process_bar_open(bar)
            self._last_price = bar.close
            # 2. Mark equity, drive the daily-loss circuit breaker. With
            # one bar per day, "start of day" is the previous bar's close.
            equity = self._equity(bar.close)
            if self._prev_equity is not None and not self.risk.kill_switch_active:
                self.risk.mark_start_of_day(self._prev_equity)
            tripped = self.risk.update_equity(equity)
            if tripped:
                res.kill_switch_tripped = True
                res.kill_switch_reason = self.risk.kill_reason
                await self._kill_switch_fired()
                # Flatten fills at the *next* bar open; keep replaying.
            self._prev_equity = equity
            res.equity_curve.append((bar.timestamp, equity))
            # 3. Strategy signals -> risk -> OMS.
            strategy_intents = self.strategy.on_bar(bar)
            for intent in strategy_intents:
                await self._route(intent)
            # Track exposure extremes from the live ledger.
            pos = self._net_position()
            res.max_position = max(res.max_position, pos)
            res.min_position = min(res.min_position, pos)
            if res.kill_switch_tripped and res.position_after_kill is None \
                    and not self.broker.has_pending:
                res.position_after_kill = pos
        # End of data: shutdown semantics — cancel anything still working.
        await self.oms.cancel_all()
        res.open_orders_at_end = len(self.oms.open_orders())
        res.final_position = self._net_position()
        res.final_equity = self._equity(self._last_price or 0.0)
        if res.kill_switch_tripped and res.position_after_kill is None:
            res.position_after_kill = res.final_position
        # Independent accounting cross-check: walk every recorded fill and
        # recompute cash PnL without the OMS ledger.
        res.accounting_error = abs(
            res.final_equity - self._replay_equity_from_fills())
        return res

    def _replay_equity_from_fills(self) -> float:
        """Recompute final equity from raw order history (no OMS ledger)."""
        cash = self.sim_cfg.initial_cash - self.broker.commissions_paid
        pos = 0
        cost = 0.0  # signed cost basis in points*units
        for mo in self.oms.orders.values():
            if mo.filled_quantity == 0:
                continue
            signed = (mo.filled_quantity
                      if mo.intent.signed_quantity > 0
                      else -mo.filled_quantity)
            cash -= self.sim_cfg.multiplier * signed * mo.avg_fill_price
            pos += signed
            cost += signed * mo.avg_fill_price
        mark = self._last_price or 0.0
        return cash + self.sim_cfg.multiplier * pos * mark


def bars_from_closes(
    closes: Sequence[float],
    symbol: str,
    timestamps: Optional[Sequence[datetime]] = None,
    spread_pct: float = 0.001,
) -> List[Bar]:
    """Build OHLC bars from a close series (open = previous close).

    Daily close data has no true intraday OHLC; the synthetic high/low adds
    a small symmetric range so bar validation holds. Fills only ever use
    the open (= previous real close), so no invented information leaks
    into execution prices.
    """
    out: List[Bar] = []
    t0 = datetime(2020, 1, 1, tzinfo=timezone.utc)
    prev = closes[0]
    for i, close in enumerate(closes):
        ts = (timestamps[i] if timestamps is not None
              else t0 + timedelta(days=i))
        o, c = float(prev), float(close)
        hi = max(o, c) * (1 + spread_pct)
        lo = min(o, c) * (1 - spread_pct)
        out.append(Bar(symbol=symbol, timestamp=ts, open=o, high=hi,
                       low=lo, close=c, volume=1_000.0))
        prev = close
    return out


def run_session(session: HistoricalSession,
                bars: Sequence[Bar]) -> SimResult:
    """Synchronous convenience wrapper."""
    return asyncio.run(session.run(bars))
