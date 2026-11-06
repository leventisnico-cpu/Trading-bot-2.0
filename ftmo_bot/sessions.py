"""US cash-session daily bars (09:30-16:00 New York) built from intraday
bars, so the CFD signals match the ETF sessions FAST-4 was tested on.
MT5 index CFDs trade almost around the clock and their D1 bars end at
server midnight, which is not the US close."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Iterable, List, Tuple
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
OPEN, CLOSE = time(9, 30), time(16, 0)


@dataclass(frozen=True)
class Session:
    day: date
    open: float
    high: float
    low: float
    close: float
    complete: bool


def build(bars: Iterable[Tuple[datetime, float, float, float, float]],
          minutes: int, now: datetime) -> List[Session]:
    """``bars``: (start time, tz-aware, o, h, l, c) of ``minutes``-long bars.
    A bar belongs to the session if it starts at or after 09:30 and ends at
    or before 16:00 New York time. A session is complete once ``now`` is at
    or past 16:00 on that day."""
    days: dict = {}
    for t, o, h, l, c in bars:
        local = t.astimezone(NY)
        start = local.time()
        end_minutes = local.hour * 60 + local.minute + minutes
        if start < OPEN or end_minutes > CLOSE.hour * 60:
            continue
        days.setdefault(local.date(), []).append((local, o, h, l, c))
    out = []
    now_local = now.astimezone(NY)
    for d in sorted(days):
        rows = sorted(days[d])
        complete = (now_local.date() > d
                    or (now_local.date() == d and now_local.time() >= CLOSE))
        out.append(Session(d, rows[0][1], max(r[2] for r in rows),
                           min(r[3] for r in rows), rows[-1][4], complete))
    return out
