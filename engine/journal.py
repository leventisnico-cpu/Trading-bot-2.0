"""Append-only event journal (§11 support).

Every decision, order, drop, fill, and error gets a line. JSONL, fsynced.
The journal is evidence, not state: the engine never reads it to decide.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


class Journal:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, event_type: str, **payload) -> None:
        line = json.dumps(
            {"ts": datetime.now(timezone.utc).isoformat(), "type": event_type, **payload},
            sort_keys=True, default=str,
        )
        with open(self.path, "a") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())


class NullJournal(Journal):
    """For backtests where journaling every synthetic order is noise."""

    def __init__(self):
        pass

    def record(self, event_type: str, **payload) -> None:
        pass
