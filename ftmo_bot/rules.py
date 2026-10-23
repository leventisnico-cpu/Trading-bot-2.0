"""FTMO limits, position sizing and the near-breach guard (pure).

FTMO 2-Step (as modelled in research/funded_ftmo_swing.md):
* max loss: equity must stay above (1 - max_loss) x initial balance;
* max daily loss: equity must stay above day-start balance - daily_loss x
  initial balance (day starts at midnight Prague time; balance excludes
  floating P&L).
The guard flattens just before either line. Exits are never blocked;
only new entries are refused.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Limits:
    initial: float
    max_loss: float = 0.10
    daily_loss: float = 0.05
    buffer: float = 0.002

    def total_floor(self) -> float:
        return self.initial * (1 - self.max_loss)

    def daily_floor(self, day_start_balance: float) -> float:
        return day_start_balance - self.daily_loss * self.initial

    def guard(self, equity: float, day_start_balance: float) -> Optional[str]:
        """Reason to flatten everything now, or None."""
        pad = self.buffer * self.initial
        if equity <= self.total_floor() + pad:
            return (f"equity {equity:,.2f} within {pad:,.2f} of the max-loss "
                    f"line {self.total_floor():,.2f}")
        if equity <= self.daily_floor(day_start_balance) + pad:
            return (f"equity {equity:,.2f} within {pad:,.2f} of the daily-loss "
                    f"line {self.daily_floor(day_start_balance):,.2f}")
        return None


def lots(balance: float, risk: float, entry: float, stop: float,
         loss_per_lot: float, cap: float, volume_step: float,
         volume_min: float, volume_max: float) -> float:
    """Volume risking ``risk`` x balance between entry and stop.
    ``loss_per_lot``: account-currency loss of 1.0 lot from entry to stop
    (from the broker, so the currency conversion is the broker's).
    Notional per lot in account currency = loss_per_lot / (entry - stop) x
    entry; total notional is capped at ``cap`` x balance. Rounded down to
    the step; 0.0 if below the minimum."""
    if entry <= stop or loss_per_lot <= 0:
        return 0.0
    v = risk * balance / loss_per_lot
    notional_per_lot = loss_per_lot / (entry - stop) * entry
    v = min(v, cap * balance / notional_per_lot, volume_max)
    v = math.floor(v / volume_step + 1e-9) * volume_step
    return round(v, 8) if v >= volume_min else 0.0


def risk_room(balance: float, day_start_balance: float, committed: float,
              limits: Limits) -> float:
    """Most a new position may risk (entry to stop, account currency) so
    that every open stop hit together, today or on any later day, stays
    ``buffer`` above both loss lines. ``committed``: summed entry-to-stop
    risk of the open positions. FTMO's day-start balance ignores floating
    P&L, so open risk counts in full against each day's 5%: two 3% stops
    (6%) would cross it; this caps the second one at what is left."""
    pad = limits.buffer * limits.initial
    worst = balance - committed                      # all open stops filled
    daily = worst - (limits.daily_floor(day_start_balance) + pad)
    total = worst - (limits.total_floor() + pad)
    return max(0.0, min(daily, total))


def check_entry(equity: float, day_start_balance: float, limits: Limits,
                open_positions: int, max_positions: int,
                blocked: bool) -> Optional[str]:
    """Reason to refuse a new entry, or None. Every entry passes here."""
    if blocked:
        return "entries blocked after a guard flatten (until the next day)"
    if open_positions >= max_positions:
        return f"already {open_positions} positions (max {max_positions})"
    reason = limits.guard(equity, day_start_balance)
    if reason:
        return reason
    return None


def target_reached(equity: float, initial: float, target: Optional[float],
                   trading_days: int, min_days: int) -> bool:
    return (target is not None and equity >= initial * (1 + target)
            and trading_days >= min_days)
