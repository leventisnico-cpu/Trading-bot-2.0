"""Thin typed wrapper over the ``MetaTrader5`` package (Windows-only).

The module is injected (``MT5Client(module=fake)``) so tests run anywhere; in
production it is imported lazily. Every call is retried on a ``None`` result
(the package's failure signal) and logged as one structured JSON line.

Times: MT5 stamps bars/ticks in the trade server's wall-clock encoded as if it
were UTC. ``server_tz`` (config ``mt5.server_timezone``) converts them to real
UTC. Verify on the demo: compare the latest M1 bar time with UTC now.

Holidays are not hand-maintained: ``symbol_tradeable`` asks the terminal
whether the symbol currently accepts orders and has a fresh quote.
"""

from __future__ import annotations

import importlib
import json
import logging
import time as _time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from ftmo_bot.strategy.base import Bar

log = logging.getLogger("ftmo_bot.mt5")
Side = Literal["long", "short"]

_TIMEFRAMES = {15: "TIMEFRAME_M15", 60: "TIMEFRAME_H1", 240: "TIMEFRAME_H4"}


class MT5Error(RuntimeError):
    pass


@dataclass(frozen=True)
class AccountSnapshot:
    login: int
    equity: float
    balance: float
    is_demo: bool


@dataclass(frozen=True)
class PositionInfo:
    ticket: int
    symbol: str
    side: Side
    volume: float
    price_open: float
    sl: float
    tp: float
    price_current: float
    profit: float
    magic: int
    comment: str
    opened_utc: datetime


@dataclass(frozen=True)
class TickInfo:
    ts_utc: datetime
    bid: float
    ask: float


@dataclass(frozen=True)
class OrderResult:
    ok: bool
    retcode: int
    ticket: int
    price: float
    comment: str


