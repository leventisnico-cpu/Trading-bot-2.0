"""In-memory stand-in for the ``MetaTrader5`` package (enough for our client)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import numpy as np

RATE_DTYPE = np.dtype(
    [
        ("time", "<i8"),
        ("open", "<f8"),
        ("high", "<f8"),
        ("low", "<f8"),
        ("close", "<f8"),
        ("tick_volume", "<i8"),
        ("spread", "<i4"),
        ("real_volume", "<i8"),
    ]
)


@dataclass
class FakePosition:
    ticket: int
    symbol: str
    type: int
    volume: float
    price_open: float
    sl: float
    tp: float
    price_current: float
    magic: int
    comment: str
    time: int = 0
    profit: float = 0.0


@dataclass
class FakeMT5:
    """Server time == UTC unless ``server_offset_s`` is set."""

    equity: float = 100_000.0
    balance: float = 100_000.0
    trade_mode: int = 0  # demo
    bid: dict[str, float] = field(default_factory=dict)
    spread: float = 0.0001
    now: datetime = datetime(2026, 3, 4, 8, 0, tzinfo=UTC)
    positions: list[FakePosition] = field(default_factory=list)
    pending: list[int] = field(default_factory=list)
    rates: dict[tuple[str, int], np.ndarray] = field(default_factory=dict)
    deals: list[SimpleNamespace] = field(default_factory=list)
    sent: list[dict[str, Any]] = field(default_factory=list)
    fail_account: bool = False
    reject_orders: bool = False
    _next_ticket: int = 1000

    # constants
    ACCOUNT_TRADE_MODE_DEMO = 0
    POSITION_TYPE_BUY = 0
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    TRADE_ACTION_DEAL = 1
    TRADE_ACTION_SLTP = 6
    TRADE_ACTION_REMOVE = 8
    TRADE_RETCODE_DONE = 10009
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    SYMBOL_TRADE_MODE_FULL = 4
    DEAL_ENTRY_IN = 0
    DEAL_ENTRY_OUT = 1
    TIMEFRAME_M15 = 15
    TIMEFRAME_H1 = 16385
    TIMEFRAME_H4 = 16388

    def initialize(self, **kw: Any) -> bool:
        return True

    def shutdown(self) -> None:
        pass

    def last_error(self) -> tuple[int, str]:
        return (1, "fake error")

    def account_info(self) -> SimpleNamespace | None:
        if self.fail_account:
            return None
        return SimpleNamespace(
            login=1, equity=self.equity, balance=self.balance, trade_mode=self.trade_mode
        )

    def positions_get(self, symbol: str | None = None) -> tuple[FakePosition, ...]:
        for p in self.positions:
            b = self.bid.get(p.symbol, p.price_current)
            p.price_current = b if p.type == 0 else b + self.spread
        return tuple(p for p in self.positions if symbol is None or p.symbol == symbol)

    def orders_get(self) -> tuple[SimpleNamespace, ...]:
        return tuple(SimpleNamespace(ticket=t) for t in self.pending)

    def symbol_info_tick(self, symbol: str) -> SimpleNamespace:
        b = self.bid.get(symbol, 1.1)
        return SimpleNamespace(time=int(self.now.timestamp()), bid=b, ask=b + self.spread)

    def symbol_info(self, symbol: str) -> SimpleNamespace:
        return SimpleNamespace(trade_mode=4, filling_mode=2)

    def copy_rates_from_pos(self, symbol: str, tf: int, start: int, count: int) -> np.ndarray:
        arr = self.rates.get((symbol, tf), np.zeros(0, RATE_DTYPE))
        cutoff = int(self.now.timestamp())
        minutes = 15 if tf == 15 else 240
        done = arr[arr["time"] + minutes * 60 <= cutoff]
        return done[-count:]

    def history_deals_get(self, *args: Any, position: int | None = None) -> tuple[Any, ...]:
        if position is not None:
            return tuple(d for d in self.deals if d.position_id == position)
        return tuple(self.deals)

    def order_send(self, req: dict[str, Any]) -> SimpleNamespace:
        self.sent.append(req)
        if self.reject_orders:
            return SimpleNamespace(retcode=10013, order=0, price=0.0, comment="rejected")
        action = req["action"]
        if action == self.TRADE_ACTION_DEAL and "position" in req:
            pos = next(p for p in self.positions if p.ticket == req["position"])
            self.positions.remove(pos)
            self.deals.append(
                SimpleNamespace(
                    position_id=pos.ticket, entry=1, profit=-1.0, commission=0.0, swap=0.0
                )
            )
            return SimpleNamespace(
                retcode=self.TRADE_RETCODE_DONE,
                order=pos.ticket,
                price=req["price"],
                comment="closed",
            )
        if action == self.TRADE_ACTION_DEAL:
            self._next_ticket += 1
            self.positions.append(
                FakePosition(
                    self._next_ticket,
                    req["symbol"],
                    req["type"],
                    req["volume"],
                    req["price"],
                    req["sl"],
                    req["tp"],
                    req["price"],
                    req["magic"],
                    req["comment"],
                    int(self.now.timestamp()),
                )
            )
            return SimpleNamespace(
                retcode=self.TRADE_RETCODE_DONE,
                order=self._next_ticket,
                price=req["price"],
                comment="done",
            )
        if action == self.TRADE_ACTION_SLTP:
            pos = next(p for p in self.positions if p.ticket == req["position"])
            pos.sl, pos.tp = req["sl"], req["tp"]
            return SimpleNamespace(
                retcode=self.TRADE_RETCODE_DONE, order=pos.ticket, price=0.0, comment="modified"
            )
        if action == self.TRADE_ACTION_REMOVE:
            self.pending.remove(req["order"])
            return SimpleNamespace(
                retcode=self.TRADE_RETCODE_DONE, order=req["order"], price=0.0, comment="removed"
            )
        raise AssertionError(req)

    # test helpers
    def set_rates(self, symbol: str, tf: int, bars: list[Any]) -> None:
        arr = np.zeros(len(bars), RATE_DTYPE)
        for i, b in enumerate(bars):
            arr[i] = (int(b.ts_utc.timestamp()), b.open, b.high, b.low, b.close, 1, 1, 1)
        self.rates[(symbol, tf)] = arr
