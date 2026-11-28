"""FTMO rules engine — the single most important module in the repo.

PURE: no I/O, no MT5, no clock reads, no logging. Every input arrives as an
argument (including ``now_utc``), so the backtest (``backtest/engine.py``,
``backtest/ftmo_sim.py``), the live guard (``risk/guard.py``) and the order
router (``execution/order_router.py``) all run this exact code path.

Measurement follows FTMO: losses are *equity*-based (floating P&L, swaps and
commissions included) and the day resets at 00:00 Europe/Prague (CE(S)T).

The same functions serve both limit sets; the caller passes ``Limits`` built
from either ``engine_limits`` (2.5% / 6%, what the bot enforces) or
``ftmo_limits`` (5% / 10%, what FTMO enforces).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

Side = Literal["long", "short"]

PRAGUE = "Europe/Prague"
_FRIDAY = 4


class SignalLike(Protocol):
    """The two fields of ``strategy.base.Signal`` the rules engine reads."""

    @property
    def symbol(self) -> str: ...

    @property
    def side(self) -> Side: ...


@dataclass(frozen=True)
class Limits:
    """One limit set (engine or FTMO). Amounts are fractions of initial balance."""

    initial_balance: float
    daily_loss_pct: float
    overall_loss_pct: float
    max_open_slots: int = 2
    correlated_groups: tuple[frozenset[str], ...] = ()
    max_consecutive_losses: int = 2
    reset_tz: str = PRAGUE
    friday_cutoff: time = time(21, 0)

    def __post_init__(self) -> None:
        if self.initial_balance <= 0:
            raise ValueError("initial_balance must be positive")
        for name in ("daily_loss_pct", "overall_loss_pct"):
            pct = getattr(self, name)
            if not 0 < pct < 1:
                raise ValueError(f"{name} must be in (0, 1), got {pct}")
        if self.max_open_slots < 1:
            raise ValueError("max_open_slots must be >= 1")
        if self.max_consecutive_losses < 1:
            raise ValueError("max_consecutive_losses must be >= 1")
        ZoneInfo(self.reset_tz)  # raises on an unknown zone

    @property
    def daily_loss_limit(self) -> float:
        return self.initial_balance * self.daily_loss_pct

    @property
    def overall_loss_limit(self) -> float:
        return self.initial_balance * self.overall_loss_pct


@dataclass(frozen=True)
class OpenPosition:
    """An open position as the rules engine sees it.

    ``risk_to_stop`` is the *additional* loss (account currency, >= 0) the
    account takes from the current mark if this position exits at its stop,
    including exit costs. After the breakeven move it is ~exit costs only.
    """

    symbol: str
    side: Side
    risk_to_stop: float


@dataclass(frozen=True)
class AccountState:
    """Account snapshot at ``now_utc``.

    ``equity`` includes unrealised P&L and accrued swap/commission.
    ``day_baseline`` is equity at the last 00:00 CE(S)T.
    ``overall_reference`` is the equity the overall loss is measured from: the
    initial balance for a static floor (FTMO 2-Step).
    """

    now_utc: datetime
    equity: float
    day_baseline: float
    overall_reference: float
    open_positions: tuple[OpenPosition, ...] = ()
    consecutive_losses_today: int = 0


class HaltKind(StrEnum):
    DAILY = "daily"
    OVERALL = "overall"


@dataclass(frozen=True)
class HaltDecision:
    kind: HaltKind
    reason: str


@dataclass(frozen=True)
class Baseline:
    """Equity snapshot at 00:00 CE(S)T for ``day``; persisted by the caller."""

    day: date
    equity: float
    taken_at_utc: datetime
    late: bool = False  # True if snapshotted after a restart, not at midnight


# --------------------------------------------------------------------------
# Clock helpers (pure: ``now_utc`` is always an argument)
# --------------------------------------------------------------------------


def _require_aware(ts: datetime) -> datetime:
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return ts


def to_local(now_utc: datetime, tz: str = PRAGUE) -> datetime:
    return _require_aware(now_utc).astimezone(ZoneInfo(tz))


def trading_day(now_utc: datetime, tz: str = PRAGUE) -> date:
    """The CE(S)T calendar date FTMO's daily-loss counter belongs to."""
    return to_local(now_utc, tz).date()


def _local_midnight_utc(day: date, tz: str) -> datetime:
    # 00:00 always exists in Europe/Prague (DST switches at 02:00/03:00).
    return datetime.combine(day, time(0), tzinfo=ZoneInfo(tz)).astimezone(UTC)


def last_reset_utc(now_utc: datetime, tz: str = PRAGUE) -> datetime:
    """The most recent 00:00 CE(S)T at or before ``now_utc``."""
    return _local_midnight_utc(trading_day(now_utc, tz), tz)


def next_reset_utc(now_utc: datetime, tz: str = PRAGUE) -> datetime:
    """The next 00:00 CE(S)T strictly after ``now_utc``."""
    return _local_midnight_utc(trading_day(now_utc, tz) + timedelta(days=1), tz)


def past_friday_cutoff(now_utc: datetime, limits: Limits) -> bool:
    """True from Friday ``friday_cutoff`` CE(S)T until the Monday reset."""
    local = to_local(now_utc, limits.reset_tz)
    if local.weekday() > _FRIDAY:
        return True
    return local.weekday() == _FRIDAY and local.time() >= limits.friday_cutoff


