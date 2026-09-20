"""Abstract strategy contract.

A strategy is a *pure* signal generator: it consumes completed :class:`Bar`
objects (historical for warmup, then live) and returns
:class:`OrderIntent` lists. It never talks to the broker, never sizes
against account equity, and never bypasses risk — those belong to the app,
risk, and execution layers.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Iterable, List

from ..core.types import Bar, OrderIntent

log = logging.getLogger(__name__)


class BaseStrategy(ABC):
    """Base class all strategies must extend.

    Lifecycle::

        s = MyStrategy(...)
        s.prime(historical_bars)      # warmup, produces no intents
        intents = s.on_bar(live_bar)  # called once per completed bar
        s.on_own_fill(signed_qty, price)  # OMS feedback keeps position sync'd

    Subclasses must implement :meth:`warmup_bars`, :meth:`compute_signals`,
    and declare :attr:`symbol`.
    """

    #: Unique id, stamped onto every intent this strategy emits.
    strategy_id: str = "base"

    #: The single symbol this strategy trades.
    symbol: str = ""

    def __init__(self) -> None:
        self._bars_seen: int = 0
        self._position: int = 0

    # ------------------------------------------------------------ contract

    @property
    @abstractmethod
    def warmup_bars(self) -> int:
        """Number of bars required before signals are trustworthy."""

    @abstractmethod
    def compute_signals(self, bar: Bar) -> List[OrderIntent]:
        """Update internal state with ``bar`` and return intents (may be []).

        Called for *every* bar, including warmup bars — implementations must
        update indicators unconditionally but only emit intents once
        :meth:`is_warm` is true (``on_bar`` enforces this as a backstop).
        """

    # ------------------------------------------------------------- runtime

    @property
    def position(self) -> int:
        """Net signed position attributed to this strategy."""
        return self._position

    @property
    def is_warm(self) -> bool:
        return self._bars_seen >= self.warmup_bars

    def prime(self, bars: Iterable[Bar]) -> None:
        """Feed historical bars for warmup; any intents are discarded."""
        n = 0
        for bar in bars:
            self._ingest(bar)
            n += 1
        log.info("%s primed with %d historical bars (warm=%s)",
                 self.strategy_id, n, self.is_warm)

    def on_bar(self, bar: Bar) -> List[OrderIntent]:
        """Process one completed live bar and return approved-for-risk intents."""
        intents = self._ingest(bar)
        if not self.is_warm:
            return []
        for intent in intents:
            log.info("%s intent: %s %d %s (%s)", self.strategy_id,
                     intent.action.value, intent.quantity, intent.symbol,
                     intent.reason)
        return intents

    def on_own_fill(self, signed_quantity: int, price: float) -> None:
        """OMS callback: a fill from an order this strategy originated."""
        self._position += signed_quantity
        log.debug("%s fill feedback: %+d @ %.4f -> position=%d",
                  self.strategy_id, signed_quantity, price, self._position)

    # ------------------------------------------------------------ internal

    def _ingest(self, bar: Bar) -> List[OrderIntent]:
        if self.symbol and bar.symbol != self.symbol:
            log.warning("%s ignoring bar for foreign symbol %s",
                        self.strategy_id, bar.symbol)
            return []
        self._bars_seen += 1
        return self.compute_signals(bar)
