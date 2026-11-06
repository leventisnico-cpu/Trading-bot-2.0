"""One bot process per state file.

Two ``run`` loops on one account would each execute the same plan (each
marks it done only in its own memory before the other reads the file),
and ``flat`` next to a running loop is undone at the next open. An OS
file lock held for the life of the process prevents both; the OS frees
it when the process dies, so a crash never leaves a stale lock."""

from __future__ import annotations

import os
from pathlib import Path
from typing import IO, Optional


def _lock_nt(fh: IO[str]) -> None:
    """Windows: a non-blocking lock on the file's first byte (locking past
    the end of an empty file is allowed). Raises OSError if held."""
    import msvcrt
    fh.seek(0)
    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)


def _lock_posix(fh: IO[str]) -> None:
    import fcntl
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


class InstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh: Optional[IO[str]] = None

    def acquire(self) -> bool:
        """True if this process now holds the lock; False if another does."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+", encoding="utf-8")
        try:
            (_lock_nt if os.name == "nt" else _lock_posix)(fh)
        except OSError:
            fh.close()
            return False
        self._fh = fh
        return True

    def release(self) -> None:
        if self._fh is not None:
            self._fh.close()                         # closing frees the lock
            self._fh = None


def for_state(state_path: str) -> InstanceLock:
    p = Path(state_path)
    return InstanceLock(p.with_name("ftmo_bot.lock"))
