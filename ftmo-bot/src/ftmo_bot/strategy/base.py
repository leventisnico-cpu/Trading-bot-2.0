"""Strategy contract.

A strategy sees completed bars and emits ``Signal | None``. It never imports
``execution/*`` or ``risk/guard.py``, never sizes, never sends orders, and never
checks drawdown — the risk engine sits above it and wins every conflict.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

Side = Literal["long", "short"]


@dataclass(frozen=True)
class Bar:
    """A completed OHLC bar (bid prices). ``ts_utc`` is the bar's OPEN time."""

    symbol: str
    ts_utc: datetime
    open: float
    high: float
    low: float
    close: float
    minutes: int = 15

    @property
    def close_ts(self) -> datetime:
        return self.ts_utc + timedelta(minutes=self.minutes)


@dataclass(frozen=True)
class Signal:
    """Everything a strategy may say. ``entry`` is the reference price (signal
    bar close); the actual fill is the next tick. ``stop``/``target`` are sent
    server-side with the order and never managed tick by tick."""

    symbol: str
    side: Side
    entry: float
    stop: float
    target: float
    session_id: str


class Strategy(ABC):
    @abstractmethod
    def on_bar(self, bar: Bar, h4: Sequence[Bar]) -> Signal | None:
        """Called once per completed 15m bar, in time order, per instrument.

        ``h4`` is the trend-timeframe history; implementations must ignore any
        bar in it that had not closed by ``bar.close_ts`` (no lookahead).
        """
