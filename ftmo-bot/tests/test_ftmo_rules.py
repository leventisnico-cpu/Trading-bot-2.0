"""Phase 1: rules engine. Must reach 100% branch coverage (CI enforces it)."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pytest

from ftmo_bot.risk import ftmo_rules as R


@dataclass(frozen=True)
class Sig:
    symbol: str
    side: R.Side


def limits(**kw: object) -> R.Limits:
    base: dict[str, object] = {
        "initial_balance": 100_000.0,
        "daily_loss_pct": 0.025,
        "overall_loss_pct": 0.06,
        "correlated_groups": (frozenset({"EURUSD", "GBPUSD"}),),
    }
    base.update(kw)
    return R.Limits(**base)  # type: ignore[arg-type]


def state(**kw: object) -> R.AccountState:
    base: dict[str, object] = {
        "now_utc": datetime(2026, 3, 4, 10, 0, tzinfo=UTC),  # Wednesday
        "equity": 100_000.0,
        "day_baseline": 100_000.0,
        "overall_reference": 100_000.0,
    }
    base.update(kw)
    return R.AccountState(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------- purity


def test_module_is_pure() -> None:
    """No I/O / MT5 / clock imports in the rules engine (top invariant)."""
    src = Path(R.__file__).read_text()
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    allowed = {"__future__", "collections", "dataclasses", "datetime", "enum", "typing", "zoneinfo"}
    assert imported <= allowed, imported - allowed
    banned_patterns = (
        r"(?<![\w.])open\(",
        r"\.now\(",
        r"utcnow",
        r"time\.time",
        r"MetaTrader5",
        r"print\(",
    )
    for banned in banned_patterns:
        assert not re.search(banned, src), banned


# ---------------------------------------------------------------- Limits


def test_limits_amounts() -> None:
    lim = limits()
    assert lim.daily_loss_limit == pytest.approx(2_500.0)
    assert lim.overall_loss_limit == pytest.approx(6_000.0)


@pytest.mark.parametrize(
    "kw",
    [
        {"initial_balance": 0.0},
        {"daily_loss_pct": 0.0},
        {"overall_loss_pct": 1.0},
        {"max_open_slots": 0},
        {"max_consecutive_losses": 0},
    ],
)
def test_limits_validation(kw: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        limits(**kw)


def test_limits_unknown_tz() -> None:
    with pytest.raises(Exception):  # noqa: B017 - ZoneInfoNotFoundError subclasses KeyError
        limits(reset_tz="Mars/Olympus")


# ---------------------------------------------------------------- clock


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValueError):
        R.trading_day(datetime(2026, 1, 1, 12, 0))


def test_trading_day_midnight_edges_winter() -> None:
    # CET = UTC+1: 22:59:59Z is still the 4th, 23:00Z is the 5th.
    assert R.trading_day(datetime(2026, 1, 4, 22, 59, 59, tzinfo=UTC)) == date(2026, 1, 4)
    assert R.trading_day(datetime(2026, 1, 4, 23, 0, tzinfo=UTC)) == date(2026, 1, 5)


def test_trading_day_midnight_edges_summer() -> None:
    # CEST = UTC+2: reset at 22:00Z.
    assert R.trading_day(datetime(2026, 7, 1, 21, 59, 59, tzinfo=UTC)) == date(2026, 7, 1)
    assert R.trading_day(datetime(2026, 7, 1, 22, 0, tzinfo=UTC)) == date(2026, 7, 2)


def test_next_reset_spring_forward_night() -> None:
    # 2026-03-29 02:00 CET -> 03:00 CEST. The day is 23h long.
    before = datetime(2026, 3, 28, 22, 30, tzinfo=UTC)  # 23:30 CET on the 28th
    nxt = R.next_reset_utc(before)
    assert nxt == datetime(2026, 3, 28, 23, 0, tzinfo=UTC)  # 00:00 CET on the 29th
    after = R.next_reset_utc(nxt)
    assert after == datetime(2026, 3, 29, 22, 0, tzinfo=UTC)  # 00:00 CEST on the 30th
    assert after - nxt == timedelta(hours=23)
    # Inside the skipped hour's UTC instant, the day is still the 29th.
    assert R.trading_day(datetime(2026, 3, 29, 1, 30, tzinfo=UTC)) == date(2026, 3, 29)


def test_next_reset_fall_back_night() -> None:
    # 2026-10-25 03:00 CEST -> 02:00 CET. The day is 25h long.
    start = R.next_reset_utc(datetime(2026, 10, 24, 12, 0, tzinfo=UTC))
    assert start == datetime(2026, 10, 24, 22, 0, tzinfo=UTC)  # 00:00 CEST 25th
    end = R.next_reset_utc(start)
    assert end == datetime(2026, 10, 25, 23, 0, tzinfo=UTC)  # 00:00 CET 26th
    assert end - start == timedelta(hours=25)
    # Both 02:30 local instants (CEST then CET) belong to the 25th.
    assert R.trading_day(datetime(2026, 10, 25, 0, 30, tzinfo=UTC)) == date(2026, 10, 25)
    assert R.trading_day(datetime(2026, 10, 25, 1, 30, tzinfo=UTC)) == date(2026, 10, 25)


def test_next_reset_at_exact_midnight_is_strictly_after() -> None:
    midnight = datetime(2026, 1, 4, 23, 0, tzinfo=UTC)
    assert R.next_reset_utc(midnight) == midnight + timedelta(days=1)
    assert R.last_reset_utc(midnight) == midnight


def test_friday_cutoff() -> None:
    lim = limits()
    # Friday 2026-03-06, CET (UTC+1): 21:00 local = 20:00Z.
    assert not R.past_friday_cutoff(datetime(2026, 3, 6, 19, 59, tzinfo=UTC), lim)
    assert R.past_friday_cutoff(datetime(2026, 3, 6, 20, 0, tzinfo=UTC), lim)
    assert R.past_friday_cutoff(datetime(2026, 3, 7, 12, 0, tzinfo=UTC), lim)  # Saturday
    assert R.past_friday_cutoff(datetime(2026, 3, 8, 12, 0, tzinfo=UTC), lim)  # Sunday
    assert not R.past_friday_cutoff(datetime(2026, 3, 9, 0, 0, tzinfo=UTC), lim)  # Monday
    assert not R.past_friday_cutoff(datetime(2026, 3, 5, 22, 0, tzinfo=UTC), lim)  # Thursday


def test_friday_cutoff_summer_time() -> None:
    lim = limits()
    # Friday 2026-07-03, CEST (UTC+2): 21:00 local = 19:00Z.
    assert not R.past_friday_cutoff(datetime(2026, 7, 3, 18, 59, tzinfo=UTC), lim)
    assert R.past_friday_cutoff(datetime(2026, 7, 3, 19, 0, tzinfo=UTC), lim)


# ---------------------------------------------------------------- baseline


def test_baseline_persists_across_restart() -> None:
    midnight = datetime(2026, 3, 3, 23, 0, 2, tzinfo=UTC)  # 00:00:02 CET on the 4th
    b = R.resolve_baseline(None, midnight, 100_000.0)
    assert b.day == date(2026, 3, 4) and b.equity == 100_000.0 and not b.late
    # Mid-day restart with equity down: the stored midnight baseline is kept.
    restart = datetime(2026, 3, 4, 13, 0, tzinfo=UTC)
    assert R.resolve_baseline(b, restart, 98_200.0) is b


def test_baseline_rolls_at_reset_and_flags_late_snapshot() -> None:
    old = R.Baseline(date(2026, 3, 3), 99_000.0, datetime(2026, 3, 2, 23, 0, tzinfo=UTC))
    late = R.resolve_baseline(old, datetime(2026, 3, 4, 9, 0, tzinfo=UTC), 101_000.0)
    assert late.day == date(2026, 3, 4) and late.equity == 101_000.0 and late.late


def test_baseline_dst_midnight() -> None:
    # 00:00 CEST on 2026-03-30 is 22:00Z on the 29th.
    b = R.resolve_baseline(None, datetime(2026, 3, 29, 22, 0, tzinfo=UTC), 1.0)
    assert b.day == date(2026, 3, 30) and not b.late


# ---------------------------------------------------------------- losses & halt


def test_losses_signed() -> None:
    s = state(equity=101_000.0, day_baseline=100_500.0)
    assert R.daily_loss(s) == pytest.approx(-500.0)
    assert R.overall_loss(s) == pytest.approx(-1_000.0)


def test_no_halt_when_inside_limits() -> None:
    assert R.should_halt(state(equity=97_600.0), limits()) is None


def test_equity_exactly_at_daily_limit_halts() -> None:
    d = R.should_halt(state(equity=97_500.0), limits())
    assert d is not None and d.kind is R.HaltKind.DAILY


def test_equity_exactly_at_overall_limit_halts_overall() -> None:
    s = state(equity=94_000.0, day_baseline=95_000.0)  # daily only 1000
    d = R.should_halt(s, limits())
    assert d is not None and d.kind is R.HaltKind.OVERALL


def test_overall_wins_when_both_breached() -> None:
    d = R.should_halt(state(equity=93_000.0, day_baseline=100_000.0), limits())
    assert d is not None and d.kind is R.HaltKind.OVERALL


def test_floating_loss_breaches_while_balance_fine() -> None:
    """Balance is untouched (no closed trades); floating loss alone breaches.

    The rules engine only ever sees equity, so a 100k balance with -2,600
    floating must halt.
    """
    balance = 100_000.0
    floating = -2_600.0
    d = R.should_halt(state(equity=balance + floating), limits())
    assert d is not None and d.kind is R.HaltKind.DAILY


def test_ftmo_limits_with_same_functions() -> None:
    ftmo = limits(daily_loss_pct=0.05, overall_loss_pct=0.10)
    assert R.should_halt(state(equity=96_000.0), ftmo) is None
    d = R.should_halt(state(equity=95_000.0), ftmo)
    assert d is not None and d.kind is R.HaltKind.DAILY


def test_target_reached() -> None:
    assert R.target_reached(110_000.0, 100_000.0, 0.10)
    assert not R.target_reached(109_999.99, 100_000.0, 0.10)


# ---------------------------------------------------------------- slots


def test_slots_used_groups_correlated() -> None:
    lim = limits()
    assert R.slots_used([], lim) == 0
    assert R.slots_used(["EURUSD", "GBPUSD"], lim) == 1
    assert R.slots_used(["EURUSD", "GBPUSD", "XAUUSD"], lim) == 2
    assert R.slots_used(["NAS100", "XAUUSD"], lim) == 2


# ---------------------------------------------------------------- can_open


def pos(symbol: str, side: R.Side = "long", risk: float = 760.0) -> R.OpenPosition:
    return R.OpenPosition(symbol, side, risk)


def test_can_open_ok() -> None:
    assert R.can_open(Sig("EURUSD", "long"), state(), limits(), 800.0) == (True, "ok")


def test_can_open_rejects_negative_risk() -> None:
    ok, reason = R.can_open(Sig("EURUSD", "long"), state(), limits(), -1.0)
    assert not ok and "invalid" in reason


def test_can_open_rejects_naive_time() -> None:
    with pytest.raises(ValueError):
        R.can_open(Sig("EURUSD", "long"), state(now_utc=datetime(2026, 3, 4, 10)), limits(), 1.0)


def test_can_open_blocked_when_halted() -> None:
    ok, reason = R.can_open(Sig("EURUSD", "long"), state(equity=97_000.0), limits(), 1.0)
    assert not ok and reason.startswith("halted (daily)")


def test_can_open_blocked_after_friday_cutoff() -> None:
    s = state(now_utc=datetime(2026, 3, 6, 20, 30, tzinfo=UTC))
    ok, reason = R.can_open(Sig("EURUSD", "long"), s, limits(), 1.0)
    assert not ok and "Friday" in reason


def test_can_open_daily_soft_stop() -> None:
    ok, reason = R.can_open(Sig("EURUSD", "long"), state(consecutive_losses_today=2), limits(), 1.0)
    assert not ok and "soft stop" in reason
    ok, _ = R.can_open(Sig("EURUSD", "long"), state(consecutive_losses_today=1), limits(), 1.0)
    assert ok


def test_can_open_one_position_per_symbol() -> None:
    s = state(open_positions=(pos("XAUUSD"),))
    ok, reason = R.can_open(Sig("XAUUSD", "long"), s, limits(), 1.0)
    assert not ok and "already open" in reason


def test_correlation_slot_rule() -> None:
    lim = limits()
    eur_long = state(open_positions=(pos("EURUSD", "long"),))
    # Opposite direction in the correlated pair: refused.
    ok, reason = R.can_open(Sig("GBPUSD", "short"), eur_long, lim, 1.0)
    assert not ok and "correlation" in reason
    # Same direction: allowed, and the pair counts as ONE slot...
    ok, _ = R.can_open(Sig("GBPUSD", "long"), eur_long, lim, 1.0)
    assert ok
    # ...so with EURUSD+GBPUSD open there is still one slot left for XAUUSD.
    pair = state(open_positions=(pos("EURUSD"), pos("GBPUSD")))
    assert R.can_open(Sig("XAUUSD", "long"), pair, lim, 1.0)[0]
    # A non-group position with a different symbol does not trip the group check.
    xau = state(open_positions=(pos("XAUUSD", "short"),))
    assert R.can_open(Sig("EURUSD", "long"), xau, lim, 1.0)[0]


def test_max_open_slots() -> None:
    s = state(open_positions=(pos("EURUSD"), pos("XAUUSD")))
    ok, reason = R.can_open(Sig("NAS100", "long"), s, limits(), 1.0)
    assert not ok and "max open slots" in reason
    # GBPUSD joins EURUSD's slot, so it is not blocked by the slot count.
    assert R.can_open(Sig("GBPUSD", "long"), s, limits(), 1.0)[0]


def test_pre_trade_projection_daily() -> None:
    # Down 1,800 today; a new 760 risk would project to 2,560 >= 2,500.
    s = state(equity=98_200.0)
    ok, reason = R.can_open(Sig("EURUSD", "long"), s, limits(), 760.0)
    assert not ok and "projected daily" in reason
    assert R.can_open(Sig("EURUSD", "long"), s, limits(), 690.0)[0]


def test_pre_trade_projection_includes_open_positions_stops() -> None:
    s = state(equity=99_000.0, open_positions=(pos("XAUUSD", risk=800.0),))
    ok, reason = R.can_open(Sig("EURUSD", "long"), s, limits(), 760.0)  # 1000+800+760
    assert not ok and "projected daily" in reason
    # Negative risk_to_stop (stop in profit) is clamped to zero, never a credit.
    s2 = state(equity=99_000.0, open_positions=(pos("XAUUSD", risk=-5_000.0),))
    assert R.can_open(Sig("EURUSD", "long"), s2, limits(), 760.0)[0]


def test_pre_trade_projection_overall() -> None:
    # Fresh day (daily loss 0) but 5,500 down overall: 760 more projects past 6,000.
    s = state(equity=94_500.0, day_baseline=94_500.0)
    ok, reason = R.can_open(Sig("EURUSD", "long"), s, limits(), 760.0)
    assert not ok and "projected overall" in reason


def test_projection_exactly_at_limit_rejected() -> None:
    s = state(equity=98_000.0)
    ok, _ = R.can_open(Sig("EURUSD", "long"), s, limits(), 500.0)  # exactly 2,500
    assert not ok


def test_overall_reference_is_caller_defined() -> None:
    """Trailing (1-Step) profile is a config/caller choice, not a code branch."""
    s = state(equity=104_000.0, day_baseline=104_000.0, overall_reference=110_000.0)
    d = R.should_halt(s, limits())
    assert d is not None and d.kind is R.HaltKind.OVERALL


def test_halt_reason_contains_numbers() -> None:
    d = R.should_halt(state(equity=97_000.0), limits())
    assert d is not None and "3000.00" in d.reason and "2500.00" in d.reason


def test_default_friday_cutoff_value() -> None:
    assert limits().friday_cutoff == time(21, 0)
