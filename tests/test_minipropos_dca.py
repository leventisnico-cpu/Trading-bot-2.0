"""ScheduledDcaStrategy: schedule boundaries, restart idempotency, capped
catch-up, and the never-sells invariant (pure, no broker)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List
from zoneinfo import ZoneInfo

import pytest

from mini_prop_os.core.types import Action, Bar, OrderIntent
from mini_prop_os.strategy.scheduled_dca import ScheduledDcaStrategy

ET = ZoneInfo("America/New_York")


def bar(ts: datetime, close: float = 500.0) -> Bar:
    return Bar(symbol="SPY", timestamp=ts.astimezone(timezone.utc),
               open=close, high=close + 0.5, low=close - 0.5, close=close,
               volume=1000.0)


def et(y: int, m: int, d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=ET)


def minute_bars(start: datetime, minutes: int, close: float = 500.0) -> List[Bar]:
    return [bar(start + timedelta(minutes=i), close) for i in range(minutes)]


def dca(tmp_path: Path, **kw) -> ScheduledDcaStrategy:
    params = dict(symbol="SPY", quantity=10, schedule="weekly",
                  weekday="Monday", time_of_day="10:00",
                  timezone="America/New_York",
                  state_path=tmp_path / "dca_state.json")
    params.update(kw)
    return ScheduledDcaStrategy(**params)


def feed(s: ScheduledDcaStrategy, bars: List[Bar]) -> List[OrderIntent]:
    out: List[OrderIntent] = []
    for b in bars:
        out += s.on_bar(b)
    return out


# 2026-01-05 is a Monday.
MON = et(2026, 1, 5, 9, 30)


def test_requires_exactly_one_sizing_mode(tmp_path):
    with pytest.raises(ValueError):
        dca(tmp_path, quantity=0, amount=0.0)
    with pytest.raises(ValueError):
        dca(tmp_path, quantity=5, amount=100.0)
    with pytest.raises(ValueError):
        dca(tmp_path, schedule="monthly")
    with pytest.raises(ValueError):
        dca(tmp_path, weekday="Funday")
    with pytest.raises(ValueError):
        dca(tmp_path, time_of_day="25:00")


def test_buys_once_at_first_bar_on_or_after_slot(tmp_path):
    s = dca(tmp_path)
    # Monday 09:30 .. 10:30: first bar anchors (last week's slot
    # consumed without buying), then one buy at 10:00.
    intents = feed(s, minute_bars(MON, 61))
    assert len(intents) == 1
    it = intents[0]
    assert it.action is Action.BUY and it.quantity == 10
    assert it.symbol == "SPY" and it.strategy_id == "scheduled_dca"
    assert s.last_slot == et(2026, 1, 5, 10, 0)
    assert s.last_buy_slot == et(2026, 1, 5, 10, 0)
    # The rest of the week: no further buys.
    assert feed(s, minute_bars(et(2026, 1, 7, 9, 30), 390)) == []
    # Next Monday 10:00: exactly one more.
    assert len(feed(s, minute_bars(et(2026, 1, 12, 9, 30), 61))) == 1


def test_bar_one_minute_before_slot_does_not_trigger(tmp_path):
    s = dca(tmp_path)
    assert feed(s, minute_bars(MON, 30)) == []           # 09:30..09:59
    assert s.last_slot == et(2025, 12, 29, 10, 0)        # anchored only
    assert s.last_buy_slot is None
    assert len(feed(s, [bar(et(2026, 1, 5, 10, 0))])) == 1


def test_fresh_start_after_the_slot_waits_for_next_week(tmp_path):
    """No state, bot started Wednesday: nothing until next Monday 10:00."""
    s = dca(tmp_path)
    assert feed(s, minute_bars(et(2026, 1, 7, 14, 0), 10)) == []
    assert s.last_buy_slot is None
    assert feed(s, minute_bars(et(2026, 1, 12, 9, 30), 30)) == []
    assert len(feed(s, minute_bars(et(2026, 1, 12, 10, 0), 5))) == 1


def test_slot_reached_late_in_the_day_still_buys_once(tmp_path):
    """State from last week, bot restarted after 10:00 on the schedule
    day: the slot is due, buy once."""
    s0 = dca(tmp_path)
    feed(s0, minute_bars(et(2025, 12, 29, 9, 30), 40))   # bought Dec 29
    s = dca(tmp_path)
    intents = feed(s, minute_bars(et(2026, 1, 5, 14, 0), 10))
    assert len(intents) == 1
    assert s.last_slot == et(2026, 1, 5, 10, 0)


def test_restart_in_same_period_is_idempotent(tmp_path):
    s1 = dca(tmp_path)
    assert len(feed(s1, minute_bars(MON, 40))) == 1
    state = json.loads((tmp_path / "dca_state.json").read_text())
    assert state["last_buy_date"] == "2026-01-05"
    assert state["symbol"] == "SPY"
    # Restart: fresh object, same state file, later the same day/week.
    s2 = dca(tmp_path)
    assert s2.last_slot == et(2026, 1, 5, 10, 0)
    assert feed(s2, minute_bars(et(2026, 1, 5, 11, 0), 30)) == []
    assert feed(s2, minute_bars(et(2026, 1, 9, 10, 0), 30)) == []
    # ...and buys again only at the next slot.
    assert len(feed(s2, minute_bars(et(2026, 1, 12, 10, 0), 5))) == 1


def test_missed_periods_catch_up_capped_at_one(tmp_path):
    s = dca(tmp_path)
    assert len(feed(s, minute_bars(MON, 40))) == 1        # slot Jan 5
    # Down for three weeks; back on Tuesday Jan 27 (slots Jan 12/19/26 missed).
    intents = feed(s, minute_bars(et(2026, 1, 27, 9, 30), 10))
    assert len(intents) == 1                               # not 3
    assert s.last_slot == et(2026, 1, 26, 10, 0)
    assert s.skipped_slots == 2                            # Jan 12 and 19


def test_never_emits_a_sell_whatever_the_position(tmp_path):
    s = dca(tmp_path)
    feed(s, [bar(et(2025, 12, 29, 10, 0))])          # anchor last week
    start = et(2026, 1, 5, 9, 30)
    intents: List[OrderIntent] = []
    for week in range(12):
        day = start + timedelta(days=7 * week)
        for i in range(40):
            for it in s.on_bar(bar(day + timedelta(minutes=i),
                                   close=500.0 - 30 * week)):  # falling market
                intents.append(it)
                s.on_own_fill(it.quantity, 500.0 - 30 * week)
    assert intents and all(it.action is Action.BUY for it in intents)
    assert len(intents) == 12
    assert s.position == 120


def test_amount_mode_converts_at_last_price(tmp_path):
    s = dca(tmp_path, quantity=0, amount=1000.0)
    intents = feed(s, minute_bars(MON, 40, close=333.0))
    assert intents[0].quantity == 3            # floor(1000 / 333)
    s2 = dca(tmp_path, quantity=0, amount=100.0, state_path=None)
    assert feed(s2, minute_bars(MON, 40, close=333.0)) == []   # 0 shares
    assert s2.last_slot == et(2026, 1, 5, 10, 0)   # consumed, not retried
    assert s2.last_buy_slot is None


def test_daily_schedule_and_timezone_boundaries(tmp_path):
    # 00:00 UTC schedule, daily: a bar stamped Monday 00:00 UTC triggers
    # Monday's slot; Sunday 23:59 UTC still belongs to Sunday's slot.
    s = dca(tmp_path, schedule="daily", time_of_day="00:00", timezone="UTC",
            state_path=None)
    sun = datetime(2026, 1, 4, 23, 59, tzinfo=timezone.utc)
    mon = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)
    assert s.due_slot(sun) == datetime(2026, 1, 4, tzinfo=timezone.utc)
    assert s.due_slot(mon) == mon
    s.on_bar(bar(sun))                                    # anchors Sunday
    assert len(s.on_bar(bar(mon))) == 1
    assert s.on_bar(bar(mon + timedelta(hours=5))) == []
    assert len(s.on_bar(bar(mon + timedelta(days=1)))) == 1


def test_weekly_due_slot_wraps_to_previous_week(tmp_path):
    s = dca(tmp_path, state_path=None)
    assert s.due_slot(et(2026, 1, 5, 9, 59)) == et(2025, 12, 29, 10, 0)
    assert s.due_slot(et(2026, 1, 5, 10, 0)) == et(2026, 1, 5, 10, 0)
    assert s.due_slot(et(2026, 1, 11, 23, 59)) == et(2026, 1, 5, 10, 0)


def test_foreign_symbol_state_is_ignored(tmp_path):
    p = tmp_path / "dca_state.json"
    p.write_text(json.dumps({"symbol": "QQQ",
                             "last_slot": "2026-01-05T10:00:00-05:00"}))
    assert dca(tmp_path).last_slot is None
    p.write_text("not json")
    assert dca(tmp_path).last_slot is None


def test_warmup_does_not_trigger_catch_up(tmp_path):
    """Priming with history must not treat that history's slots as missed
    downtime and buy on the first live bar after a past slot."""
    s = dca(tmp_path, warmup_bars=5)
    s.prime(minute_bars(et(2025, 12, 29, 9, 30), 5))     # last week's history
    assert feed(s, minute_bars(et(2026, 1, 5, 9, 35), 20)) == []
    assert len(feed(s, minute_bars(et(2026, 1, 5, 10, 0), 3))) == 1


def test_dca_config_fields_validated(tmp_path):
    from mini_prop_os.core.config import ConfigError, load_config
    p = tmp_path / "c.yaml"
    p.write_text("strategy: {name: scheduled_dca, order_quantity: 10}\n")
    cfg = load_config(p)
    assert cfg.strategy.dca_schedule == "weekly"
    assert cfg.strategy.dca_weekday == "Monday"
    assert cfg.strategy.dca_time == "10:00"
    assert cfg.strategy.dca_timezone == "America/New_York"
    for bad, match in (("dca_schedule: monthly", "dca_schedule"),
                       ("dca_weekday: Funday", "dca_weekday"),
                       ("dca_time: '25:00'", "dca_time"),
                       ("dca_timezone: Mars/Olympus", "dca_timezone"),
                       ("dca_amount: -1", "dca_amount")):
        p.write_text(f"strategy: {{name: scheduled_dca, {bad}}}\n")
        with pytest.raises(ConfigError, match=match):
            load_config(p)


def test_shipped_dca_paper_config_builds_the_strategy():
    pytest.importorskip("ib_insync")
    from mini_prop_os.app import build_strategy
    from mini_prop_os.core.config import load_config
    repo = Path(__file__).resolve().parents[1]
    cfg = load_config(repo / "deploy" / "config.tfsa-paper-dca.yaml")
    s = build_strategy(cfg)
    assert isinstance(s, ScheduledDcaStrategy)
    assert s.quantity == cfg.risk.max_order_quantity == 10
    assert cfg.connection.port == 4002 and cfg.contract.sec_type == "STK"
