"""Economic news events (Forex Factory weekly JSON) and the news-window test.

Forex Factory only publishes the *current* week (``ff_calendar_thisweek.json``),
so live trading caches each week as it is fetched. For historical backtests,
supply a CSV of past events (``ts_utc,currency,impact,title``) — without one the
backtest's news filter has nothing to filter and the report says so.

Holidays are NOT kept in a hand table: live, the MT5 client checks whether the
symbol is tradeable (see ``execution/mt5_client.py``).
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"


@dataclass(frozen=True)
class NewsEvent:
    ts_utc: datetime
    currency: str
    impact: str
    title: str


def parse_ff_json(text: str) -> list[NewsEvent]:
    """Parse the Forex Factory weekly JSON. Entries without a time are skipped."""
    events = []
    for item in json.loads(text):
        try:
            ts = datetime.fromisoformat(item["date"])
        except (KeyError, ValueError):
            continue
        if ts.tzinfo is None:
            continue
        events.append(
            NewsEvent(
                ts_utc=ts.astimezone(UTC),
                currency=str(item.get("country", "")).upper(),
                impact=str(item.get("impact", "")),
                title=str(item.get("title", "")),
            )
        )
    return events


def high_impact(events: Iterable[NewsEvent], impact: str = "High") -> list[NewsEvent]:
    return [e for e in events if e.impact == impact]


def _default_fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as resp:
        body: bytes = resp.read()
    return body.decode("utf-8")


def fetch_week(
    cache_dir: Path,
    now_utc: datetime,
    fetch: Callable[[str], str] = _default_fetch,
) -> Path:
    """Fetch this week's calendar and cache it as ``ff_{isoyear}-W{week}.json``.

    If the fetch fails and a cache for this week exists, the cache is kept.
    """
    year, week, _ = now_utc.isocalendar()
    path = cache_dir / f"ff_{year}-W{week:02d}.json"
    try:
        text = fetch(FF_URL)
        parse_ff_json(text)  # validate before overwriting a good cache
    except Exception:
        if path.exists():
            return path
        raise
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    tmp.replace(path)
    return path


def load_cache(cache_dir: Path) -> list[NewsEvent]:
    events: list[NewsEvent] = []
    for p in sorted(cache_dir.glob("ff_*.json")):
        events.extend(parse_ff_json(p.read_text()))
    return dedupe(events)


def load_csv(path: Path) -> list[NewsEvent]:
    df = pd.read_csv(path)
    ts = pd.to_datetime(df["ts_utc"], utc=True)
    return dedupe(
        NewsEvent(t.to_pydatetime(), str(c).upper(), str(i), str(title))
        for t, c, i, title in zip(ts, df["currency"], df["impact"], df["title"], strict=True)
    )


def dedupe(events: Iterable[NewsEvent]) -> list[NewsEvent]:
    return sorted(set(events), key=lambda e: (e.ts_utc, e.currency, e.title))


def blocked(
    events: Sequence[NewsEvent],
    currencies: Iterable[str],
    at_utc: datetime,
    window: timedelta,
) -> NewsEvent | None:
    """The first event within ±``window`` of ``at_utc`` for any of ``currencies``."""
    cur = set(currencies)
    for e in events:
        if e.currency in cur and abs(e.ts_utc - at_utc) <= window:
            return e
    return None
