"""Application layer: wires ib_insync to the pure strategy/risk/OMS core.

Contains the ib_insync :class:`BrokerAdapter` implementation, the market
data pipeline (historical warmup + live keep-up-to-date bars), the equity
monitor that feeds the daily-loss circuit breaker, and the
:class:`TradingApp` orchestrator used by ``main.py``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from ib_insync import (IB, BarDataList, ContFuture, Contract, Fill as IbFill,
                       Future, LimitOrder, MarketOrder, Stock, Trade)

from .core.config import AppConfig, ContractConfig
from .core.connection import IBConnectionManager
from .core.types import Bar, Fill, OrderIntent, OrderType
from .execution.oms import ManagedOrder, OrderManagementSystem, OrderState
from .risk.guardrails import PortfolioSnapshot, RiskGuardrails
from .strategy.base import BaseStrategy
from .strategy.ema_crossover import EmaCrossoverStrategy

log = logging.getLogger(__name__)

#: ib_insync order statuses mapped to OMS states handled via on_order_status.
_STATUS_MAP: Dict[str, OrderState] = {
    "PendingSubmit": OrderState.SUBMITTED,
    "PreSubmitted": OrderState.SUBMITTED,
    "Submitted": OrderState.SUBMITTED,
    "ApiCancelled": OrderState.CANCELLED,
    "Cancelled": OrderState.CANCELLED,
    "Inactive": OrderState.REJECTED,
}


class IbBrokerAdapter:
    """BrokerAdapter backed by ib_insync; also relays trade events to the OMS."""

    def __init__(self, ib: IB, contract: Contract) -> None:
        self._ib = ib
        self._contract = contract
        self._trades: Dict[int, Trade] = {}
        self.oms: Optional[OrderManagementSystem] = None

    def set_contract(self, contract: Contract) -> None:
        """Swap the qualified contract (e.g. resolved front-month future)."""
        self._contract = contract

    async def place_order(self, intent: OrderIntent) -> int:
        """Translate an approved intent to an IBKR order and transmit it."""
        if intent.symbol != self._contract.symbol:
            raise ValueError(
                f"intent symbol {intent.symbol!r} does not match qualified "
                f"contract {self._contract.symbol!r}")
        if intent.order_type is OrderType.LIMIT:
            assert intent.limit_price is not None  # risk layer guarantees
            order = LimitOrder(intent.action.value, intent.quantity,
                               intent.limit_price)
        else:
            order = MarketOrder(intent.action.value, intent.quantity)
        order.tif = "DAY"
        trade = self._ib.placeOrder(self._contract, order)
        order_id = trade.order.orderId
        self._trades[order_id] = trade
        trade.statusEvent += self._on_trade_status
        trade.fillEvent += self._on_trade_fill
        log.info("transmitted order %d: %s %d %s %s", order_id,
                 intent.action.value, intent.quantity, intent.symbol,
                 intent.order_type.value)
        return order_id

    async def cancel_order(self, order_id: int) -> None:
        trade = self._trades.get(order_id)
        if trade is None:
            log.warning("cancel: no trade recorded for order %d", order_id)
            return
        self._ib.cancelOrder(trade.order)

    # --------------------------------------------------- ib_insync events

    def _on_trade_status(self, trade: Trade) -> None:
        if self.oms is None:
            return
        status = trade.orderStatus.status
        mapped = _STATUS_MAP.get(status)
        if mapped is None:
            log.debug("order %d status %s (no OMS mapping, fills carry it)",
                      trade.order.orderId, status)
            return
        self.oms.on_order_status(trade.order.orderId, mapped)

    def _on_trade_fill(self, trade: Trade, fill: IbFill) -> None:
        if self.oms is None:
            return
        side = 1 if fill.execution.side == "BOT" else -1
        self.oms.on_fill(Fill(
            order_id=trade.order.orderId,
            symbol=trade.contract.symbol,
            signed_quantity=side * int(fill.execution.shares),
            price=float(fill.execution.price),
            timestamp=fill.time or datetime.now(timezone.utc),
            exec_id=fill.execution.execId,
        ))


def build_contract(cfg: ContractConfig) -> Contract:
    """Translate the contract config into an ib_insync contract.

    For futures with no explicit expiry this returns a :class:`ContFuture`;
    the app resolves it to the tradeable front-month :class:`Future` at
    connect time (orders cannot be placed against a continuous future).
    """
    if cfg.sec_type == "STK":
        return Stock(cfg.symbol, cfg.exchange, cfg.currency)
    if cfg.sec_type == "FUT":
        if cfg.last_trade_date:
            return Future(cfg.symbol,
                          lastTradeDateOrContractMonth=cfg.last_trade_date,
                          exchange=cfg.exchange, currency=cfg.currency)
        return ContFuture(cfg.symbol, exchange=cfg.exchange,
                          currency=cfg.currency)
    raise ValueError(f"unsupported sec_type {cfg.sec_type!r}")


def build_strategy(cfg: AppConfig) -> BaseStrategy:
    """Strategy factory keyed on ``strategy.name`` in config.yaml."""
    if cfg.strategy.name == "ema_crossover":
        return EmaCrossoverStrategy(
            symbol=cfg.contract.symbol,
            fast_period=cfg.strategy.fast_period,
            slow_period=cfg.strategy.slow_period,
            order_quantity=cfg.strategy.order_quantity,
            warmup_bars=cfg.strategy.warmup_bars,
        )
    raise ValueError(f"unknown strategy {cfg.strategy.name!r}")


class TradingApp:
    """Owns the full trading lifecycle for one contract + one strategy."""

    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self.conn = IBConnectionManager(
            cfg.connection,
            on_connected=self._on_connected,
            on_disconnected=self._on_disconnected,
        )
        self.risk = RiskGuardrails(cfg.risk)
        self.strategy = build_strategy(cfg)
        self.contract: Contract = build_contract(cfg.contract)
        self.broker = IbBrokerAdapter(self.conn.ib, self.contract)
        self.oms = OrderManagementSystem(
            self.broker,
            execution_log_path=cfg.execution.execution_log_path,
            on_fill=self._on_oms_fill,
        )
        self.broker.oms = self.oms
        self._bars: Optional[BarDataList] = None
        self._last_bar_time: Optional[datetime] = None
        self._last_price: Optional[float] = None
        self._equity_task: Optional[asyncio.Task[None]] = None
        self._trading_enabled = asyncio.Event()
        self._shutdown_evt = asyncio.Event()
        self._flattening = False

    # ------------------------------------------------------------- public

    async def run(self) -> None:
        """Connect, prime, then serve events until shutdown is requested."""
        await self.conn.start()
        self._equity_task = asyncio.create_task(
            self._equity_monitor(), name="equity-monitor")
        log.info("Mini-Prop OS running: %s %s on %s:%d",
                 self.strategy.strategy_id, self.cfg.contract.symbol,
                 self.cfg.connection.host, self.cfg.connection.port)
        await self._shutdown_evt.wait()

    def request_shutdown(self) -> None:
        """Signal-handler-safe shutdown request."""
        self._shutdown_evt.set()

    async def shutdown(self) -> None:
        """Cancel working orders, optionally flatten, then disconnect."""
        log.info("shutting down...")
        self._trading_enabled.clear()
        if self._equity_task is not None:
            self._equity_task.cancel()
            try:
                await self._equity_task
            except (asyncio.CancelledError, Exception):
                pass
        try:
            if self.conn.is_connected:
                if self.cfg.execution.cancel_on_shutdown:
                    n = await self.oms.cancel_all()
                    if n:
                        log.info("requested cancel of %d working order(s)", n)
                        await asyncio.sleep(2.0)  # let cancels acknowledge
                if self.cfg.execution.flatten_on_shutdown:
                    await self._flatten_all("shutdown flatten")
                    await asyncio.sleep(2.0)  # let market orders fill
        except Exception:
            log.exception("error during shutdown order handling")
        finally:
            await self.conn.stop()
        open_orders = self.oms.open_orders()
        if open_orders:
            log.warning("%d order(s) not confirmed terminal at exit: %s",
                        len(open_orders),
                        [(o.order_id, o.state.value) for o in open_orders])
        log.info("shutdown complete")

    # ------------------------------------------------- connection callbacks

    async def _on_connected(self) -> None:
        """(Re)establish contract, warmup data, and live bar subscription."""
        try:
            await self._qualify_contract()
            await self._mark_equity(start_of_day=(
                self.risk.start_of_day_equity is None))
            await self._subscribe_bars()
            self._trading_enabled.set()
        except Exception:
            log.exception("post-connect setup failed; trading stays disabled")

    async def _qualify_contract(self) -> None:
        """Qualify the configured contract; resolve a continuous future to
        the tradeable front-month Future (ContFuture cannot take orders)."""
        ib = self.conn.ib
        qualified = await ib.qualifyContractsAsync(self.contract)
        if not qualified:
            raise RuntimeError(
                f"could not qualify contract {self.cfg.contract.symbol}")
        if isinstance(self.contract, ContFuture):
            front = Future(conId=self.contract.conId,
                           exchange=self.cfg.contract.exchange)
            if not await ib.qualifyContractsAsync(front):
                raise RuntimeError(
                    f"could not resolve front-month future for "
                    f"{self.cfg.contract.symbol}")
            self.contract = front
            self.broker.set_contract(front)
            log.info("resolved front month: %s %s (conId=%d, mult=%s)",
                     front.symbol, front.lastTradeDateOrContractMonth,
                     front.conId, front.multiplier)
        if self.contract.secType == "FUT" and self.contract.multiplier:
            venue_mult = float(self.contract.multiplier)
            if abs(venue_mult - self.cfg.contract.multiplier) > 1e-9:
                # Never trade with a wrong economic multiplier: all notional
                # risk caps depend on it.
                raise RuntimeError(
                    f"configured contract.multiplier "
                    f"{self.cfg.contract.multiplier} does not match the "
                    f"venue's {venue_mult} for {self.contract.symbol} — fix "
                    f"config.yaml before trading")

    async def _on_disconnected(self) -> None:
        self._trading_enabled.clear()
        self._bars = None
        log.warning("trading disabled until reconnect completes")

    # ------------------------------------------------------- market data

    async def _subscribe_bars(self) -> None:
        """Historical warmup + live keep-up-to-date bars in one request."""
        ib = self.conn.ib
        bars = await ib.reqHistoricalDataAsync(
            self.contract,
            endDateTime="",
            durationStr="2 D",
            barSizeSetting=self.cfg.strategy.bar_size,
            whatToShow="TRADES",
            useRTH=self.cfg.strategy.use_rth,
            formatDate=2,
            keepUpToDate=True,
        )
        self._bars = bars
        history = [self._to_bar(b) for b in bars[:-1]] if len(bars) > 1 else []
        if self._last_bar_time is not None:
            # Reconnect: feed only the bars we missed while disconnected, as
            # warmup (indicators stay continuous, no trading on stale bars).
            missed = [b for b in history if b.timestamp > self._last_bar_time]
            if missed:
                self.strategy.prime(missed)
                log.info("primed %d bar(s) missed during disconnect",
                         len(missed))
                self._last_bar_time = missed[-1].timestamp
                self._last_price = missed[-1].close
        elif history:
            self.strategy.prime(history)
            self._last_bar_time = history[-1].timestamp
            self._last_price = history[-1].close
        bars.updateEvent += self._on_bar_update
        log.info("subscribed to %s bars for %s (useRTH=%s, %d warmup bars)",
                 self.cfg.strategy.bar_size, self.cfg.contract.symbol,
                 self.cfg.strategy.use_rth, len(history))

    @staticmethod
    def _to_bar(b: object) -> Bar:
        ts = b.date  # type: ignore[attr-defined]
        if not isinstance(ts, datetime):
            ts = datetime(ts.year, ts.month, ts.day, tzinfo=timezone.utc)
        return Bar(
            symbol="", timestamp=ts,
            open=float(b.open), high=float(b.high),  # type: ignore[attr-defined]
            low=float(b.low), close=float(b.close),  # type: ignore[attr-defined]
            volume=float(b.volume),  # type: ignore[attr-defined]
        )

    def _on_bar_update(self, bars: BarDataList, has_new_bar: bool) -> None:
        """ib_insync callback: fires on every tick; act only on completed bars.

        With keepUpToDate, ``bars[-1]`` is the forming bar; when
        ``has_new_bar`` is true the previous bar just completed.
        """
        if not has_new_bar or len(bars) < 2:
            return
        completed = bars[-2]
        try:
            raw = self._to_bar(completed)
            if (self._last_bar_time is not None
                    and raw.timestamp <= self._last_bar_time):
                return  # duplicate after resubscribe
            bar = Bar(symbol=self.cfg.contract.symbol,
                      timestamp=raw.timestamp, open=raw.open, high=raw.high,
                      low=raw.low, close=raw.close, volume=raw.volume)
        except (ValueError, AttributeError) as exc:
            # A glitchy bar from the feed must not blow up inside the
            # ib_insync event dispatch — skip it and keep the stream alive.
            log.error("skipping corrupt bar at %r: %s",
                      getattr(completed, "date", None), exc)
            return
        self._last_bar_time = bar.timestamp
        self._last_price = bar.close
        asyncio.ensure_future(self._process_bar(bar))

    async def _process_bar(self, bar: Bar) -> None:
        """Strategy -> risk -> OMS pipeline for one completed bar."""
        if not self._trading_enabled.is_set():
            return
        try:
            intents = self.strategy.on_bar(bar)
        except Exception:
            log.exception("strategy failed on bar %s; halting via kill switch",
                          bar.timestamp)
            self.risk.trip("strategy exception")
            intents = []
        for intent in intents:
            await self._route_intent(intent)

    # -------------------------------------------------------- order routing

    def _snapshot(self) -> PortfolioSnapshot:
        sym = self.cfg.contract.symbol
        return PortfolioSnapshot(
            positions=self.oms.position_quantities(),
            last_prices={sym: self._last_price or 0.0},
            multipliers={sym: self.cfg.contract.multiplier},
        )

    async def _route_intent(self, intent: OrderIntent) -> None:
        snapshot = self._snapshot()
        decision = self.risk.validate(intent, snapshot)
        if not decision.approved:
            log.warning("RISK REJECT [%s %d %s]: %s", intent.action.value,
                        intent.quantity, intent.symbol, decision.reason)
            return
        try:
            await self.oms.submit(intent)
        except Exception:
            log.exception("order submission failed for intent %d",
                          intent.intent_id)

    def _on_oms_fill(self, fill: Fill, order: ManagedOrder) -> None:
        """Feed fills back to the strategy that originated the order."""
        if order.intent.strategy_id == self.strategy.strategy_id:
            signed = (abs(fill.signed_quantity)
                      if order.intent.signed_quantity > 0
                      else -abs(fill.signed_quantity))
            self.strategy.on_own_fill(signed, fill.price)

    # ---------------------------------------------------- equity / killing

    async def _mark_equity(self, start_of_day: bool) -> Optional[float]:
        """Read NetLiquidation from account summary."""
        ib = self.conn.ib
        try:
            rows = await asyncio.wait_for(
                ib.accountSummaryAsync(self.cfg.connection.account or ""),
                timeout=15.0)
        except (asyncio.TimeoutError, Exception) as exc:
            log.warning("account summary unavailable: %s", exc)
            return None
        for row in rows:
            if row.tag == "NetLiquidation":
                equity = float(row.value)
                if start_of_day:
                    self.risk.mark_start_of_day(equity)
                return equity
        log.warning("NetLiquidation not present in account summary")
        return None

    async def _equity_monitor(self) -> None:
        """Poll equity and enforce the daily-loss circuit breaker."""
        while True:
            await asyncio.sleep(30.0)
            if not self.conn.is_connected:
                continue
            equity = await self._mark_equity(start_of_day=False)
            if equity is None:
                continue
            tripped = self.risk.update_equity(equity)
            if tripped and self.cfg.risk.kill_switch_flattens:
                await self._kill_switch_fired()

    async def _kill_switch_fired(self) -> None:
        """Cancel everything and flatten the book (once)."""
        if self._flattening:
            return
        self._flattening = True
        log.critical("kill switch fired: cancelling all orders and "
                     "flattening all positions")
        try:
            await self.oms.cancel_all()
            await self._flatten_all("kill switch")
        except Exception:
            log.exception("error while flattening after kill switch")

    async def _flatten_all(self, why: str) -> None:
        positions = self.oms.position_quantities()
        if not positions:
            log.info("flatten (%s): book already flat", why)
            return
        for intent in self.risk.flatten_intents(positions):
            decision = self.risk.validate(intent, self._snapshot())
            if not decision.approved:
                log.error("flatten intent rejected (%s) — manual "
                          "intervention required", decision.reason)
                continue
            try:
                await self.oms.submit(intent)
            except Exception:
                log.exception("failed submitting flatten order for %s",
                              intent.symbol)
