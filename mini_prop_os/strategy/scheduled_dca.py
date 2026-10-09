"""Mechanical dollar-cost averaging: buy a fixed lot on a schedule, never sell.

DEPLOYABLE: yes
    Passes scripts/expectancy.py on SPY: beats holding one lot in 3/3
    walk-forward folds and on the full sample by accumulating exposure
    (reports/minipropos_expectancy_spy.md). This is the measured
    result the repo's Phase 4 verdict pointed at — contribution-directed
    accumulation, no timing.

Rules
-----
* **Long-only, never sells.** The only intent this strategy can emit is a
  market BUY. Exits belong to the operator (or the risk layer's
  flattening, which does not go through the strategy).
* **One order per period.** A period is one slot of the schedule
  (``weekly`` on ``weekday`` at ``time_of_day`` in ``timezone``, or
  ``daily`` at ``time_of_day``). The first completed bar at or after the
  slot triggers the buy for that slot.
* **Fixed share count, or an amount converted at the last price** —
  ``quantity`` shares, or ``amount`` currency units → ``floor(amount /
  close)`` shares (minimum 1 share; 0 if the price exceeds the amount).
* **Idempotent across restarts.** The slot last consumed is persisted to
  ``state_path`` (JSON) the moment the intent is emitted, and loaded at
  construction, so a restart in the same period does not buy again.
* **A fresh start waits for the next slot.** With no persisted state the
  first warm bar *anchors* the schedule (its already-elapsed slot is
  consumed without buying); the first buy is at the next slot. Starting
  the bot on a Wednesday therefore buys the following Monday, never
  "yesterday's" slot.
* **Missed periods are not stacked.** If the bot was down across several
  slots (state present), only the most recent due slot is bought
  (catch-up capped at 1); the older ones are logged and skipped.

Fill feedback (:meth:`on_own_fill`) keeps the accumulated position for
reporting; the strategy never sizes against it.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import List, Optional, Union
from zoneinfo import ZoneInfo

from ..core.types import Action, Bar, IntentSource, OrderIntent, OrderType
from .base import BaseStrategy

log = logging.getLogger(__name__)

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday",
            "saturday", "sunday")
SCHEDULES = ("daily", "weekly")


def parse_time_of_day(text: str) -> time:
    parts = text.strip().split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise ValueError(f"time_of_day must be HH:MM, got {text!r}")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(f"time_of_day out of range: {text!r}")
    return time(h, m)


class ScheduledDcaStrategy(BaseStrategy):
    """See module docstring."""

    strategy_id = "scheduled_dca"

    def __init__(
        self,
        symbol: str,
        quantity: int = 0,
        amount: float = 0.0,
        schedule: str = "weekly",
        weekday: str = "Monday",
        time_of_day: str = "10:00",
        timezone: str = "America/New_York",
        state_path: Optional[Union[str, Path]] = "state/dca_state.json",
        warmup_bars: int = 1,
    ) -> None:
        super().__init__()
        if not symbol:
            raise ValueError("symbol required")
        if (quantity <= 0) == (amount <= 0):
            raise ValueError("set exactly one of quantity (>0) or amount (>0)")
        if schedule not in SCHEDULES:
            raise ValueError(f"schedule must be one of {SCHEDULES}")
        if weekday.lower() not in WEEKDAYS:
            raise ValueError(f"weekday must be one of {WEEKDAYS}")
        if warmup_bars < 1:
            raise ValueError("warmup_bars must be >= 1 (need a last price)")
        self.symbol = symbol
        self.quantity = int(quantity)
        self.amount = float(amount)
        self.schedule = schedule
        self.weekday = WEEKDAYS.index(weekday.lower())
        self.time_of_day = parse_time_of_day(time_of_day)
        self.tz = ZoneInfo(timezone)
        self._warmup = warmup_bars
        self._state_path = Path(state_path) if state_path else None
        self._live = False
        self._last_slot: Optional[datetime] = None
        self._last_buy_slot: Optional[datetime] = None
        self.buys_emitted: int = 0
        self.skipped_slots: int = 0
        self._load_state()

    # ------------------------------------------------------------ contract

    @property
    def warmup_bars(self) -> int:
        return self._warmup

    @property
    def last_slot(self) -> Optional[datetime]:
        """The schedule slot most recently consumed (bought or anchored)."""
        return self._last_slot

    @property
    def last_buy_slot(self) -> Optional[datetime]:
        """The schedule slot most recently bought, if any."""
        return self._last_buy_slot

    # ------------------------------------------------------------ schedule

    def due_slot(self, at: datetime) -> datetime:
        """The most recent schedule slot at or before ``at``."""
        if at.tzinfo is None:
            raise ValueError("bar timestamps must be timezone-aware")
        local = at.astimezone(self.tz)
        candidate = datetime.combine(local.date(), self.time_of_day,
                                     tzinfo=self.tz)
        if self.schedule == "weekly":
            back = (local.weekday() - self.weekday) % 7
            candidate -= timedelta(days=back)
        if candidate > local:
            candidate -= timedelta(days=1 if self.schedule == "daily" else 7)
        return candidate

    def _slots_between(self, after: datetime, upto: datetime) -> int:
        step = timedelta(days=1 if self.schedule == "daily" else 7)
        return int(round((upto - after) / step))

    # ------------------------------------------------------------- signals

    def on_bar(self, bar: Bar) -> List[OrderIntent]:
        self._live = True  # historical priming (``prime``) never anchors
        return super().on_bar(bar)

    def compute_signals(self, bar: Bar) -> List[OrderIntent]:
        if not self._live or not self.is_warm:
            return []
        slot = self.due_slot(bar.timestamp)
        if self._last_slot is not None and slot <= self._last_slot:
            return []
        if self._last_slot is None:
            # Fresh start: anchor on the slot already elapsed, buy at the
            # next one. Primed history must not look like missed downtime.
            self._last_slot = slot
            self._save_state()
            log.info("%s: anchored schedule; first buy at the slot after %s",
                     self.strategy_id, slot.isoformat())
            return []
        missed = self._slots_between(self._last_slot, slot) - 1
        if missed > 0:
            self.skipped_slots += missed
            log.warning("%s: %d schedule slot(s) missed while down; "
                        "buying only the latest (%s)", self.strategy_id,
                        missed, slot.isoformat())
        qty = self._shares_for(bar.close)
        self._last_slot = slot
        self._last_buy_slot = slot if qty > 0 else self._last_buy_slot
        self._save_state()
        if qty <= 0:
            log.warning("%s: amount %.2f buys 0 shares at %.2f; slot %s "
                        "skipped", self.strategy_id, self.amount, bar.close,
                        slot.isoformat())
            return []
        self.buys_emitted += 1
        return [OrderIntent(
            action=Action.BUY, symbol=self.symbol, quantity=qty,
            order_type=OrderType.MARKET, source=IntentSource.STRATEGY,
            strategy_id=self.strategy_id,
            reason=(f"scheduled {self.schedule} DCA buy for slot "
                    f"{slot:%Y-%m-%d %H:%M %Z} at last {bar.close:.2f}"),
        )]

    def _shares_for(self, price: float) -> int:
        if self.quantity > 0:
            return self.quantity
        if price <= 0:
            return 0
        return int(self.amount // price)

    # --------------------------------------------------------------- state

    def _load_state(self) -> None:
        if self._state_path is None or not self._state_path.is_file():
            return
        try:
            raw = json.loads(self._state_path.read_text())
            if raw.get("symbol") not in (None, self.symbol):
                log.warning("%s: state file is for %s, ignoring",
                            self.strategy_id, raw.get("symbol"))
                return
            last = raw.get("last_slot")
            if last:
                self._last_slot = datetime.fromisoformat(last)
                log.info("%s: restored last consumed slot %s",
                         self.strategy_id, self._last_slot.isoformat())
            bought = raw.get("last_buy_slot")
            if bought:
                self._last_buy_slot = datetime.fromisoformat(bought)
            self.buys_emitted = int(raw.get("buys_emitted", 0))
        except (ValueError, OSError, AttributeError) as exc:
            log.error("%s: unreadable state %s (%s); starting fresh",
                      self.strategy_id, self._state_path, exc)

    def _save_state(self) -> None:
        if self._state_path is None or self._last_slot is None:
            return
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "symbol": self.symbol,
            "last_slot": self._last_slot.isoformat(),
            "last_buy_slot": (self._last_buy_slot.isoformat()
                              if self._last_buy_slot else None),
            "last_buy_date": (self._last_buy_slot.date().isoformat()
                              if self._last_buy_slot else None),
            "buys_emitted": self.buys_emitted,
        }, indent=2))
        os.replace(tmp, self._state_path)
