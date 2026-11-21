"""Tick-data integrity checks (SPEC "Data pipeline" step 3).

Per CE(S)T trading day, over the instrument's trading session window:
- no gap > 5 min between ticks (window edges count as ticks),
- no negative spreads (bid ≤ ask) and no non-positive prices,
- tick rate per clock hour within 3σ of the symbol's median hourly rate.

Failing days are EXCLUDED and logged, never interpolated. Days with no ticks in
the session (weekends, holidays) are listed separately as non-trading days.
The report is written to ``{out_dir}/{symbol}.json``; the backtest reads its
``excluded`` list.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from ftmo_bot.config import InstrumentParams

MAX_GAP = timedelta(minutes=5)
SIGMA = 3.0


@dataclass
class DayCheck:
    day: date
    problems: list[str] = field(default_factory=list)
    hourly_rates: list[float] = field(default_factory=list)
    has_session: bool = True


def session_bounds_utc(day: date, inst: InstrumentParams, tz: str) -> tuple[datetime, datetime]:
    z = ZoneInfo(tz)
    start = datetime.combine(day, inst.session.start, tzinfo=z).astimezone(UTC)
    end = datetime.combine(day, inst.session.end, tzinfo=z).astimezone(UTC)
    return start, end


def check_day(ticks: pd.DataFrame, day: date, inst: InstrumentParams, tz: str) -> DayCheck:
    """``ticks`` may cover more than the session; only the session window is checked."""
    start, end = session_bounds_utc(day, inst, tz)
    ts = ticks["ts_utc"]
    sel = ticks[(ts >= start) & (ts < end)].sort_values("ts_utc", kind="stable")
    chk = DayCheck(day)
    if sel.empty:
        chk.has_session = False
        return chk

    bid = sel["bid"].to_numpy()
    ask = sel["ask"].to_numpy()
    if (bid > ask).any():
        chk.problems.append(f"negative spread on {(bid > ask).sum()} ticks")
    if (bid <= 0).any() or (ask <= 0).any():
        chk.problems.append("non-positive price")

    t = sel["ts_utc"].to_numpy(dtype="datetime64[ns]").astype(np.int64)
    edges = np.concatenate(([pd.Timestamp(start).value], t, [pd.Timestamp(end).value]))
    gaps = np.diff(edges)
    worst = int(gaps.max())
    if worst > MAX_GAP.total_seconds() * 1e9:
        chk.problems.append(f"gap of {worst / 6e10:.1f} min in session")

    # Tick rate per clock hour (partial hours scaled to a full hour).
    hour = pd.Timestamp(start).floor("h")
    while hour < pd.Timestamp(end):
        lo = max(hour, pd.Timestamp(start))
        hi = min(hour + pd.Timedelta(hours=1), pd.Timestamp(end))
        n = int(((sel["ts_utc"] >= lo) & (sel["ts_utc"] < hi)).sum())
        chk.hourly_rates.append(n * 3600.0 / (hi - lo).total_seconds())
        hour += pd.Timedelta(hours=1)
    return chk


def run_integrity(raw_dir: Path, inst: InstrumentParams, tz: str, out_dir: Path) -> dict[str, Any]:
    """Check every raw day file for ``inst`` and write the JSON report."""
    checks: list[DayCheck] = []
    for path in sorted((raw_dir / inst.symbol).glob("*.parquet")):
        day = date.fromisoformat(path.stem)
        ticks = pd.read_parquet(path)
        checks.append(check_day(ticks, day, inst, tz))

    rates = np.array([r for c in checks if c.has_session for r in c.hourly_rates])
    median = float(np.median(rates)) if rates.size else 0.0
    std = float(np.std(rates)) if rates.size else 0.0
    for c in checks:
        if c.has_session and std > 0:
            bad = [r for r in c.hourly_rates if abs(r - median) > SIGMA * std]
            if bad:
                c.problems.append(
                    f"hourly tick rate {min(bad):.0f}..{max(bad):.0f} outside "
                    f"{median:.0f} ± {SIGMA:.0f}σ ({std:.0f})"
                )

    failed = {c.day.isoformat(): c.problems for c in checks if c.has_session and c.problems}
    no_session = [c.day.isoformat() for c in checks if not c.has_session]
    trading = [c for c in checks if c.has_session]
    report: dict[str, Any] = {
        "symbol": inst.symbol,
        "first_day": checks[0].day.isoformat() if checks else None,
        "last_day": checks[-1].day.isoformat() if checks else None,
        "days_checked": len(checks),
        "trading_days": len(trading),
        "failed_days": len(failed),
        "failed_fraction": len(failed) / len(trading) if trading else 1.0,
        "hourly_rate_median": median,
        "hourly_rate_std": std,
        "failed": failed,
        "no_session": no_session,
        "excluded": sorted([*failed, *no_session]),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{inst.symbol}.json").write_text(json.dumps(report, indent=2))
    return report


def load_excluded(out_dir: Path, symbol: str) -> set[date]:
    path = out_dir / f"{symbol}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"no integrity report for {symbol} at {path}; run `ftmo-bot integrity` first"
        )
    return {date.fromisoformat(d) for d in json.loads(path.read_text())["excluded"]}
