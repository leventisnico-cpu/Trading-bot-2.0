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
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ib_insync import (IB, BarDataList, ContFuture, Contract, Fill as IbFill,
                       Future, LimitOrder, MarketOrder, Stock, Trade)

from .core.config import AppConfig, ContractConfig
from .core.connection import IBConnectionManager
from .core.killfile import write_kill_marker
from .core.marketdata import request_market_data_type
from .core.types import (Bar, Fill, IntentSource, OrderIntent, OrderType,
                         utc_now)
from .execution.oms import ManagedOrder, OrderManagementSystem, OrderState
from .notify import TelegramConsole, TelegramNotifier, notifier_from_env
from .risk.event_calendar import BlackoutWindow, EventCalendar
from .risk.guardrails import PortfolioSnapshot, RiskGuardrails
from .strategy.adaptive_ema import AdaptiveEmaCrossoverStrategy
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


def kill_marker_path(cfg: AppConfig) -> Path:
    """The persistent kill-switch marker lives next to the execution log."""
    return Path(cfg.execution.execution_log_path).parent / "kill_switch.json"


async def run_preflight(cfg: AppConfig) -> List[Tuple[str, bool, str]]:
    """Read-only go/no-go check of the operator's IBKR setup.

    Connects (with a clientId offset so it never clashes with a running
    bot), qualifies the configured contract including front-month
    resolution and multiplier verification, pulls a small historical bar
    sample to prove market data entitlement, and reads account equity.
    Places no orders and subscribes to nothing persistent.

    Returns (check name, passed, detail) tuples; the caller renders them.
    """
    results: List[Tuple[str, bool, str]] = []
    c = cfg.connection
    paper = c.port in (7497, 4002)
    results.append(("port mode", True,
                    f"{c.port} = {'PAPER' if paper else 'LIVE — real money'}"))
    ib = IB()
    try:
        await asyncio.wait_for(
            ib.connectAsync(host=c.host, port=c.port,
                            clientId=c.client_id + 1,
                            account=c.account or "",
                            timeout=c.connect_timeout_s),
            timeout=c.connect_timeout_s + 5.0)
        results.append(("connect to TWS/Gateway", True,
                        f"{c.host}:{c.port} serverVersion="
                        f"{ib.client.serverVersion()} "
                        f"accounts={ib.managedAccounts()}"))
    except Exception as exc:
        results.append(("connect to TWS/Gateway", False,
                        f"{type(exc).__name__}: {exc} — is Gateway/TWS "
                        f"running with API enabled on this port?"))
        return results
    try:
        code = request_market_data_type(ib, c.market_data_type)
        results.append(("market data type", True,
                        f"{c.market_data_type} (reqMarketDataType {code})"))
    except Exception as exc:
        results.append(("market data type", False, str(exc)))
    try:
        contract = await qualify_tradeable_contract(
            ib, cfg.contract, build_contract(cfg.contract))
        results.append(("qualify contract", True,
                        f"{contract.symbol} "
                        f"{contract.lastTradeDateOrContractMonth or ''} "
                        f"conId={contract.conId} "
                        f"multiplier={contract.multiplier or '1'}".strip()))
    except Exception as exc:
        results.append(("qualify contract", False, str(exc)))
        ib.disconnect()
        return results
    try:
        bars = await asyncio.wait_for(ib.reqHistoricalDataAsync(
            contract, endDateTime="", durationStr="3600 S",
            barSizeSetting=cfg.strategy.bar_size, whatToShow="TRADES",
            useRTH=cfg.strategy.use_rth, formatDate=2), timeout=30.0)
        ok = bool(bars)
        results.append(("market data (historical bars)", ok,
                        f"{len(bars)} bars, last close "
                        f"{bars[-1].close}" if ok else
                        "no bars returned — check data subscription, or "
                        "set connection.market_data_type: delayed"))
    except Exception as exc:
        results.append(("market data (historical bars)", False,
                        f"{exc} — check market data subscriptions"))
    try:
        rows = await asyncio.wait_for(
            ib.accountSummaryAsync(c.account or ""), timeout=15.0)
        equity = next((r.value for r in rows
                       if r.tag == "NetLiquidation"), None)
        results.append(("account equity readable", equity is not None,
                        f"NetLiquidation={equity}" if equity is not None
                        else "NetLiquidation missing from account summary"))
    except Exception as exc:
        results.append(("account equity readable", False, str(exc)))
    ib.disconnect()
    return results


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


