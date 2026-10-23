"""Deterministic synthetic market scenarios for engine / same-path tests."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from ftmo_bot.backtest.engine import MarketData, Ticks, ticks_from_frame
from ftmo_bot.config import FtmoProfile
from ftmo_bot.strategy.base import Bar

PRAGUE = ZoneInfo("Europe/Prague")
DAY = date(2026, 3, 4)  # Wednesday, CET


def utc(day: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=PRAGUE).astimezone(UTC)


def h4_up(symbol: str, end: datetime, base: float, step: float, n: int = 80) -> list[Bar]:
    start = end - timedelta(hours=4 * n)
    return [
        Bar(
            symbol,
            start + timedelta(hours=4 * i),
            base + step * i,
            base + step * i + step / 2,
            base + step * i - step / 2,
            base + step * i,
            240,
        )
        for i in range(n)
    ]


def day_bars(
    symbol: str,
    day: date,
    hi: float,
    lo: float,
    breakout_close: float,
    range_window: tuple[int, int] = (0, 8),
    breakout_at: tuple[int, int] = (9, 0),
) -> list[Bar]:
    bars = []
    t = utc(day, range_window[0])
    while t < utc(day, range_window[1]):
        bars.append(Bar(symbol, t, (hi + lo) / 2, hi, lo, (hi + lo) / 2))
        t += timedelta(minutes=15)
    c = breakout_close
    bars.append(
        Bar(
            symbol,
            utc(day, *breakout_at),
            c - 0.0002 * (hi - lo) / 0.002,
            c,
            c - 0.0003 * (hi - lo) / 0.002,
            c,
        )
    )
    return bars


def path_ticks(
    start: datetime,
    points: Sequence[tuple[float, float]],
    spread: float,
    every: timedelta = timedelta(seconds=10),
) -> pd.DataFrame:
    """Piecewise-linear bid path: ``points`` are (minutes from start, bid)."""
    mins = np.array([p[0] for p in points], float)
    bids = np.array([p[1] for p in points], float)
    n = int(mins[-1] * 60 / every.total_seconds()) + 1
    t_min = np.arange(n) * every.total_seconds() / 60
    bid = np.interp(t_min, mins, bids)
    ts = pd.date_range(start, periods=n, freq=every)
    return pd.DataFrame({"ts_utc": ts, "bid": bid, "ask": bid + spread})


class DictTicks:
    def __init__(self, frames: dict[tuple[str, date], pd.DataFrame], profile: FtmoProfile):
        self._t = {k: ticks_from_frame(v, profile.contracts[k[0]]) for k, v in frames.items()}

    def __call__(self, symbol: str, day: date) -> Ticks | None:
        return self._t.get((symbol, day))


def eurusd_market(
    profile: FtmoProfile,
    path: Sequence[tuple[float, float]],
    spread: float = 0.0001,
    extra: dict[str, tuple[list[Bar], list[Bar], pd.DataFrame]] | None = None,
) -> MarketData:
    """EURUSD range 1.0990–1.1010, uptrend, breakout bar 09:00 closing 1.1015.

    ``path`` is the bid path from 09:15 local (the entry tick) onward.
    """
    sym = "EURUSD"
    bars15 = {sym: day_bars(sym, DAY, 1.1010, 1.0990, 1.1015)}
    bars4h = {sym: h4_up(sym, utc(DAY, 9), 1.05, 0.0010)}
    frames = {(sym, DAY): path_ticks(utc(DAY, 9, 15), path, spread)}
    for s, (b15, b4, ticks) in (extra or {}).items():
        bars15[s] = b15
        bars4h[s] = b4
        frames[(s, DAY)] = ticks
    return MarketData(bars15, bars4h, DictTicks(frames, profile))


SESSION_START = {"EURUSD": (9, 0), "GBPUSD": (9, 0), "NAS100": (15, 30), "XAUUSD": (14, 0)}
SCALE = {
    "EURUSD": (1.08, 1.0),
    "GBPUSD": (1.25, 1.0),
    "NAS100": (15_000.0, 10_000.0),
    "XAUUSD": (1_900.0, 1_000.0),
}


def structured_day(symbol: str, day: date, level: float, win: bool) -> pd.DataFrame:
    """One UTC day of 10 s ticks: a 15-minute sine (±10 "pips") around ``level``
    (so every 15m bar has a full 20-pip true range), then at session start a ramp
    that breaks the range upward and either runs to +6.5R-ish (win) or reverses
    through the range low (loss). Offsets are in EURUSD units × SCALE."""
    _, k = SCALE[symbol]
    ts = pd.date_range(datetime(day.year, day.month, day.day, tzinfo=UTC), periods=8640, freq="10s")
    local = ts.tz_convert(PRAGUE)
    mins = np.asarray(local.hour * 60 + local.minute + local.second / 60, float)
    hh, mm = SESSION_START[symbol]
    s0 = hh * 60 + mm
    off = 0.0010 * np.sin(2 * np.pi * mins / 15)
    ramp_up = np.interp(mins, [s0, s0 + 14, s0 + 90], [0.0, 0.0015, 0.0080])
    ramp_dn = np.interp(mins, [s0, s0 + 14, s0 + 60], [0.0, 0.0015, -0.0020])
    in_sess = mins >= s0
    off = np.where(in_sess, ramp_up if win else ramp_dn, off)
    bid = level + off * k
    return pd.DataFrame(
        {"ts_utc": ts.astype("datetime64[ns, UTC]"), "bid": bid, "ask": bid + 0.0001 * k}
    )


def write_structured_market(raw: Path, start: date, days: int, seed: int = 7) -> None:
    from ftmo_bot.data.dukascopy import day_path

    rng = np.random.default_rng(seed)
    for sym, (p0, k) in SCALE.items():
        for i in range(days):
            d = start + timedelta(days=i)
            df = structured_day(sym, d, p0 + 0.0030 * k * i, bool(rng.random() < 0.55))
            p = day_path(raw, sym, d)
            p.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(p, index=False)
