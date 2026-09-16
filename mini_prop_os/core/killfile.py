"""Persistent kill-switch marker.

The in-memory kill switch in ``risk/guardrails.py`` halts a running
process, but an unattended restart (crash loop, supervisor, reboot) would
otherwise come back up trading as if nothing happened. When the kill
switch fires, the app writes a marker file; ``main.py`` refuses to start
trading while the marker exists. Clearing it is an explicit operator
action (``--reset-kill-switch <operator>``) so every reset is
attributable, mirroring ``RiskGuardrails.reset``.

Pure module (stdlib only) so it is unit-testable in CI.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


def write_kill_marker(path: Path, reason: str) -> None:
    """Persist a fired kill switch. Failures are logged, never raised —
    marker writing must not interfere with the flatten-and-halt path."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "reason": reason,
            "tripped_at": datetime.now(timezone.utc).isoformat(),
        }, indent=2) + "\n")
        log.critical("kill-switch marker written: %s", path)
    except OSError:
        log.exception("failed writing kill-switch marker %s", path)


def read_kill_marker(path: Path) -> Optional[dict]:
    """Return the marker's contents, or None if no marker exists.

    A marker that exists but cannot be parsed still blocks trading —
    an unreadable halt record is a reason to stop, not to proceed.
    """
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            return data
        return {"reason": f"malformed marker content: {data!r}"}
    except (OSError, json.JSONDecodeError) as exc:
        return {"reason": f"unreadable marker ({exc})"}


def clear_kill_marker(path: Path, operator: str) -> bool:
    """Operator-attributed reset; returns True if a marker was removed."""
    if not operator:
        raise ValueError("kill-switch reset requires an operator tag")
    marker = read_kill_marker(path)
    if marker is None:
        log.info("no kill-switch marker at %s; nothing to reset", path)
        return False
    log.warning("kill-switch marker cleared by %s (was: %s, tripped %s)",
                operator, marker.get("reason", "-"),
                marker.get("tripped_at", "-"))
    path.unlink(missing_ok=True)
    return True
