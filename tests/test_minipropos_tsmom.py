"""12-1 time-series momentum: month-end tracking, skip month, one order per
month, long-only, and the history_duration config field."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import pytest

from mini_prop_os.core.config import ConfigError, StrategyConfig
from mini_prop_os.core.types import Action, Bar, OrderIntent
from mini_prop_os.strategy.tsmom_12_1 import TimeSeriesMomentumStrategy


def daily_bars(month_closes: List[float], start_year: int = 2020) -> List[Bar]:
    """One bar per weekday; every month's last bar closes at the given
    value (interpolated within the month)."""
    out: List[Bar] = []
    y, m = start_year, 1
    prev = month_closes[0]
    for target in month_closes:
        first = datetime(y, m, 1, tzinfo=timezone.utc)
        nxt = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=timezone.utc)
        days = [first + timedelta(days=i) for i in range((nxt - first).days)
                if (first + timedelta(days=i)).weekday() < 5]
        for i, d in enumerate(days):
            c = prev + (target - prev) * (i + 1) / len(days)
            out.append(Bar("SPY", d, c, c + 1, c - 1, c, 100.0))
        prev = target
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def run(s: TimeSeriesMomentumStrategy, bars: List[Bar]) -> List[OrderIntent]:
    intents: List[OrderIntent] = []
    for b in bars:
        for it in s.on_bar(b):
            intents.append(it)
            s.on_own_fill(it.signed_quantity, b.close)
    return intents


def test_no_decision_until_thirteen_months_are_known():
    s = TimeSeriesMomentumStrategy("SPY", order_quantity=10)
    closes = [100 + i for i in range(13)]            # rising 13 months
    bars = daily_bars(closes)
    assert run(s, bars) == []                         # 12 completed months
    assert s.months_known == 12 and not s.is_ready
    # First bar of month 14 completes month 13 -> decision, BUY.
    nxt = daily_bars(closes + [113])[len(bars):]
    intents = run(s, nxt[:1])
    assert len(intents) == 1 and intents[0].action is Action.BUY
    assert intents[0].quantity == 10
    assert s.is_ready and s.decisions == 1


def test_skip_month_is_respected():
    """Momentum must ignore the most recent completed month."""
    s = TimeSeriesMomentumStrategy("SPY")
    # 12 flat months, then the 13th month crashes: 12-1 skips it -> mom
    # = close(M-1)/close(M-12) - 1 = 0 -> not > 0 -> no BUY.
    closes = [100.0] * 12 + [50.0]
    bars = daily_bars(closes + [50.0])
    intents = run(s, bars)
    assert intents == []
    assert s.last_momentum == pytest.approx(0.0)


def test_exit_when_momentum_turns_negative_and_never_short():
    s = TimeSeriesMomentumStrategy("SPY", order_quantity=10)
    up = [100 + 2 * i for i in range(14)]             # BUY after month 13
    down = [up[-1] - 15 * i for i in range(1, 14)]     # then fall
    intents = run(s, daily_bars(up + down))
    assert intents[0].action is Action.BUY
    sells = [it for it in intents if it.action is Action.SELL]
    assert sells and all(it.quantity == 10 for it in sells)
    assert s.position >= 0
    # Long-only: after a SELL the next intent (if any) is a BUY.
    for a, b in zip(intents, intents[1:]):
        assert a.action is not b.action


def test_at_most_one_order_per_month():
    s = TimeSeriesMomentumStrategy("SPY")
    closes = [100.0 + (i % 5) * 20 for i in range(40)]  # noisy
    intents = run(s, daily_bars(closes))
    assert len(intents) <= 40 - 13
    # Every intent came from a month-boundary decision, none intramonth.
    assert s.decisions >= len(intents)


def test_parameter_validation():
    with pytest.raises(ValueError):
        TimeSeriesMomentumStrategy("")
    with pytest.raises(ValueError):
        TimeSeriesMomentumStrategy("SPY", order_quantity=0)
    with pytest.raises(ValueError):
        TimeSeriesMomentumStrategy("SPY", lookback_months=1, skip_months=1)


def test_history_duration_config_field():
    assert StrategyConfig().history_duration == "2 D"
    StrategyConfig(name="tsmom_12_1", history_duration="400 D")
    for bad in ("400", "D 400", "0 D", "2 X"):
        with pytest.raises(ConfigError, match="history_duration"):
            StrategyConfig(history_duration=bad)
