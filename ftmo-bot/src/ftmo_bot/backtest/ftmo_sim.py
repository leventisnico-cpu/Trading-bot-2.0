"""Rolling-window FTMO challenge replay (SPEC "FTMO simulator").

Replays the backtest's day-by-day equity (CE(S)T days, intraday low included)
from every possible challenge start date. Each window runs until the profit
target is hit (with the minimum trading days) or a rule is breached, using the
SAME ``risk/ftmo_rules.py`` functions as the live guard — once with the engine
limits (2.5% / 6%) and once with FTMO's (5% / 10%) — so a backtest "pass" means
exactly what a live "pass" means.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from ftmo_bot.risk.ftmo_rules import (
    AccountState,
    HaltKind,
    Limits,
    daily_loss,
    overall_loss,
    should_halt,
    target_reached,
)

# Exported so a test can assert these ARE the ftmo_rules functions.
RULE_FUNCTIONS = (daily_loss, overall_loss, should_halt, target_reached)


@dataclass(frozen=True)
class Day:
    day: date
    start: float
    low: float
    end: float
    traded: bool


@dataclass(frozen=True)
class WindowResult:
    start_day: date
    outcome: str  # passed | ftmo_failed | engine_halted | unresolved
    reason: str
    days_elapsed: int  # calendar days from start to the deciding day (inclusive)
    trading_days: int
    max_daily_dd_pct: float
    engine_daily_halts: int


def days_from_frame(days: pd.DataFrame) -> list[Day]:
    return [
        Day(d, float(s), float(lo), float(e), bool(n > 0))
        for d, s, lo, e, n in zip(
            days["date_cest"],
            days["start_equity"],
            days["min_equity"],
            days["end_equity"],
            days["trades"],
            strict=True,
        )
    ]


def _noon_utc(d: date, tz: str) -> datetime:
    return datetime.combine(d, time(12), tzinfo=ZoneInfo(tz))


def simulate_window(
    days: list[Day],
    i0: int,
    engine: Limits,
    ftmo: Limits,
    target_pct: float,
    min_trading_days: int,
) -> WindowResult:
    initial = ftmo.initial_balance
    offset = initial - days[i0].start
    trading = 0
    max_dd = 0.0
    engine_daily = 0
    for d in days[i0:]:
        state = AccountState(
            now_utc=_noon_utc(d.day, ftmo.reset_tz),
            equity=d.low + offset,
            day_baseline=d.start + offset,
            overall_reference=initial,
        )
        max_dd = max(max_dd, daily_loss(state) / initial)
        elapsed = (d.day - days[i0].day).days + 1
        if d.traded:
            trading += 1
        ftmo_breach = should_halt(state, ftmo)
        if ftmo_breach is not None:
            return WindowResult(
                days[i0].day,
                "ftmo_failed",
                ftmo_breach.kind.value,
                elapsed,
                trading,
                max_dd,
                engine_daily,
            )
        eng = should_halt(state, engine)
        if eng is not None:
            if eng.kind is HaltKind.OVERALL:
                return WindowResult(
                    days[i0].day, "engine_halted", "overall", elapsed, trading, max_dd, engine_daily
                )
            engine_daily += 1
        if target_reached(d.end + offset, initial, target_pct) and trading >= min_trading_days:
            return WindowResult(
                days[i0].day, "passed", "target", elapsed, trading, max_dd, engine_daily
            )
    return WindowResult(
        days[i0].day,
        "unresolved",
        "data end",
        (days[-1].day - days[i0].day).days + 1,
        trading,
        max_dd,
        engine_daily,
    )


def rolling(
    days: list[Day], engine: Limits, ftmo: Limits, target_pct: float, min_trading_days: int
) -> list[WindowResult]:
    """One window per possible start day (every day the market was open)."""
    return [
        simulate_window(days, i, engine, ftmo, target_pct, min_trading_days)
        for i in range(len(days))
    ]


def summarize(windows: list[WindowResult]) -> dict[str, Any]:
    n = len(windows)
    counts = {
        k: sum(w.outcome == k for w in windows)
        for k in ("passed", "ftmo_failed", "engine_halted", "unresolved")
    }
    resolved = n - counts["unresolved"]
    passed_days = [w.days_elapsed for w in windows if w.outcome == "passed"]
    dds = np.array([w.max_daily_dd_pct for w in windows]) if windows else np.zeros(1)
    return {
        "windows": n,
        **counts,
        "pass_rate": counts["passed"] / resolved if resolved else 0.0,
        "pass_rate_all_windows": counts["passed"] / n if n else 0.0,
        "ftmo_fail_rate": counts["ftmo_failed"] / resolved if resolved else 0.0,
        "engine_overall_halt_rate": counts["engine_halted"] / resolved if resolved else 0.0,
        "windows_with_engine_daily_halt": sum(w.engine_daily_halts > 0 for w in windows),
        "median_days_to_pass": median(passed_days) if passed_days else None,
        "max_daily_dd_pct": {
            "p50": float(np.percentile(dds, 50)),
            "p95": float(np.percentile(dds, 95)),
            "max": float(dds.max()),
        },
    }


def window_table(windows: list[WindowResult]) -> pd.DataFrame:
    return pd.DataFrame([asdict(w) for w in windows])
