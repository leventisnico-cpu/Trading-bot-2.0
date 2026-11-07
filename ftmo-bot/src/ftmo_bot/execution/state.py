"""Persisted live state shared by the guard and the runner (via files only).

``state/`` holds:
- ``daily_baseline.json`` — equity at 00:00 CE(S)T (written by the guard only)
- ``heartbeat`` — ISO timestamp the guard rewrites every poll
- ``HALT`` — JSON halt record; a daily halt is cleared by the guard at the next
  reset, an overall halt only by a human deleting the file
- ``idempotency.json`` — keys ``symbol|session_date|side`` persisted BEFORE
  an order is sent
- ``runner.json`` — runner bookkeeping (consecutive losses, breakeven done,
  original stops)

Every write is atomic (temp file + ``os.replace``) and fsynced, so a crash can
never leave a half-written file that the other process misreads.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ftmo_bot.risk.ftmo_rules import Baseline


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


@dataclass(frozen=True)
class HaltRecord:
    kind: str  # "daily" | "overall" | "manual"
    reason: str
    day: date
    at_utc: datetime


@dataclass
class RunnerState:
    day: date | None = None
    consecutive_losses: int = 0
    breakeven_done: list[int] = field(default_factory=list)
    original_stops: dict[str, float] = field(default_factory=dict)  # ticket -> stop
    known_tickets: list[int] = field(default_factory=list)
    last_bar_ts: dict[str, str] = field(default_factory=dict)  # symbol -> ISO open ts
    summary_sent_for: str | None = None


class StateStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ baseline

    @property
    def baseline_path(self) -> Path:
        return self.root / "daily_baseline.json"

    def load_baseline(self) -> Baseline | None:
        if not self.baseline_path.exists():
            return None
        d = json.loads(self.baseline_path.read_text())
        return Baseline(
            day=date.fromisoformat(d["day"]),
            equity=float(d["equity"]),
            taken_at_utc=datetime.fromisoformat(d["taken_at_utc"]),
            late=bool(d.get("late", False)),
        )

    def save_baseline(self, b: Baseline) -> None:
        atomic_write(
            self.baseline_path,
            json.dumps(
                {
                    "day": b.day.isoformat(),
                    "equity": b.equity,
                    "taken_at_utc": b.taken_at_utc.isoformat(),
                    "late": b.late,
                }
            ),
        )

    # ------------------------------------------------------------ heartbeat

    @property
    def heartbeat_path(self) -> Path:
        return self.root / "heartbeat"

    def write_heartbeat(self, now_utc: datetime) -> None:
        atomic_write(self.heartbeat_path, now_utc.isoformat())

    def heartbeat_age(self, now_utc: datetime) -> float | None:
        """Seconds since the guard's last heartbeat; None if missing/corrupt."""
        try:
            ts = datetime.fromisoformat(self.heartbeat_path.read_text().strip())
        except (FileNotFoundError, ValueError):
            return None
        return (now_utc - ts).total_seconds()

    def heartbeat_fresh(self, now_utc: datetime, max_age_s: float) -> bool:
        age = self.heartbeat_age(now_utc)
        return age is not None and -max_age_s <= age <= max_age_s

    # ------------------------------------------------------------ HALT

    @property
    def halt_path(self) -> Path:
        return self.root / "HALT"

    def read_halt(self) -> HaltRecord | None:
        if not self.halt_path.exists():
            return None
        try:
            d = json.loads(self.halt_path.read_text())
            return HaltRecord(
                d["kind"],
                d["reason"],
                date.fromisoformat(d["day"]),
                datetime.fromisoformat(d["at_utc"]),
            )
        except (ValueError, KeyError):
            # Unreadable HALT (e.g. a human `touch`ed it) is still a halt.
            return HaltRecord("manual", "unparseable HALT file", date.min, datetime.min)

    def write_halt(self, rec: HaltRecord) -> None:
        atomic_write(
            self.halt_path,
            json.dumps(
                {
                    "kind": rec.kind,
                    "reason": rec.reason,
                    "day": rec.day.isoformat(),
                    "at_utc": rec.at_utc.isoformat(),
                }
            ),
        )

    def clear_daily_halt(self, today: date) -> bool:
        """Remove a DAILY halt from a previous day. Never touches overall/manual."""
        rec = self.read_halt()
        if rec is not None and rec.kind == "daily" and rec.day < today:
            self.halt_path.unlink(missing_ok=True)
            return True
        return False

    # ------------------------------------------------------------ idempotency

    @property
    def keys_path(self) -> Path:
        return self.root / "idempotency.json"

    def _keys(self) -> list[str]:
        if not self.keys_path.exists():
            return []
        keys: list[str] = json.loads(self.keys_path.read_text())
        return keys

    def has_key(self, key: str) -> bool:
        return key in self._keys()

    def add_key(self, key: str) -> None:
        keys = self._keys()
        if key not in keys:
            keys.append(key)
            atomic_write(self.keys_path, json.dumps(keys[-5000:]))

    # ------------------------------------------------------------ runner

    @property
    def runner_path(self) -> Path:
        return self.root / "runner.json"

    def load_runner(self) -> RunnerState:
        if not self.runner_path.exists():
            return RunnerState()
        d: dict[str, Any] = json.loads(self.runner_path.read_text())
        day = d.pop("day", None)
        return RunnerState(day=date.fromisoformat(day) if day else None, **d)

    def save_runner(self, st: RunnerState) -> None:
        d = dict(st.__dict__)
        d["day"] = st.day.isoformat() if st.day else None
        atomic_write(self.runner_path, json.dumps(d))


def idempotency_key(symbol: str, session_date: str, side: str) -> str:
    return f"{symbol}|{session_date}|{side}"