async def qualify_tradeable_contract(ib: IB, cfg: ContractConfig,
                                     contract: Contract) -> Contract:
    """Qualify ``contract``; resolve a continuous future to the tradeable
    front-month Future (ContFuture cannot take orders) and verify the
    configured multiplier against the venue's. Raises on any mismatch —
    trading with a wrong economic multiplier breaks every notional cap."""
    qualified = await ib.qualifyContractsAsync(contract)
    if not qualified:
        raise RuntimeError(f"could not qualify contract {cfg.symbol}")
    if isinstance(contract, ContFuture):
        front = Future(conId=contract.conId, exchange=cfg.exchange)
        if not await ib.qualifyContractsAsync(front):
            raise RuntimeError(
                f"could not resolve front-month future for {cfg.symbol}")
        log.info("resolved front month: %s %s (conId=%d, mult=%s)",
                 front.symbol, front.lastTradeDateOrContractMonth,
                 front.conId, front.multiplier)
        contract = front
    if contract.secType == "FUT" and contract.multiplier:
        venue_mult = float(contract.multiplier)
        if abs(venue_mult - cfg.multiplier) > 1e-9:
            raise RuntimeError(
                f"configured contract.multiplier {cfg.multiplier} does not "
                f"match the venue's {venue_mult} for {contract.symbol} — "
                f"fix config.yaml before trading")
    return contract


