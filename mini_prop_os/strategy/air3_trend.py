"""AIR3: ride one ETF while its long trend holds, in cash when it breaks.

DEPLOYABLE: no
    Pre-registered on Astral (research/astral_daily_candidates_2026_09.md)
    and chosen for its drawdown, not its return. Under the expectancy
    gate (scripts/expectancy.py: beat buy-and-hold, or earn more per
    dollar of drawdown while keeping half its gain, with entries sized to
    95% of current equity) it PASSES on SPY (2/3 folds + full sample) and
    FAILS on SMH (1/3 folds; full-sample gain/DD 3.71 vs 3.72, and under
    half of SMH's gain in 2013-2020 and 2020-2026). The bot runs it on
    SMH, so it stays marked no. A live start on SMH needs the operator's
    signed waiver in deploy/waivers/operator_waivers.yaml; see
    reports/minipropos_expectancy_smh.md and docs/LIVE_READINESS.md.

Rules (daily bars; the same rule that runs on Astral paper as saved
strategy 6422, deployment 1924)
-----------------------------------------------------------------------
* ``SMA_slow`` = simple moving average of the last 200 closes, ``SMA_fast``
  of the last 50. Nothing is emitted until 200 closes are known.
* Flat and ``close > (1 + entry_band) * SMA_slow`` and
  ``SMA_fast > SMA_slow`` → BUY ``order_quantity`` (one lot, once).
* Long and ``close < (1 - exit_band) * SMA_slow`` → SELL the whole
  position.
* Both bands default to 5%: a 10% dead zone around the slow average in
  which nothing happens. No stop-loss, no target, no pyramiding, no
  shorts. A signal is a *level*: while the entry condition stays true the
  strategy holds its one lot and does not add.
* Orders are market orders emitted on the completed daily bar (the
  close). Submitted after 16:00 ET with IBKR's default DAY /
  regular-hours flags they rest until the next open, which is exactly
  the fill the backtests assume (next bar's open).
"""

from __future__ import annotations

from collections import deque
from typing import Deque, List, Optional

from ..core.types import Action, Bar, IntentSource, OrderIntent, OrderType
from .base import BaseStrategy

FAST_PERIOD = 50
SLOW_PERIOD = 200
ENTRY_BAND = 0.05
EXIT_BAND = 0.05


class Air3TrendStrategy(BaseStrategy):
    """See module docstring."""

    strategy_id = "air3_trend"

    def __init__(self, symbol: str, order_quantity: int = 1,
                 fast_period: int = FAST_PERIOD,
                 slow_period: int = SLOW_PERIOD,
                 entry_band: float = ENTRY_BAND,
                 exit_band: float = EXIT_BAND) -> None:
        super().__init__()
        if not symbol:
            raise ValueError("symbol required")
        if order_quantity < 1:
            raise ValueError("order_quantity must be >= 1")
        if not (1 <= fast_period < slow_period):
            raise ValueError("need 1 <= fast_period < slow_period")
        if not (0.0 <= entry_band < 1.0 and 0.0 <= exit_band < 1.0):
            raise ValueError("bands must be in [0, 1)")
        self.symbol = symbol
        self.order_quantity = order_quantity
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.entry_band = entry_band
        self.exit_band = exit_band
        self._closes: Deque[float] = deque(maxlen=slow_period)
        self._fast_sum = 0.0
        self._slow_sum = 0.0
        self._fast_window: Deque[float] = deque(maxlen=fast_period)
        self.last_close: Optional[float] = None
        self.decisions: int = 0

    # ---------------------------------------------------------- readiness

    @property
    def warmup_bars(self) -> int:
        return self.slow_period

    @property
    def is_ready(self) -> bool:
        return len(self._closes) >= self.slow_period

    # --------------------------------------------------------- indicators

    @property
    def sma_fast(self) -> Optional[float]:
        if len(self._fast_window) < self.fast_period:
            return None
        return self._fast_sum / self.fast_period

    @property
    def sma_slow(self) -> Optional[float]:
        if not self.is_ready:
            return None
        return self._slow_sum / self.slow_period

    @property
    def entry_level(self) -> Optional[float]:
        s = self.sma_slow
        return None if s is None else (1.0 + self.entry_band) * s

    @property
    def exit_level(self) -> Optional[float]:
        s = self.sma_slow
        return None if s is None else (1.0 - self.exit_band) * s

    @property
    def regime(self) -> str:
        """``in`` while the position is on, ``out`` otherwise, ``warmup``
        before the slow average exists."""
        if not self.is_ready:
            return "warmup"
        return "in" if self.position > 0 else "out"

    def _push(self, close: float) -> None:
        if len(self._closes) == self._closes.maxlen:
            self._slow_sum -= self._closes[0]
        self._closes.append(close)
        self._slow_sum += close
        if len(self._fast_window) == self._fast_window.maxlen:
            self._fast_sum -= self._fast_window[0]
        self._fast_window.append(close)
        self._fast_sum += close

    # ------------------------------------------------------------ signals

    def compute_signals(self, bar: Bar) -> List[OrderIntent]:
        if bar.close <= 0:
            return []
        self._push(bar.close)
        self.last_close = bar.close
        fast, slow = self.sma_fast, self.sma_slow
        if fast is None or slow is None:
            return []
        common = dict(symbol=self.symbol, order_type=OrderType.MARKET,
                      source=IntentSource.STRATEGY,
                      strategy_id=self.strategy_id)
        if (self.position == 0 and bar.close > self.entry_level
                and fast > slow):
            self.decisions += 1
            return [OrderIntent(
                action=Action.BUY, quantity=self.order_quantity,
                reason=(f"close {bar.close:.2f} > {self.entry_level:.2f} "
                        f"(1+{self.entry_band:.0%} x SMA{self.slow_period}) "
                        f"and SMA{self.fast_period} > SMA{self.slow_period}"),
                **common)]
        if self.position > 0 and bar.close < self.exit_level:
            self.decisions += 1
            return [OrderIntent(
                action=Action.SELL, quantity=self.position,
                reason=(f"close {bar.close:.2f} < {self.exit_level:.2f} "
                        f"(1-{self.exit_band:.0%} x SMA{self.slow_period})"),
                **common)]
        return []
