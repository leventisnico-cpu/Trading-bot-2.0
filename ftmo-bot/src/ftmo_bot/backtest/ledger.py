"""Run ledger enforcing the overfitting controls (SPEC "Overfitting controls").

- ``insample`` may be run any time.
- ``oos`` requires an in-sample run with the SAME strategy.yaml hash, and runs
  once per hash: changing parameters after seeing OOS means re-running
  in-sample first (the OOS clock resets).
- ``holdout`` requires an OOS run with the same hash and is touched ONCE, ever.

There is deliberately no override flag. Resetting means editing the ledger by
hand, which leaves a trace in git.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SPLITS = ("insample", "oos", "holdout")


class LedgerRefusal(RuntimeError):
    pass


def _entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def check(path: Path, split: str, params_hash: str) -> None:
    if split not in SPLITS:
        raise ValueError(f"unknown split {split!r}")
    runs = _entries(path)
    done = {(r["split"], r["params_hash"]) for r in runs}
    if split == "oos":
        if ("insample", params_hash) not in done:
            raise LedgerRefusal(
                "OOS refused: no in-sample run with the current strategy.yaml "
                f"(hash {params_hash}). Run `ftmo-bot backtest --split insample` first."
            )
        if ("oos", params_hash) in done:
            raise LedgerRefusal(
                f"OOS refused: already run once with params {params_hash}. "
                "Re-running OOS with the same parameters is peeking."
            )
    if split == "holdout":
        if any(r["split"] == "holdout" for r in runs):
            raise LedgerRefusal("holdout refused: the 2026 holdout has already been touched once.")
        if ("oos", params_hash) not in done:
            raise LedgerRefusal(
                f"holdout refused: no OOS run with params {params_hash}. Run OOS first."
            )


def record(path: Path, split: str, params_hash: str, **extra: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "split": split,
        "params_hash": params_hash,
        "ts_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        **extra,
    }
    with path.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")