class MT5Client:
    def __init__(
        self,
        module: Any = None,
        server_tz: str = "UTC",
        retries: int = 3,
        retry_delay_s: float = 0.5,
        sleep: Callable[[float], None] = _time.sleep,
        deviation_points: int = 20,
    ) -> None:
        self.mt5 = module if module is not None else importlib.import_module("MetaTrader5")
        self.server_tz = ZoneInfo(server_tz)
        self.retries = retries
        self.retry_delay_s = retry_delay_s
        self._sleep = sleep
        self.deviation = deviation_points

    # ------------------------------------------------------------ plumbing

    def _log(self, event: str, **fields: Any) -> None:
        log.info(json.dumps({"event": event, **fields}, default=str))

    def _call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        fn = getattr(self.mt5, name)
        for attempt in range(self.retries + 1):
            result = fn(*args, **kwargs)
            if result is not None:
                return result
            err = self.mt5.last_error()
            self._log("mt5_retry", call=name, attempt=attempt, error=err)
            if attempt < self.retries:
                self._sleep(self.retry_delay_s * (2**attempt))
        raise MT5Error(f"{name} failed after {self.retries + 1} attempts: {self.mt5.last_error()}")

    def _server_to_utc(self, seconds: float) -> datetime:
        naive = datetime(1970, 1, 1) + timedelta(seconds=float(seconds))
        return naive.replace(tzinfo=self.server_tz).astimezone(UTC)

    # ------------------------------------------------------------ session

    def connect(self, login: int, password: str, server: str, path: str | None = None) -> None:
        kwargs: dict[str, Any] = {"login": login, "password": password, "server": server}
        if path:
            kwargs["path"] = path
        if not self.mt5.initialize(**kwargs):
            raise MT5Error(f"initialize failed: {self.mt5.last_error()}")
        self._log("connected", login=login, server=server)

    def shutdown(self) -> None:
        self.mt5.shutdown()

    # ------------------------------------------------------------ reads

    def account(self) -> AccountSnapshot:
        a = self._call("account_info")
        return AccountSnapshot(
            login=int(a.login),
            equity=float(a.equity),
            balance=float(a.balance),
            is_demo=int(a.trade_mode) == int(self.mt5.ACCOUNT_TRADE_MODE_DEMO),
        )

    def positions(self, symbol: str | None = None) -> list[PositionInfo]:
        raw = self._call("positions_get", symbol=symbol) if symbol else self._call("positions_get")
        return [
            PositionInfo(
                ticket=int(p.ticket),
                symbol=str(p.symbol),
                side="long" if int(p.type) == int(self.mt5.POSITION_TYPE_BUY) else "short",
                volume=float(p.volume),
                price_open=float(p.price_open),
                sl=float(p.sl),
                tp=float(p.tp),
                price_current=float(p.price_current),
                profit=float(p.profit),
                magic=int(p.magic),
                comment=str(p.comment),
                opened_utc=self._server_to_utc(p.time),
            )
            for p in raw
        ]

    def pending_orders(self) -> list[int]:
        return [int(o.ticket) for o in self._call("orders_get")]

    def tick(self, symbol: str) -> TickInfo:
        t = self._call("symbol_info_tick", symbol)
        return TickInfo(self._server_to_utc(t.time), float(t.bid), float(t.ask))

    def symbol_tradeable(
        self, symbol: str, now_utc: datetime, max_quote_age_s: float = 300
    ) -> bool:
        info = self.mt5.symbol_info(symbol)
        if info is None or int(info.trade_mode) != int(self.mt5.SYMBOL_TRADE_MODE_FULL):
            return False
        t = self.mt5.symbol_info_tick(symbol)
        if t is None:
            return False
        return (now_utc - self._server_to_utc(t.time)).total_seconds() <= max_quote_age_s

    def completed_bars(self, symbol: str, minutes: int, count: int) -> list[Bar]:
        """The last ``count`` COMPLETED bars (position 0, the forming bar, is skipped)."""
        tf = getattr(self.mt5, _TIMEFRAMES[minutes])
        rates = self._call("copy_rates_from_pos", symbol, tf, 1, count)
        return [
            Bar(
                symbol,
                self._server_to_utc(r["time"]),
                float(r["open"]),
                float(r["high"]),
                float(r["low"]),
                float(r["close"]),
                minutes,
            )
            for r in rates
        ]

    def closed_pnl(self, position_ticket: int) -> float | None:
        """Net P&L (profit + commission + swap) of a closed position, None if still open."""
        deals = self.mt5.history_deals_get(position=position_ticket)
        if not deals:
            return None
        out = [d for d in deals if int(d.entry) == int(self.mt5.DEAL_ENTRY_OUT)]
        if not out:
            return None
        return float(sum(float(d.profit) + float(d.commission) + float(d.swap) for d in deals))

    def deals_between(self, start_utc: datetime, end_utc: datetime) -> int:
        deals = self.mt5.history_deals_get(start_utc, end_utc)
        return (
            0
            if deals is None
            else sum(1 for d in deals if int(d.entry) == int(self.mt5.DEAL_ENTRY_IN))
        )

    # ------------------------------------------------------------ writes

    def _filling(self, symbol: str) -> int:
        info = self.mt5.symbol_info(symbol)
        mode = int(getattr(info, "filling_mode", 0)) if info is not None else 0
        if mode & 2:
            return int(self.mt5.ORDER_FILLING_IOC)
        if mode & 1:
            return int(self.mt5.ORDER_FILLING_FOK)
        return int(self.mt5.ORDER_FILLING_RETURN)

    def _send(self, request: dict[str, Any]) -> OrderResult:
        res = self.mt5.order_send(request)
        if res is None:
            out = OrderResult(False, -1, 0, 0.0, str(self.mt5.last_error()))
        else:
            ok = int(res.retcode) == int(self.mt5.TRADE_RETCODE_DONE)
            out = OrderResult(
                ok,
                int(res.retcode),
                int(getattr(res, "order", 0)),
                float(getattr(res, "price", 0.0)),
                str(getattr(res, "comment", "")),
            )
        self._log("order_send", request=request, result=out.__dict__)
        return out

    def market_order(
        self,
        symbol: str,
        side: Side,
        volume: float,
        sl: float,
        tp: float,
        magic: int,
        comment: str,
    ) -> OrderResult:
        """Market order with server-side SL and TP attached (never managed from Python)."""
        t = self.tick(symbol)
        return self._send(
            {
                "action": self.mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": self.mt5.ORDER_TYPE_BUY if side == "long" else self.mt5.ORDER_TYPE_SELL,
                "price": t.ask if side == "long" else t.bid,
                "sl": sl,
                "tp": tp,
                "deviation": self.deviation,
                "magic": magic,
                "comment": comment[:31],
                "type_time": self.mt5.ORDER_TIME_GTC,
                "type_filling": self._filling(symbol),
            }
        )

    def modify_sl(self, pos: PositionInfo, sl: float) -> OrderResult:
        return self._send(
            {
                "action": self.mt5.TRADE_ACTION_SLTP,
                "symbol": pos.symbol,
                "position": pos.ticket,
                "sl": sl,
                "tp": pos.tp,
            }
        )

    def close_position(self, pos: PositionInfo, comment: str = "flatten") -> OrderResult:
        t = self.tick(pos.symbol)
        return self._send(
            {
                "action": self.mt5.TRADE_ACTION_DEAL,
                "symbol": pos.symbol,
                "volume": pos.volume,
                "type": self.mt5.ORDER_TYPE_SELL if pos.side == "long" else self.mt5.ORDER_TYPE_BUY,
                "position": pos.ticket,
                "price": t.bid if pos.side == "long" else t.ask,
                "deviation": self.deviation,
                "magic": pos.magic,
                "comment": comment[:31],
                "type_time": self.mt5.ORDER_TIME_GTC,
                "type_filling": self._filling(pos.symbol),
            }
        )

    def cancel_order(self, ticket: int) -> OrderResult:
        return self._send({"action": self.mt5.TRADE_ACTION_REMOVE, "order": ticket})
