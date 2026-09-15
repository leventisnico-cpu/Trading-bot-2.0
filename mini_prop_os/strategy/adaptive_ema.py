"""Volatility-adaptive EMA crossover strategy.

Extends the plain crossover with three transparent adaptations to market
conditions, each individually testable:

1. **Regime detection** — an EWMA of absolute log returns over a fast
   window, compared to a slow baseline EWMA, classifies each bar as
   LOW / NORMAL / HIGH / EXTREME volatility.
2. **Regime-dependent behavior** —
   * position size scales down as volatility rises (base size in
     LOW/NORMAL, half in HIGH, zero in EXTREME);
   * EXTREME volatility is risk-off: no entries, and an open position is
     exited immediately;
   * entries require *confirmation*: after a golden cross, the EMA spread
     must exceed ``k[regime] * ATR`` within ``confirm_window`` bars, which
     suppresses whipsaw entries in chop (in a real trend the spread widens
     within a couple of bars; in chop it never does).
3. **Online learning** — after each completed round trip, the entry
   threshold ``k`` for the regime the trade was *entered* in is nudged up
   on a loss and down on a win, hard-bounded to ``[k_min, k_max]``. The
   adjustment is a bounded step, every update is logged, and the learned
   state is inspectable (:attr:`entry_thresholds`, :attr:`regime_stats`).

The learning rule is deliberately simple and bounded: it cannot invert the
strategy, cannot raise size, and cannot disable exits — it can only make
entries in a losing regime progressively more selective. Exits are never
filtered; leaving a position is always allowed.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

from ..core.types import Action, Bar, IntentSource, OrderIntent, OrderType
from .base import BaseStrategy

log = logging.getLogger(__name__)


class VolRegime(str, Enum):
    """Volatility regime classification for one bar."""

    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    EXTREME = "EXTREME"


@dataclass
class RegimeStats:
    """Per-regime trade outcome memory (for learning and reporting)."""

    trades: int = 0
    wins: int = 0
    total_pnl_points: float = 0.0


class AdaptiveEmaCrossoverStrategy(BaseStrategy):
    """EMA crossover with volatility-regime sizing, risk-off, entry
    confirmation, and bounded online threshold learning."""

    strategy_id = "adaptive_ema"

    #: Default entry-confirmation thresholds (in ATR units) per regime.
    DEFAULT_THRESHOLDS: Dict[VolRegime, float] = {
        VolRegime.LOW: 0.05,
        VolRegime.NORMAL: 0.15,
        VolRegime.HIGH: 0.35,
        VolRegime.EXTREME: math.inf,  # never enter
    }

    def __init__(
        self,
        symbol: str,
        fast_period: int = 9,
        slow_period: int = 21,
        base_quantity: int = 2,
        warmup_bars: int = 0,
        vol_fast_period: int = 10,
        vol_slow_period: int = 100,
        high_vol_ratio: float = 1.6,
        extreme_vol_ratio: float = 2.5,
        confirm_window: int = 10,
        learn: bool = True,
        k_step: float = 0.05,
        k_min: float = 0.0,
        k_max: float = 1.0,
    ) -> None:
        """
        Args:
            base_quantity: units per entry in LOW/NORMAL volatility; HIGH
                trades ``max(1, base_quantity // 2)``, EXTREME trades 0.
            vol_fast_period / vol_slow_period: EWMA windows for current
                volatility vs its long-run baseline.
            high_vol_ratio / extreme_vol_ratio: fast/slow volatility ratios
                separating NORMAL from HIGH and HIGH from EXTREME.
            confirm_window: bars after a golden cross during which a
                confirmed entry may trigger.
            learn: enable the bounded per-regime threshold adaptation.
            k_step / k_min / k_max: learning step size and hard bounds.
        """
        super().__init__()
        if fast_period < 1 or slow_period < 2 or fast_period >= slow_period:
            raise ValueError("bad EMA periods")
        if base_quantity < 1:
            raise ValueError("base_quantity must be >= 1")
        if vol_fast_period < 2 or vol_slow_period <= vol_fast_period:
            raise ValueError("need vol_fast_period >= 2 and vol_slow > fast")
        if not (1.0 < high_vol_ratio < extreme_vol_ratio):
            raise ValueError("need 1 < high_vol_ratio < extreme_vol_ratio")
        if confirm_window < 1:
            raise ValueError("confirm_window must be >= 1")
        if not (0.0 <= k_min <= k_max) or k_step <= 0:
            raise ValueError("bad learning bounds")
        self.symbol = symbol
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.base_quantity = base_quantity
        self._warmup = warmup_bars if warmup_bars > 0 else max(
            3 * slow_period, vol_slow_period)
        self.vol_fast_period = vol_fast_period
        self.vol_slow_period = vol_slow_period
        self.high_vol_ratio = high_vol_ratio
        self.extreme_vol_ratio = extreme_vol_ratio
        self.confirm_window = confirm_window
        self.learn = learn
        self.k_step = k_step
        self.k_min = k_min
        self.k_max = k_max

        self._alpha_fast = 2.0 / (fast_period + 1)
        self._alpha_slow = 2.0 / (slow_period + 1)
        self._alpha_vf = 2.0 / (vol_fast_period + 1)
        self._alpha_vs = 2.0 / (vol_slow_period + 1)
        self._alpha_atr = 2.0 / (14 + 1)

        self._ema_fast: Optional[float] = None
        self._ema_slow: Optional[float] = None
        self._vol_fast: Optional[float] = None
        self._vol_slow: Optional[float] = None
        self._atr: Optional[float] = None
        self._prev_close: Optional[float] = None
        self._cross_sign: Optional[int] = None
        self._pending_entry_bars: int = 0

        #: Learned entry thresholds, ATR units, per regime (EXTREME fixed).
        self.entry_thresholds: Dict[VolRegime, float] = dict(
            self.DEFAULT_THRESHOLDS)
        self.regime_stats: Dict[VolRegime, RegimeStats] = {
            r: RegimeStats() for r in VolRegime}
        self.regime_history: List[VolRegime] = []

        # Round-trip bookkeeping for learning.
        self._entry_regime: Optional[VolRegime] = None
        self._entry_avg_price: float = 0.0
        self._entry_qty: int = 0
        self._exit_pnl_points: float = 0.0

    # ------------------------------------------------------------ contract

    @property
    def warmup_bars(self) -> int:
        return self._warmup

    @property
    def regime(self) -> VolRegime:
        """Current volatility regime (NORMAL until vol EWMAs exist)."""
        if not self._vol_fast or not self._vol_slow or self._vol_slow <= 0:
            return VolRegime.NORMAL
        ratio = self._vol_fast / self._vol_slow
        if ratio >= self.extreme_vol_ratio:
            return VolRegime.EXTREME
        if ratio >= self.high_vol_ratio:
            return VolRegime.HIGH
        if ratio <= 0.7:
            return VolRegime.LOW
        return VolRegime.NORMAL

    def size_for_regime(self, regime: VolRegime) -> int:
        """Entry size under the given volatility regime."""
        if regime is VolRegime.EXTREME:
            return 0
        if regime is VolRegime.HIGH:
            return max(1, self.base_quantity // 2)
        return self.base_quantity

    # ------------------------------------------------------------- signals

    def _update_indicators(self, bar: Bar) -> None:
        close = bar.close
        self._ema_fast = (close if self._ema_fast is None else
                          self._ema_fast
                          + self._alpha_fast * (close - self._ema_fast))
        self._ema_slow = (close if self._ema_slow is None else
                          self._ema_slow
                          + self._alpha_slow * (close - self._ema_slow))
        if self._prev_close is not None and self._prev_close > 0:
            r = abs(math.log(close / self._prev_close))
            self._vol_fast = (r if self._vol_fast is None else
                              self._vol_fast
                              + self._alpha_vf * (r - self._vol_fast))
            self._vol_slow = (r if self._vol_slow is None else
                              self._vol_slow
                              + self._alpha_vs * (r - self._vol_slow))
            tr = max(bar.high - bar.low,
                     abs(bar.high - self._prev_close),
                     abs(bar.low - self._prev_close))
            self._atr = (tr if self._atr is None else
                         self._atr + self._alpha_atr * (tr - self._atr))
        self._prev_close = close

    def compute_signals(self, bar: Bar) -> List[OrderIntent]:
        if bar.close <= 0:
            return []
        self._update_indicators(bar)
        regime = self.regime
        self.regime_history.append(regime)

        assert self._ema_fast is not None and self._ema_slow is not None
        new_sign = 1 if self._ema_fast > self._ema_slow else (
            -1 if self._ema_fast < self._ema_slow else self._cross_sign)
        prev_sign, self._cross_sign = self._cross_sign, new_sign

        if not self.is_warm:
            return []

        intents: List[OrderIntent] = []

        # Risk-off: EXTREME volatility exits any open position immediately
        # and cancels any pending entry. Exits are never filtered.
        if regime is VolRegime.EXTREME:
            self._pending_entry_bars = 0
            if self.position > 0:
                intents.append(self._exit_intent(
                    f"EXTREME volatility risk-off "
                    f"(vol ratio {self._vol_ratio():.2f})"))
            return intents

        crossed_up = (prev_sign is not None and new_sign != prev_sign
                      and new_sign > 0)
        crossed_down = (prev_sign is not None and new_sign != prev_sign
                        and new_sign < 0)

        if crossed_down:
            self._pending_entry_bars = 0
            if self.position > 0:
                intents.append(self._exit_intent(
                    f"death cross (fast {self._ema_fast:.2f} < "
                    f"slow {self._ema_slow:.2f})"))
            return intents

        if crossed_up and self.position == 0:
            self._pending_entry_bars = self.confirm_window

        # Confirmation gate: enter only once the spread clears the learned
        # threshold for the current regime, within the window.
        if self._pending_entry_bars > 0 and self.position == 0:
            self._pending_entry_bars -= 1
            spread = self._ema_fast - self._ema_slow
            threshold = self.entry_thresholds[regime] * (self._atr or 0.0)
            qty = self.size_for_regime(regime)
            if spread >= threshold and qty > 0 and spread > 0:
                self._pending_entry_bars = 0
                intents.append(OrderIntent(
                    action=Action.BUY, symbol=self.symbol, quantity=qty,
                    order_type=OrderType.MARKET,
                    source=IntentSource.STRATEGY,
                    strategy_id=self.strategy_id,
                    reason=(f"confirmed golden cross in {regime.value} vol "
                            f"(spread {spread:.2f} >= "
                            f"{self.entry_thresholds[regime]:.2f}*ATR, "
                            f"size {qty})")))
                self._entry_regime = regime
        return intents

    def _exit_intent(self, reason: str) -> OrderIntent:
        return OrderIntent(
            action=Action.SELL, symbol=self.symbol, quantity=self.position,
            order_type=OrderType.MARKET, source=IntentSource.STRATEGY,
            strategy_id=self.strategy_id, reason=reason)

    def _vol_ratio(self) -> float:
        if not self._vol_fast or not self._vol_slow or self._vol_slow <= 0:
            return 1.0
        return self._vol_fast / self._vol_slow

    # ------------------------------------------------------------ learning

    def on_own_fill(self, signed_quantity: int, price: float) -> None:
        was_flat = self.position == 0
        super().on_own_fill(signed_quantity, price)
        if signed_quantity > 0:
            if was_flat:
                self._entry_avg_price = price
                self._entry_qty = signed_quantity
                self._exit_pnl_points = 0.0
            else:  # partial entry fills: extend the average
                total = self._entry_qty + signed_quantity
                self._entry_avg_price = (
                    (self._entry_avg_price * self._entry_qty
                     + price * signed_quantity) / total)
                self._entry_qty = total
        else:
            self._exit_pnl_points += (-signed_quantity) * (
                price - self._entry_avg_price)
            if self.position == 0 and self._entry_qty > 0:
                self._complete_round_trip(self._exit_pnl_points)

    def _complete_round_trip(self, pnl_points: float) -> None:
        regime = self._entry_regime or VolRegime.NORMAL
        stats = self.regime_stats[regime]
        stats.trades += 1
        stats.total_pnl_points += pnl_points
        won = pnl_points > 0
        if won:
            stats.wins += 1
        if self.learn and regime is not VolRegime.EXTREME:
            old = self.entry_thresholds[regime]
            delta = -self.k_step if won else self.k_step
            new = min(self.k_max, max(self.k_min, old + delta))
            if new != old:
                self.entry_thresholds[regime] = new
                log.info(
                    "adaptive: %s trade in %s vol (%.2f pts) -> entry "
                    "threshold %.2f -> %.2f ATR",
                    "winning" if won else "losing", regime.value,
                    pnl_points, old, new)
        self._entry_regime = None
        self._entry_qty = 0
        self._entry_avg_price = 0.0
        self._exit_pnl_points = 0.0
