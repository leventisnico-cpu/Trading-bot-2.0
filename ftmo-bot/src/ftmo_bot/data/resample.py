"""Ticks → 15m and 4H bars, tagged in CE(S)T.

Bars are built from the BID (what MT5 charts show), aligned on UTC boundaries
(every CE(S)T offset is a whole hour, so 15m bars align identically in both
clocks; 4H bars are UTC-aligned for a constant 4-hour length across DST).

Added columns:
- ``date_cest``: Europe/Prague calendar date of the bar's open (daily-loss grouping)
- ``session``: ``"range"`` / ``"session"`` / ``""`` per the instrument's windows,
  evaluated on the bar's local open time.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from ftmo_bot.config import InstrumentParams

BAR_COLUMNS = ["ts_utc", "open", "high", "low", "close", "spread_mean", "ticks"]


def ticks_to_bars(ticks: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """OHLC (bid) + mean spread + tick count per bar. Bars without ticks are omitted."""
    if ticks.empty:
        return pd.DataFrame({c: pd.Series(dtype="float64") for c in BAR_COLUMNS}).astype(
            {"ts_utc": "datetime64[ns, UTC]", "ticks": "int64"}
        )
    df = ticks.sort_values("ts_utc", kind="stable")
    key = df["ts_utc"].dt.floor(f"{minutes}min")
    spread = df["ask"] - df["bid"]
    g = df.assign(_k=key, _s=spread).groupby("_k", sort=True)
    bars = pd.DataFrame(
        {
            "open": g["bid"].first(),
            "high": g["bid"].max(),
            "low": g["bid"].min(),
            "close": g["bid"].last(),
            "spread_mean": g["_s"].mean(),
            "ticks": g["bid"].size().astype("int64"),
        }
    )
    bars.index.name = "ts_utc"
    return bars.reset_index()[BAR_COLUMNS]


def tag_sessions(bars: pd.DataFrame, inst: InstrumentParams, tz: str) -> pd.DataFrame:
    out = bars.copy()
    local = out["ts_utc"].dt.tz_convert(tz)
    out["date_cest"] = local.dt.date
    times = local.dt.time
    out["session"] = [
        "range" if inst.range.contains(t) else "session" if inst.session.contains(t) else ""
        for t in times
    ]
    return out


def load_ticks(raw_dir: Path, symbol: str, exclude: Iterable[str] = ()) -> pd.DataFrame:
    """Concatenate the symbol's day files, skipping excluded ``YYYY-MM-DD`` UTC days.

    Only for small ranges (tests, single days): six years of ticks do not fit
    in memory, which is why ``resample_symbol`` streams one day at a time.
    """
    skip = set(exclude)
    files = sorted(p for p in (raw_dir / symbol).glob("*.parquet") if p.stem not in skip)
    frames = [f for f in (pd.read_parquet(p) for p in files) if len(f)]
    if not frames:
        from ftmo_bot.data.dukascopy import empty_ticks

        return empty_ticks()
    return pd.concat(frames, ignore_index=True)


def bars_path(bars_dir: Path, symbol: str, minutes: int) -> Path:
    label = f"{minutes // 60}h" if minutes % 60 == 0 else f"{minutes}m"
    return bars_dir / f"{symbol}_{label}.parquet"


def resample_symbol(
    raw_dir: Path,
    bars_dir: Path,
    inst: InstrumentParams,
    tz: str,
    bar_minutes: int = 15,
    trend_minutes: int = 240,
) -> dict[int, Path]:
    """Build bars one UTC day file at a time (bars never straddle a UTC midnight
    because 15m and 4H both divide 24h)."""
    if (24 * 60) % bar_minutes or (24 * 60) % trend_minutes:
        raise ValueError("bar sizes must divide 24h")
    parts: dict[int, list[pd.DataFrame]] = {bar_minutes: [], trend_minutes: []}
    for path in sorted((raw_dir / inst.symbol).glob("*.parquet")):
        ticks = pd.read_parquet(path)
        if ticks.empty:
            continue
        for minutes in parts:
            parts[minutes].append(ticks_to_bars(ticks, minutes))
    bars_dir.mkdir(parents=True, exist_ok=True)
    out: dict[int, Path] = {}
    for minutes, frames in parts.items():
        bars = (
            pd.concat(frames, ignore_index=True)
            if frames
            else ticks_to_bars(pd.DataFrame(), minutes)
        )
        bars = tag_sessions(bars, inst, tz)
        path = bars_path(bars_dir, inst.symbol, minutes)
        bars.to_parquet(path, index=False)
        out[minutes] = path
    return out
