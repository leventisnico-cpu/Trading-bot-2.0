"""12-1 month time-series momentum, long-only, monthly decision.

DEPLOYABLE: no
    Survived the research pass (research/momentum_12_1_vs_tbills.md: on
    SPY, fully invested, 2/3 folds and the full sample by ~4% over 27
    years) but FAILED Order 3's gate through the production pipeline
    (reports/minipropos_expectancy_spy.md: 1/3 folds, full sample loses
    to holding the same lot). An edge that flips sign between a
    constant-dollar model and a constant-share lot with $1 commissions
    and one tick of slippage is not an edge this repo deploys.

Rules
-----
* Track month-end closes from whatever bars arrive (the last bar seen in
  a calendar month is that month's close). Any bar size works; priming
  needs ~13 months of history (``strategy.history_duration``).
* On the first bar of a new month, with at least 13 month-end closes
  known, compute ``mom = close[M-1] / close[M-12] - 1`` where ``M`` is
  the month just completed — i.e. the return over the 11 months ending
  one month ago, skipping the most recent month (the canonical "12-1").
* ``mom > 0`` and flat → BUY ``order_quantity``; ``mom <= 0`` and long →
  SELL the whole position. At most one order per month. Cash is the
  alternative (T-bills are not modelled; that understates the strategy's
  return in cash months, which is the conservative direction).
* No intramonth trading, no leverage, no shorts.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from ..core.types import Action, Bar, IntentSource, OrderIntent, OrderType
from .base import BaseStrategy

LOOKBACK_MONTHS = 12
SKIP_MONTHS = 1


class TimeSeriesMomentumStrategy(BaseStrategy):
    """See module docstring."""

    strategy_id = "tsmom_12_1"

    def __init__(self, symbol: str, order_quantity: int = 10,
                 lookback_months: int = LOOKBACK_MONTHS,
                 skip_months: int = SKIP_MONTHS) -> None:
        super().__init__()
        if not symbol:
            raise ValueError("symbol required")
        if order_quantity < 1:
            raise ValueError("order_quantity must be >= 1")
        if skip_months < 0 or lookback_months <= skip_months:
            raise ValueError("need 0 <= skip_months < lookback_months")
        self.symbol = symbol
        self.order_quantity = order_quantity
        self.lookback = lookback_months
        self.skip = skip_months
        self._month_closes: List[float] = []      # completed months
        self._current_month: Optional[Tuple[int, int]] = None
        self._current_close: Optional[float] = None
        self.last_momentum: Optional[float] = None
        self.decisions: int = 0

    @property
    def warmup_bars(self) -> int:
        return 1  # readiness is month-based; see ``months_known``

    @property
    def months_known(self) -> int:
        return len(self._month_closes)

    @property
    def is_ready(self) -> bool:
        return self.months_known >= self.lookback + 1

    def momentum(self) -> Optional[float]:
        """12-1 momentum from the completed months, or None if not ready."""
        if not self.is_ready:
            return None
        recent = self._month_closes[-1 - self.skip]
        base = self._month_closes[-1 - self.lookback]
        if base <= 0:
            return None
        return recent / base - 1.0

    def compute_signals(self, bar: Bar) -> List[OrderIntent]:
        ym = (bar.timestamp.year, bar.timestamp.month)
        intents: List[OrderIntent] = []
        if self._current_month is not None and ym != self._current_month:
            # The previous bar was the last of its month: close the month
            # and decide for the new one (t+1 relative to that close).
            assert self._current_close is not None
            self._month_closes.append(self._current_close)
            intents = self._decide()
        self._current_month = ym
        if bar.close > 0:
            self._current_close = bar.close
        return intents

    def _decide(self) -> List[OrderIntent]:
        mom = self.momentum()
        if mom is None:
            return []
        self.last_momentum = mom
        self.decisions += 1
        common = dict(symbol=self.symbol, order_type=OrderType.MARKET,
                      source=IntentSource.STRATEGY,
                      strategy_id=self.strategy_id)
        if mom > 0 and self.position == 0:
            return [OrderIntent(action=Action.BUY,
                                quantity=self.order_quantity,
                                reason=f"12-1 momentum {mom:+.2%} > 0",
                                **common)]
        if mom <= 0 and self.position > 0:
            return [OrderIntent(action=Action.SELL, quantity=self.position,
                                reason=f"12-1 momentum {mom:+.2%} <= 0",
                                **common)]
        return []