def build_strategy(cfg: AppConfig) -> BaseStrategy:
    """Strategy factory keyed on ``strategy.name`` in config.yaml."""
    s = cfg.strategy
    if s.name == "ema_crossover":
        return EmaCrossoverStrategy(
            symbol=cfg.contract.symbol,
            fast_period=s.fast_period,
            slow_period=s.slow_period,
            order_quantity=s.order_quantity,
            warmup_bars=s.warmup_bars,
        )
    if s.name == "adaptive_ema":
        return AdaptiveEmaCrossoverStrategy(
            symbol=cfg.contract.symbol,
            fast_period=s.fast_period,
            slow_period=s.slow_period,
            base_quantity=s.order_quantity,
            warmup_bars=s.warmup_bars,
            vol_fast_period=s.vol_fast_period,
            vol_slow_period=s.vol_slow_period,
            high_vol_ratio=s.high_vol_ratio,
            extreme_vol_ratio=s.extreme_vol_ratio,
            confirm_window=s.confirm_window,
            learn=s.learn,
            risk_per_trade=s.risk_per_trade,
            multiplier=cfg.contract.multiplier,
        )
    raise ValueError(f"unknown strategy {s.name!r}")


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
        self._setup_lock = asyncio.Lock()
        self.calendar = self._load_calendar(cfg)
        self.notifier: Optional[TelegramNotifier] = None
        self.console: Optional[TelegramConsole] = None
        self._console_task: Optional[asyncio.Task[None]] = None
        self._last_equity: Optional[float] = None
        if cfg.notifications.enabled:
            self.notifier = notifier_from_env(
                cfg.notifications.bot_token_env,
                cfg.notifications.chat_id_env)
            if self.notifier is not None and cfg.notifications.commands_enabled:
                self.console = TelegramConsole(
                    self.notifier, self.notifier._transport,
                    handlers={"/status": self.status_text,
                              "/positions": self.positions_text,
                              "/orders": self.orders_text})

    # ------------------------------------------------------ notifications

    def notify(self, text: str) -> None:
        """Fire-and-forget operator alert; never blocks the trading loop."""
        if self.notifier is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.notifier.send(text)
            return
        loop.run_in_executor(None, self.notifier.send, text)

    def status_text(self) -> str:
        """Reply for /status (also logged at each state change)."""
        c = self.cfg.connection
        mode = "PAPER" if c.port in (7497, 4002) else "LIVE"
        pos = self.oms.position_quantities().get(self.cfg.contract.symbol, 0)
        lines = [
            f"Mini-Prop OS [{mode} :{c.port}] {self.strategy.strategy_id} "
            f"{self.cfg.contract.symbol}",
            f"connected: {self.conn.is_connected}  "
            f"trading: {'enabled' if self._trading_enabled.is_set() else 'DISABLED'}",
            f"position: {pos:+d}  last: "
            f"{self._last_price if self._last_price is not None else '-'}  "
            f"bar: {self._last_bar_time.isoformat() if self._last_bar_time else '-'}",
            f"equity: {self._last_equity if self._last_equity is not None else '-'}"
            f"  start-of-day: {self.risk.start_of_day_equity}",
            f"kill switch: "
            f"{'TRIPPED — ' + self.risk.kill_reason if self.risk.kill_switch_active else 'clear'}",
            f"working orders: {len(self.oms.open_orders())}",
        ]
        regime = getattr(self.strategy, "regime", None)
        if regime is not None:
            lines.append(f"regime: {getattr(regime, 'value', regime)}")
        return "\n".join(lines)

    def positions_text(self) -> str:
        book = self.oms.positions
        if not book:
            return "book flat"
        return "\n".join(
            f"{sym}: {p.quantity:+d} @ {p.avg_price:.4f} "
            f"realized {p.realized_pnl:+.2f}" for sym, p in book.items())

    def orders_text(self) -> str:
        orders = self.oms.open_orders()
        if not orders:
            return "no working orders"
        return "\n".join(
            f"#{o.order_id} {o.intent.action.value} {o.intent.quantity} "
            f"{o.intent.symbol} {o.state.value} filled {o.filled_quantity}"
            for o in orders)

    async def _console_loop(self) -> None:
        assert self.console is not None
        interval = self.cfg.notifications.poll_interval_s
        while True:
            try:
                await asyncio.to_thread(self.console.poll_once)
            except Exception:
                log.exception("telegram console poll failed")
            await asyncio.sleep(interval)

    @staticmethod
    def _load_calendar(cfg: AppConfig) -> Optional[EventCalendar]:
        """Load the economic-event calendar, if one is configured."""
        if not cfg.risk.event_calendar_path:
            return None
        before = cfg.risk.blackout_minutes_before
        after = cfg.risk.blackout_minutes_after
        window = BlackoutWindow(
            high_before_minutes=before, high_after_minutes=after,
            medium_before_minutes=before / 3.0,
            medium_after_minutes=after / 3.0)
        return EventCalendar.from_file(cfg.risk.event_calendar_path, window)

    def _is_entry(self, intent: OrderIntent) -> bool:
        """True when the intent increases exposure rather than reducing it."""
        current = self.oms.position_quantities().get(intent.symbol, 0)
        return abs(current + intent.signed_quantity) > abs(current)

    def _blackout_block(self, intent: OrderIntent) -> Optional[str]:
        """Reason to suppress this intent for a scheduled event, or None.

        Only strategy-sourced *entries* are ever blocked: exits, risk
        flattening, and operator orders must always get through — being
        unable to leave a position during a release is the risk the
        blackout exists to avoid.
        """
        if self.calendar is None or len(self.calendar) == 0:
            return None
        if intent.source is not IntentSource.STRATEGY:
            return None
        if not self._is_entry(intent):
            return None
        event = self.calendar.active_event(utc_now())
        if event is None:
            return None
        return (f"scheduled {event.impact.value}-impact event "
                f"{event.name!r} at {event.timestamp.isoformat()}")

    # ------------------------------------------------------------- public

    async def run(self) -> None:
        """Connect, prime, then serve events until shutdown is requested."""
        await self.conn.start()
        self._equity_task = asyncio.create_task(
            self._equity_monitor(), name="equity-monitor")
        if self.console is not None:
            self._console_task = asyncio.create_task(
                self._console_loop(), name="telegram-console")
        log.info("Mini-Prop OS running: %s %s on %s:%d",
                 self.strategy.strategy_id, self.cfg.contract.symbol,
                 self.cfg.connection.host, self.cfg.connection.port)
        self.notify("started: " + self.status_text())
        await self._shutdown_evt.wait()

    def request_shutdown(self) -> None:
        """Signal-handler-safe shutdown request."""
        self._shutdown_evt.set()

    async def shutdown(self) -> None:
        """Cancel working orders, optionally flatten, then disconnect."""
        log.info("shutting down...")
        self._trading_enabled.clear()
        for task in (self._equity_task, self._console_task):
            if task is None:
                continue
            task.cancel()
            try:
                await task
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
        if self.notifier is not None:
            self.notifier.send("stopped: " + self.status_text())

    # ------------------------------------------------- connection callbacks

    async def _on_connected(self) -> None:
        """(Re)establish contract, equity baseline, broker reconciliation,
        and the live bar subscription. Trading is enabled only when every
        step succeeds; failures leave it disabled and the equity monitor
        retries the whole setup on its next tick."""
        async with self._setup_lock:
            if self._trading_enabled.is_set() or self.risk.kill_switch_active:
                return
            try:
                request_market_data_type(
                    self.conn.ib, self.cfg.connection.market_data_type)
                await self._qualify_contract()
                if self.risk.start_of_day_equity is None:
                    equity = await self._mark_equity(start_of_day=True)
                    if equity is None:
                        raise RuntimeError(
                            "cannot read account equity — the daily-loss "
                            "breaker would have no baseline")
                await self._reconcile_broker_state()
                await self._subscribe_bars()
                self._trading_enabled.set()
                log.info("trading enabled")
                self.notify("trading enabled: " + self.status_text())
            except Exception as exc:
                log.exception(
                    "post-connect setup failed; trading stays disabled "
                    "(retrying on the next equity-monitor tick)")
                self.notify(f"setup failed, trading disabled: {exc}")

    async def _reconcile_broker_state(self) -> None:
        """Align the OMS ledger with the broker before any order can route.

        * A cold start with an existing position in the account imports it
          into the ledger (risk caps and kill-switch flattening then cover
          the real book).
        * A mismatch on a warm ledger (fills that happened while
          disconnected) is unexplained state: halt for operator review
          rather than trade against a wrong book.
        * Working orders on our contract that the OMS does not know are
          cancelled — a stateless restart must start from a clean slate.
        """
        ib = self.conn.ib
        symbol = self.cfg.contract.symbol
        mult = self.cfg.contract.multiplier or 1.0
        broker_qty = 0
        broker_avg = 0.0
        for pos in await ib.reqPositionsAsync():
            if (pos.contract.symbol == symbol
                    and pos.contract.secType == self.cfg.contract.sec_type
                    and pos.position):
                broker_qty += int(pos.position)
                broker_avg = float(pos.avgCost) / mult
        oms_qty = self.oms.position_quantities().get(symbol, 0)
        if broker_qty != oms_qty:
            if oms_qty == 0 and not self.oms.orders:
                self.oms.seed_position(symbol, broker_qty, broker_avg)
                log.warning("imported existing broker position at startup: "
                            "%+d %s @ %.4f", broker_qty, symbol, broker_avg)
            else:
                await self._halt(
                    f"position reconciliation mismatch for {symbol}: "
                    f"broker={broker_qty} ledger={oms_qty} — fills may have "
                    f"occurred while disconnected")
                raise RuntimeError("position reconciliation mismatch")
        for trade in await ib.reqAllOpenOrdersAsync():
            if trade.contract.symbol != symbol:
                continue
            oid = trade.order.orderId
            mo = self.oms.get(oid)
            if mo is None or mo.is_terminal:
                log.warning("cancelling unmanaged working order %d "
                            "(%s %s %s)", oid, trade.order.action,
                            trade.order.totalQuantity, symbol)
                ib.cancelOrder(trade.order)

    async def _qualify_contract(self) -> None:
        self.contract = await qualify_tradeable_contract(
            self.conn.ib, self.cfg.contract, self.contract)
        self.broker.set_contract(self.contract)

    async def _on_disconnected(self) -> None:
        self._trading_enabled.clear()
        self._bars = None
        log.warning("trading disabled until reconnect completes")

    # ------------------------------------------------------- market data

    async def _subscribe_bars(self) -> None:
        """Historical warmup + live keep-up-to-date bars in one request."""
        if self._bars is not None:
            return  # already subscribed on this connection (setup retry)
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
        except Exception as exc:
            log.exception("strategy failed on bar %s; halting via kill "
                          "switch", bar.timestamp)
            await self._halt(f"strategy exception: {exc}")
            return
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
        blackout = self._blackout_block(intent)
        if blackout is not None:
            log.info("BLACKOUT [%s %d %s]: %s", intent.action.value,
                     intent.quantity, intent.symbol, blackout)
            return
        snapshot = self._snapshot()
        decision = self.risk.validate(intent, snapshot)
        if not decision.approved:
            log.warning("RISK REJECT [%s %d %s]: %s", intent.action.value,
                        intent.quantity, intent.symbol, decision.reason)
            self.notify(f"RISK REJECT {intent.action.value} {intent.quantity} "
                        f"{intent.symbol}: {decision.reason}")
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
        pos = self.oms.position_quantities().get(fill.symbol, 0)
        self.notify(f"FILL {order.intent.action.value} "
                    f"{abs(fill.signed_quantity)} {fill.symbol} @ {fill.price} "
                    f"(order #{order.order_id}, {order.state.value}) "
                    f"position {pos:+d} — {order.intent.reason}")

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
                self._last_equity = equity
                if start_of_day:
                    self.risk.mark_start_of_day(equity)
                return equity
        log.warning("NetLiquidation not present in account summary")
        return None

    async def _equity_monitor(self) -> None:
        """Poll equity, enforce the daily-loss circuit breaker, and retry
        incomplete post-connect setup."""
        while True:
            await asyncio.sleep(30.0)
            if not self.conn.is_connected:
                continue
            if (not self._trading_enabled.is_set()
                    and not self.risk.kill_switch_active):
                await self._on_connected()  # retry failed setup
                continue
            equity = await self._mark_equity(start_of_day=False)
            if equity is None:
                continue
            tripped = self.risk.update_equity(equity)
            if tripped:
                await self._kill_switch_fired()

    async def _halt(self, reason: str) -> None:
        """Single halt path: trip the kill switch, persist the marker,
        cancel working orders, and flatten (per config)."""
        self.risk.trip(reason)
        await self._kill_switch_fired()

    async def _kill_switch_fired(self) -> None:
        """Cancel everything, flatten the book, persist the halt (once)."""
        if self._flattening:
            return
        self._flattening = True
        log.critical("kill switch fired: cancelling all orders and "
                     "flattening all positions")
        self.notify("KILL SWITCH: " + (self.risk.kill_reason or "fired")
                    + " — cancelling orders"
                    + (" and flattening" if self.cfg.risk.kill_switch_flattens
                       else ""))
        # Persist first: even if flattening errors, a restart must not
        # resume trading until an operator clears the marker.
        write_kill_marker(kill_marker_path(self.cfg),
                          self.risk.kill_reason or "kill switch fired")
        try:
            await self.oms.cancel_all()
            if self.cfg.risk.kill_switch_flattens:
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
