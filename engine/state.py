"""Durable, atomic state (§3.7, §5.5).

Writes are atomic: temp file in the same directory + fsync + os.replace,
then the previous good file is kept as a validated backup. Every file
carries a sha256 checksum so a torn or tampered file fails closed.

An unreadable state file is a refusal to trade (StateError) — never a
reset to defaults. In particular, a torn file can never read as
halted=False.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .errors import StateError

SCHEMA_VERSION = 1


@dataclass
class EngineState:
    schema_version: int = SCHEMA_VERSION
    halted: bool = False                 # hard kill fired; manual reset only (§7)
    halt_reason: str = ""
    peak_equity: float = 0.0
    last_equity: float = 0.0
    last_equity_date: str = ""           # ISO date of last_equity
    last_completed_period: str = ""      # e.g. "2026-08" once a rebalance CONVERGED (§5.9)
    rebalance_retries: int = 0
    positions: dict = field(default_factory=dict)   # symbol -> shares (engine's view; cross-checked vs broker)
    cash: float = 0.0


def _checksum(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _serialize(state: EngineState) -> str:
    body = json.dumps(asdict(state), sort_keys=True)
    return json.dumps({"body": body, "sha256": _checksum(body)})


def _deserialize(text: str) -> EngineState:
    outer = json.loads(text)
    body = outer["body"]
    if _checksum(body) != outer["sha256"]:
        raise ValueError("checksum mismatch")
    data = json.loads(body)
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version {data.get('schema_version')}")
    known = {f for f in EngineState.__dataclass_fields__}
    if set(data) != known:
        raise ValueError("state fields do not match schema")
    return EngineState(**data)


class StateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.backup_path = self.path.with_suffix(self.path.suffix + ".bak")

    def load(self, *, allow_fresh: bool = False) -> EngineState:
        """Load state. Unreadable state is a StateError, never defaults.

        A fresh (no file at all, no backup) state is only permitted when the
        caller explicitly passes allow_fresh=True (first-run bootstrap).
        """
        main_exists = self.path.exists()
        bak_exists = self.backup_path.exists()

        if not main_exists and not bak_exists:
            if allow_fresh:
                return EngineState()
            raise StateError(
                f"no state file at {self.path} and fresh start not permitted; "
                "run bootstrap explicitly if this is genuinely a first run"
            )

        errors = []
        if main_exists:
            try:
                return _deserialize(self.path.read_text())
            except Exception as exc:  # torn/corrupt main — try validated backup
                errors.append(f"main: {exc}")
        if bak_exists:
            try:
                state = _deserialize(self.backup_path.read_text())
                # Backup is one save behind; using it is safe only because every
                # field that must never regress (halted) is checked by callers
                # against both. Halted in EITHER copy means halted.
                if main_exists:
                    state = self._merge_halt_flags(state)
                return state
            except Exception as exc:
                errors.append(f"backup: {exc}")
        raise StateError(
            "state unreadable — refusing to trade (never resetting to defaults): "
            + "; ".join(errors)
        )

    def _merge_halt_flags(self, state: EngineState) -> EngineState:
        # If the corrupt main file still contains a legible halted:true anywhere
        # in its bytes, honor it. Cheap, conservative, and errs toward halting.
        try:
            raw = self.path.read_text(errors="replace")
            if '"halted": true' in raw or '\\"halted\\": true' in raw:
                state.halted = True
                state.halt_reason = state.halt_reason or "halt flag recovered from corrupt state file"
        except OSError:
            pass
        return state

    def save(self, state: EngineState) -> None:
        payload = _serialize(state)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        # Preserve the current good file as the validated backup before replace.
        if self.path.exists():
            try:
                _deserialize(self.path.read_text())  # only back up a VALID file
                os.replace(self.path, self.backup_path)
            except Exception:
                pass  # never back up a corrupt file over a good backup
        os.replace(tmp, self.path)
        self._fsync_dir()

    def _fsync_dir(self) -> None:
        try:
            fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass
