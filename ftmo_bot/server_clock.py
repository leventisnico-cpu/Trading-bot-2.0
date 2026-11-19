"""The MT5 server clock: which time zone the broker's bar and tick stamps use.

MetaTrader stamps bars and ticks in the server's local time, written as if
it were UTC. Brokers differ. Many run New York + 7 h all year (17:00 New
York = server midnight); others follow EU summer time (EET/EEST) or Prague
time (CET/CEST). New York + 7 and EET agree except for two to three weeks
a year, when the US and the EU change their clocks on different dates. A
wrong guess shifts every US session by an hour, and with it every close
FAST-4 reads.

So the bot measures the live offset (the server stamp of a tick known to be
fresh, minus the real UTC time) and trusts only a rule whose offset matches
it at that moment. Pure: every input is an argument.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UTC = timezone.utc
QUANTUM = 900        # server offsets are whole quarter hours
TOLERANCE = 120      # seconds; a tick older than this is not used

#: rule name -> IANA zone; None means New York + 7 hours.
RULES: Dict[str, Optional[str]] = {
    "NY+7": None,
    "EET": "Europe/Athens",     # UTC+2, UTC+3 in EU summer time
    "CET": "Europe/Prague",     # UTC+1, UTC+2 in EU summer time
    "UTC": "UTC",
}
#: preference when several rules fit the same live offset
ORDER = ("NY+7", "EET", "CET", "UTC")


def to_utc(rule: str, server: datetime) -> datetime:
    """``server``: a naive server-local time. Returns an aware UTC time."""
    zone = RULES[rule]
    if zone is None:
        return (server - timedelta(hours=7)).replace(tzinfo=NY).astimezone(UTC)
    return server.replace(tzinfo=ZoneInfo(zone)).astimezone(UTC)


def offset_at(rule: str, utc: datetime) -> timedelta:
    """Server local time minus UTC at the instant ``utc``."""
    zone = RULES[rule]
    if zone is None:
        return utc.astimezone(NY).utcoffset() + timedelta(hours=7)
    return utc.astimezone(ZoneInfo(zone)).utcoffset()


def measure(tick_server_epoch: float, utc_now: datetime) -> Optional[timedelta]:
    """Offset implied by a fresh tick, rounded to the quarter hour; None if
    the stamp is more than ``TOLERANCE`` seconds away from a quarter hour
    (the tick is stale or the PC clock is off)."""
    diff = tick_server_epoch - utc_now.timestamp()
    q = round(diff / QUANTUM) * QUANTUM
    if abs(diff - q) > TOLERANCE:
        return None
    return timedelta(seconds=q)


def matching(offset: timedelta, utc_now: datetime) -> List[str]:
    """Rules whose offset at ``utc_now`` equals ``offset``, in ``ORDER``."""
    return [r for r in ORDER if offset_at(r, utc_now) == offset]


def describe(offset: timedelta) -> str:
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    h, m = divmod(abs(minutes), 60)
    return f"UTC{sign}{h}" + (f":{m:02d}" if m else "")
