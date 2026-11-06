"""Intraday EMA-crossover strategy (long-only) on a liquid ticker (e.g. SPY).

DEPLOYABLE: no
    Loses to holding SPY in every walk-forward fold
    (reports/minipropos_expectancy_spy.md; gate:
    scripts/expectancy.py). Paper-only until that changes.

Rules
-----
* Maintain fast and slow exponential moving averages of bar closes,
  updated incrementally (O(1) per bar, no lookback array).
* When the fast EMA crosses **above** the slow EMA and we are flat -> BUY
  ``order_quantity`` shares (market order).
* When the fast EMA crosses **below** the slow EMA and we are long -> SELL
  the entire strategy position (market order).
* No signals until ``warmup_bars`` bars have been ingested, and never more
  than one entry per crossover (state machine on the cross sign).

The strategy is long-only by construction; the risk layer additionally
rejects shorts unless ``risk.allow_short`` is set.
"""

from __future__ import annotations

from typing import List, Optional

from ..core.types import Action, Bar, IntentSource, OrderIntent, OrderType
from .base import BaseStrategy


class EmaCrossoverStrategy(BaseStrategy):
    """Incremental EMA crossover. See module docstring for the rules."""

    strategy_id = "ema_crossover"

    def __init__(
        self,
        symbol: str,
        fast_period: int = 9,
        slow_period: int = 21,
        order_quantity: int = 10,
        warmup_bars: int = 0,
    ) -> None:
        """
        Args:
            symbol: ticker to trade; bars for other symbols are ignored.
            fast_period: fast EMA length in bars (must be < slow_period).
            slow_period: slow EMA length in bars.
            order_quantity: shares per entry.
            warmup_bars: explicit warmup override; 0 derives ``3 * slow_period``
                so both EMAs have effectively converged before trading.
        """
        super().__init__()
        if fast_period < 1 or slow_period < 2:
            raise ValueError("EMA periods must be positive")
        if fast_period >= slow_period:
            raise ValueError("fast_period must be < slow_period")
        if order_quantity < 1:
            raise ValueError("order_quantity must be >= 1")
        self.symbol = symbol
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.order_quantity = order_quantity
        self._warmup = warmup_bars if warmup_bars > 0 else 3 * slow_period
        self._alpha_fast = 2.0 / (fast_period + 1)
        self._alpha_slow = 2.0 / (slow_period + 1)
        self._ema_fast: Optional[float] = None
        self._ema_slow: Optional[float] = None
        #: +1 fast above slow, -1 fast below slow, None until both EMAs exist.
        self._cross_sign: Optional[int] = None

    # ------------------------------------------------------------ contract

    @property
    def warmup_bars(self) -> int:
        return self._warmup

    @property
    def ema_fast(self) -> Optional[float]:
        return self._ema_fast

    @property
    def ema_slow(self) -> Optional[float]:
        return self._ema_slow

    def compute_signals(self, bar: Bar) -> List[OrderIntent]:
        close = bar.close
        if close <= 0:
            # Defensive: a non-positive close is corrupt data; skip the bar
            # without contaminating the EMAs.
            return []
        self._ema_fast = (close if self._ema_fast is None else
                          self._ema_fast +
                          self._alpha_fast * (close - self._ema_fast))
        self._ema_slow = (close if self._ema_slow is None else
                          self._ema_slow +
                          self._alpha_slow * (close - self._ema_slow))

        new_sign = 1 if self._ema_fast > self._ema_slow else (
            -1 if self._ema_fast < self._ema_slow else self._cross_sign)
        prev_sign, self._cross_sign = self._cross_sign, new_sign

        if not self.is_warm or prev_sign is None or new_sign == prev_sign:
            return []

        if new_sign > 0 and self.position == 0:
            return [OrderIntent(
                action=Action.BUY,
                symbol=self.symbol,
                quantity=self.order_quantity,
                order_type=OrderType.MARKET,
                source=IntentSource.STRATEGY,
                strategy_id=self.strategy_id,
                reason=(f"fast EMA({self.fast_period})={self._ema_fast:.4f} "
                        f"crossed above slow EMA({self.slow_period})="
                        f"{self._ema_slow:.4f}"),
            )]
        if new_sign < 0 and self.position > 0:
            return [OrderIntent(
                action=Action.SELL,
                symbol=self.symbol,
                quantity=self.position,
                order_type=OrderType.MARKET,
                source=IntentSource.STRATEGY,
                strategy_id=self.strategy_id,
                reason=(f"fast EMA({self.fast_period})={self._ema_fast:.4f} "
                        f"crossed below slow EMA({self.slow_period})="
                        f"{self._ema_slow:.4f}"),
            )]
        return []