def resolve_baseline(
    stored: Baseline | None, now_utc: datetime, current_equity: float, tz: str = PRAGUE
) -> Baseline:
    """Return today's baseline: the stored one if it is today's, else a new snapshot.

    This is what makes a mid-day restart keep the midnight baseline.
    """
    _require_aware(now_utc)
    today = trading_day(now_utc, tz)
    if stored is not None and stored.day == today:
        return stored
    late = now_utc - last_reset_utc(now_utc, tz) > timedelta(minutes=1)
    return Baseline(day=today, equity=current_equity, taken_at_utc=now_utc, late=late)


# --------------------------------------------------------------------------
# Loss measurement
# --------------------------------------------------------------------------


def daily_loss(state: AccountState) -> float:
    """Loss since 00:00 CE(S)T in account currency (negative = profit)."""
    return state.day_baseline - state.equity


def overall_loss(state: AccountState) -> float:
    """Loss versus the overall reference in account currency (negative = profit)."""
    return state.overall_reference - state.equity


def should_halt(state: AccountState, limits: Limits) -> HaltDecision | None:
    """Breach check. Reaching a limit exactly counts as a breach (FTMO: ``>=``).

    The overall breach wins because it is the stronger action (manual restart).
    """
    o_loss = overall_loss(state)
    if o_loss >= limits.overall_loss_limit:
        return HaltDecision(
            HaltKind.OVERALL,
            f"overall loss {o_loss:.2f} >= limit {limits.overall_loss_limit:.2f} "
            f"(equity {state.equity:.2f}, reference {state.overall_reference:.2f})",
        )
    d_loss = daily_loss(state)
    if d_loss >= limits.daily_loss_limit:
        return HaltDecision(
            HaltKind.DAILY,
            f"daily loss {d_loss:.2f} >= limit {limits.daily_loss_limit:.2f} "
            f"(equity {state.equity:.2f}, baseline {state.day_baseline:.2f})",
        )
    return None


def target_reached(equity: float, initial_balance: float, target_pct: float) -> bool:
    # Cent tolerance: 100_000 * 1.1 is 110000.00000000001 in floating point.
    return equity - initial_balance * (1.0 + target_pct) >= -1e-6


# --------------------------------------------------------------------------
# Slot accounting
# --------------------------------------------------------------------------


def _group_of(symbol: str, limits: Limits) -> frozenset[str] | None:
    for group in limits.correlated_groups:
        if symbol in group:
            return group
    return None


def slots_used(symbols: Iterable[str], limits: Limits) -> int:
    """Each correlated group counts as one slot; every other symbol as one."""
    slots: set[str | frozenset[str]] = set()
    for symbol in symbols:
        group = _group_of(symbol, limits)
        slots.add(group if group is not None else symbol)
    return len(slots)


# --------------------------------------------------------------------------
# Pre-trade gate
# --------------------------------------------------------------------------


def can_open(
    signal: SignalLike, state: AccountState, limits: Limits, new_trade_risk: float
) -> tuple[bool, str]:
    """Pre-trade gate. Returns ``(allowed, reason)``.

    ``new_trade_risk`` is the loss (account currency) if the new position hits
    its stop, spread + commission + slippage included (``sizing.projected_loss``).
    The projection assumes every open position also stops out.
    """
    _require_aware(state.now_utc)
    if new_trade_risk < 0:
        return False, f"invalid new_trade_risk {new_trade_risk}"

    halt = should_halt(state, limits)
    if halt is not None:
        return False, f"halted ({halt.kind.value}): {halt.reason}"

    if past_friday_cutoff(state.now_utc, limits):
        return False, "past Friday cutoff / weekend"

    if state.consecutive_losses_today >= limits.max_consecutive_losses:
        return False, f"daily soft stop: {state.consecutive_losses_today} consecutive losses"

    open_symbols = [p.symbol for p in state.open_positions]
    if signal.symbol in open_symbols:
        return False, f"position already open on {signal.symbol}"

    group = _group_of(signal.symbol, limits)
    if group is not None:
        for pos in state.open_positions:
            if pos.symbol in group and pos.side != signal.side:
                return False, (
                    f"correlation guard: {pos.symbol} {pos.side} open, "
                    f"refusing {signal.symbol} {signal.side}"
                )

    if slots_used([*open_symbols, signal.symbol], limits) > limits.max_open_slots:
        return False, f"max open slots ({limits.max_open_slots}) reached"

    worst_case = new_trade_risk + sum(max(p.risk_to_stop, 0.0) for p in state.open_positions)
    projected_daily = daily_loss(state) + worst_case
    if projected_daily >= limits.daily_loss_limit:
        return False, (
            f"projected daily loss {projected_daily:.2f} >= limit {limits.daily_loss_limit:.2f}"
        )
    projected_overall = overall_loss(state) + worst_case
    if projected_overall >= limits.overall_loss_limit:
        return False, (
            f"projected overall loss {projected_overall:.2f} "
            f">= limit {limits.overall_loss_limit:.2f}"
        )
    return True, "ok"
