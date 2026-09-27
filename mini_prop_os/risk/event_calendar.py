"""Scheduled-event blackouts: stand aside when volatility is pre-announced.

Why a calendar instead of a news model
--------------------------------------
Research pairing LLM news sentiment with allocation (HARLF and similar) is
aimed at multi-asset portfolios rebalancing daily or slower, where "which
assets look favoured this week" is the decision. This system trades one
futures contract on minute bars, so that framing does not transfer.

What *does* transfer is the underlying insight: information outside price
history predicts risk. For an intraday trend-follower, the highest-value and
most reliable slice of that is the economic calendar. FOMC, CPI, and NFP
releases produce instant multi-point gaps in the S&P complex, and a
trend-following entry taken seconds before one is a coin flip with the
strategy's edge removed and its tail risk multiplied.

A calendar beats a live news model here on every axis that matters in the
trade path: it is deterministic, needs no network call while trading, adds
no latency, cannot hallucinate, and the timings are published weeks ahead.
An LLM reading headlines in real time would add seconds of latency and a
failure mode (a confident misread) directly inside the order path.

Blackouts suppress **new entries only**. Exits, risk-flattening, and the
kill switch are never blocked — being unable to leave a position during a
CPI print is precisely the risk this module exists to avoid.

Pure stdlib; no network access at trade time.
"""

from __future__ import annotations

import json
import logging
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

log = logging.getLogger(__name__)


class EventImpact(str, Enum):
    """How violently a release typically moves the S&P complex."""

    HIGH = "HIGH"      # FOMC, CPI, NFP: multi-point instant gaps
    MEDIUM = "MEDIUM"  # PPI, retail sales, GDP revisions
    LOW = "LOW"        # minor releases, usually ignorable


@dataclass(frozen=True)
class ScheduledEvent:
    """One calendar entry.

    Args:
        name: human label, e.g. "CPI" — used in logs and blackout reasons.
        timestamp: release time. **Must be timezone-aware**; a naive
            datetime is rejected rather than silently assumed to be UTC,
            because an hour's drift here means trading straight into the
            release it was meant to avoid.
        impact: severity, which selects the blackout width.
    """

    name: str
    timestamp: datetime
    impact: EventImpact = EventImpact.HIGH

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("event name must be non-empty")
        if self.timestamp.tzinfo is None:
            raise ValueError(
                f"event {self.name!r} has a naive timestamp; supply a "
                f"timezone-aware datetime so blackout windows cannot drift")


@dataclass(frozen=True)
class BlackoutWindow:
    """Minutes of standing aside either side of a release, by impact."""

    high_before_minutes: float = 15.0
    high_after_minutes: float = 15.0
    medium_before_minutes: float = 5.0
    medium_after_minutes: float = 5.0
    low_before_minutes: float = 0.0
    low_after_minutes: float = 0.0

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} must be >= 0")

    def span(self, impact: EventImpact) -> tuple[float, float]:
        if impact is EventImpact.HIGH:
            return self.high_before_minutes, self.high_after_minutes
        if impact is EventImpact.MEDIUM:
            return self.medium_before_minutes, self.medium_after_minutes
        return self.low_before_minutes, self.low_after_minutes


class EventCalendar:
    """Scheduled events plus the blackout test the strategy layer calls.

    Events are held sorted so lookups stay O(log n) even with years of
    calendar loaded; this runs on every bar.
    """

    def __init__(self, events: Iterable[ScheduledEvent] = (),
                 window: Optional[BlackoutWindow] = None) -> None:
        self.window = window or BlackoutWindow()
        self._events: List[ScheduledEvent] = sorted(
            events, key=lambda e: e.timestamp)
        self._starts: List[datetime] = []
        self._reindex()

    def _reindex(self) -> None:
        """Precompute blackout start times for binary search."""
        self._starts = [
            e.timestamp - timedelta(minutes=self.window.span(e.impact)[0])
            for e in self._events
        ]

    def __len__(self) -> int:
        return len(self._events)

    @property
    def events(self) -> Sequence[ScheduledEvent]:
        return tuple(self._events)

    def add(self, event: ScheduledEvent) -> None:
        """Insert an event, keeping the calendar sorted."""
        idx = bisect_left([e.timestamp for e in self._events],
                          event.timestamp)
        self._events.insert(idx, event)
        self._reindex()

    def active_event(self, now: datetime) -> Optional[ScheduledEvent]:
        """The event whose blackout window contains ``now``, if any.

        Raises:
            ValueError: if ``now`` is timezone-naive — comparing it against
                aware event times would raise deep in the trade path.
        """
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        if not self._events:
            return None
        # Every window that could contain `now` starts at or before it.
        idx = bisect_left(self._starts, now)
        # Scan back over candidates; windows may overlap, so check a few.
        for i in range(idx, -1, -1):
            if i >= len(self._events):
                continue
            event = self._events[i]
            before, after = self.window.span(event.impact)
            start = event.timestamp - timedelta(minutes=before)
            end = event.timestamp + timedelta(minutes=after)
            if start <= now <= end:
                return event
            if end < now - timedelta(days=1):
                break  # far enough back that nothing earlier can match
        return None

    def is_blackout(self, now: datetime) -> bool:
        """True when new entries should be suppressed."""
        return self.active_event(now) is not None

    def next_event(self, now: datetime) -> Optional[ScheduledEvent]:
        """The next event at or after ``now`` (for logging and previews)."""
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        idx = bisect_left([e.timestamp for e in self._events], now)
        return self._events[idx] if idx < len(self._events) else None

    # ------------------------------------------------------------ loading

    @classmethod
    def from_records(cls, records: Iterable[dict],
                     window: Optional[BlackoutWindow] = None) -> "EventCalendar":
        """Build from dicts of ``{name, timestamp, impact}``.

        ``timestamp`` is ISO-8601 and must carry an offset (``...Z`` or
        ``+00:00``). Entries missing required fields raise rather than being
        skipped: a silently dropped FOMC entry is worse than a failed load.
        """
        events = []
        for i, rec in enumerate(records):
            try:
                name = rec["name"]
                raw = rec["timestamp"]
            except (KeyError, TypeError) as exc:
                raise ValueError(
                    f"calendar record {i} missing required field: {exc}"
                ) from exc
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            impact = EventImpact(str(rec.get("impact", "HIGH")).upper())
            events.append(ScheduledEvent(name=name, timestamp=ts,
                                         impact=impact))
        return cls(events, window)

    @classmethod
    def from_file(cls, path: str | Path,
                  window: Optional[BlackoutWindow] = None) -> "EventCalendar":
        """Load a JSON list of event records.

        A missing file yields an **empty** calendar (blackouts simply never
        fire) rather than an error, so an operator who has not populated one
        can still trade — but a malformed file raises, because a
        half-understood calendar is a false sense of safety.
        """
        p = Path(path)
        if not p.is_file():
            log.warning("no event calendar at %s; blackouts disabled", p)
            return cls((), window)
        try:
            data = json.loads(p.read_text())
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed event calendar {p}: {exc}") from exc
        if not isinstance(data, list):
            raise ValueError(f"event calendar {p} must contain a JSON list")
        cal = cls.from_records(data, window)
        log.info("loaded %d scheduled events from %s", len(cal), p)
        return cal

    def prune(self, before: datetime) -> int:
        """Drop events older than ``before``; returns how many were removed."""
        if before.tzinfo is None:
            raise ValueError("before must be timezone-aware")
        keep = [e for e in self._events if e.timestamp >= before]
        removed = len(self._events) - len(keep)
        self._events = keep
        self._reindex()
        return removed
