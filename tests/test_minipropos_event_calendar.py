"""Tests for scheduled-event blackouts."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from mini_prop_os.risk.event_calendar import (BlackoutWindow, EventCalendar,
                                              EventImpact, ScheduledEvent)

T = datetime(2026, 9, 21, 12, 30, tzinfo=timezone.utc)


def ev(name="CPI", when=T, impact=EventImpact.HIGH) -> ScheduledEvent:
    return ScheduledEvent(name=name, timestamp=when, impact=impact)


# ----------------------------------------------------------- validation

def test_naive_timestamps_are_rejected():
    """An hour of timezone drift means trading into the release it was
    meant to avoid, so a naive datetime must fail loudly."""
    with pytest.raises(ValueError, match="naive"):
        ScheduledEvent("CPI", datetime(2026, 9, 21, 12, 30))


def test_empty_event_name_rejected():
    with pytest.raises(ValueError):
        ScheduledEvent("  ", T)


def test_negative_blackout_window_rejected():
    with pytest.raises(ValueError):
        BlackoutWindow(high_before_minutes=-1.0)


def test_naive_now_is_rejected():
    cal = EventCalendar([ev()])
    with pytest.raises(ValueError):
        cal.is_blackout(datetime(2026, 9, 21, 12, 30))


# ------------------------------------------------------------- windows

@pytest.mark.parametrize("offset,blocked", [
    (-60, False), (-16, False), (-15, True), (-1, True),
    (0, True), (1, True), (15, True), (16, False), (60, False),
])
def test_blackout_spans_the_configured_window(offset, blocked):
    cal = EventCalendar([ev()])
    assert cal.is_blackout(T + timedelta(minutes=offset)) is blocked


def test_impact_selects_window_width():
    window = BlackoutWindow(high_before_minutes=30, high_after_minutes=30,
                            medium_before_minutes=5, medium_after_minutes=5,
                            low_before_minutes=0, low_after_minutes=0)
    high = EventCalendar([ev(impact=EventImpact.HIGH)], window)
    med = EventCalendar([ev(impact=EventImpact.MEDIUM)], window)
    low = EventCalendar([ev(impact=EventImpact.LOW)], window)
    probe = T - timedelta(minutes=10)
    assert high.is_blackout(probe)
    assert not med.is_blackout(probe)
    assert med.is_blackout(T - timedelta(minutes=2))
    # Zero-width windows still block exactly at the release.
    assert low.is_blackout(T)
    assert not low.is_blackout(T - timedelta(seconds=1))


def test_empty_calendar_never_blacks_out():
    cal = EventCalendar([])
    assert not cal.is_blackout(T)
    assert cal.active_event(T) is None
    assert cal.next_event(T) is None
    assert len(cal) == 0


def test_overlapping_windows_resolve_to_an_event():
    """Two releases minutes apart must not leave a gap between them."""
    cal = EventCalendar([ev("CPI", T), ev("Fed speaker",
                                          T + timedelta(minutes=20))])
    for offset in range(-15, 36):
        assert cal.is_blackout(T + timedelta(minutes=offset)), offset


def test_active_event_names_the_cause():
    cal = EventCalendar([ev("NFP", T)])
    active = cal.active_event(T + timedelta(minutes=5))
    assert active is not None and active.name == "NFP"


def test_next_event_lookahead():
    later = T + timedelta(days=2)
    cal = EventCalendar([ev("CPI", T), ev("FOMC", later)])
    assert cal.next_event(T - timedelta(days=1)).name == "CPI"
    assert cal.next_event(T + timedelta(minutes=1)).name == "FOMC"
    assert cal.next_event(later + timedelta(days=1)) is None


def test_events_stay_sorted_when_added_out_of_order():
    cal = EventCalendar([ev("late", T + timedelta(days=5))])
    cal.add(ev("early", T))
    assert [e.name for e in cal.events] == ["early", "late"]
    assert cal.is_blackout(T)


def test_prune_drops_past_events():
    cal = EventCalendar([ev("old", T - timedelta(days=30)), ev("new", T)])
    assert cal.prune(T - timedelta(days=1)) == 1
    assert [e.name for e in cal.events] == ["new"]


# ------------------------------------------------------------- loading

def test_loads_from_json_file(tmp_path):
    path = tmp_path / "cal.json"
    path.write_text(json.dumps([
        {"name": "CPI", "timestamp": "2026-09-21T12:30:00Z",
         "impact": "HIGH"},
        {"name": "PPI", "timestamp": "2026-09-22T12:30:00+00:00",
         "impact": "medium"},
    ]))
    cal = EventCalendar.from_file(path)
    assert len(cal) == 2
    assert cal.is_blackout(T)
    assert [e.impact for e in cal.events] == [EventImpact.HIGH,
                                              EventImpact.MEDIUM]


def test_missing_file_disables_blackouts_without_error(tmp_path):
    """An operator who has not populated a calendar can still trade."""
    cal = EventCalendar.from_file(tmp_path / "absent.json")
    assert len(cal) == 0 and not cal.is_blackout(T)


def test_malformed_file_raises_rather_than_trading_blind(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(ValueError, match="malformed"):
        EventCalendar.from_file(bad)
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"name": "CPI"}))
    with pytest.raises(ValueError, match="list"):
        EventCalendar.from_file(wrong)


def test_record_missing_required_field_raises():
    """A silently dropped FOMC entry is worse than a failed load."""
    with pytest.raises(ValueError, match="missing required field"):
        EventCalendar.from_records([{"name": "CPI"}])


def test_lookup_is_efficient_with_a_large_calendar():
    """This runs on every bar, so it must not scan the whole calendar."""
    events = [ev(f"e{i}", T + timedelta(days=i)) for i in range(5000)]
    cal = EventCalendar(events)
    assert cal.is_blackout(T + timedelta(days=4999))
    assert not cal.is_blackout(T + timedelta(days=2500, hours=6))
