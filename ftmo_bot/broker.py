"""The broker interface the runner uses. ``broker_mt5.MT5Broker`` implements
it for MetaTrader 5; tests use a fake."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Protocol, Tuple

Bar = Tuple[datetime, float, float, float, float]     # start (tz-aware), o, h, l, c


@dataclass(frozen=True)
class Account:
    login: int
    server: str
    currency: str
    balance: float
    equity: float
    trade_allowed: bool


@dataclass(frozen=True)
class Spec:
    exists: bool
    volume_min: float = 0.0
    volume_step: float = 0.0
    volume_max: float = 0.0
    tick: float = 0.0             # price step of a stop (0.0: not known)


@dataclass(frozen=True)
class Position:
    ticket: int
    symbol: str
    volume: float
    price_open: float
    sl: float


@dataclass(frozen=True)
class Fill:
    ok: bool
    price: float = 0.0
    ticket: int = 0
    message: str = ""


class Broker(Protocol):
    def account(self) -> Account: ...
    def now(self) -> datetime: ...
    def bars(self, symbol: str, minutes: int, count: int) -> List[Bar]: ...
    def quote(self, symbol: str) -> Tuple[float, float]: ...   # bid, ask
    def spec(self, symbol: str) -> Spec: ...
    def loss_per_lot(self, symbol: str, entry: float, stop: float) -> float: ...
    def positions(self, magic: int) -> List[Position]: ...
    def buy(self, symbol: str, volume: float, sl: Optional[float],
            magic: int, comment: str) -> Fill: ...
    # ``volume`` None closes the whole position; less closes part of it
    # (the ticket stays open with the rest)
    def close(self, position: Position, magic: int, comment: str,
              volume: Optional[float] = None) -> Fill: ...
    def modify_sl(self, position: Position, sl: float, magic: int) -> Fill: ...
