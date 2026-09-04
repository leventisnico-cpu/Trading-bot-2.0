"""BUG: a torn (truncated) state file CAN read back as halted=False.

state.py claims: "a torn file can never read as halted=False". But if the
main file is truncated BEFORE the bytes of the halted flag (keys are sorted:
"cash", "halt_reason", "halted", ...), _merge_halt_flags finds no
'"halted": true' substring and load() silently returns the one-save-old
backup, which says halted=False. The engine then trades again after a hard kill.
"""
import sys, tempfile; sys.path.insert(0, "/home/user/Trading-bot-2.0")
from pathlib import Path
from engine.state import EngineState, StateStore

tmp = Path(tempfile.mkdtemp())
store = StateStore(tmp / "state.json")

# 1. Normal running state saved (becomes the backup on the next save).
store.save(EngineState(halted=False, peak_equity=1000.0, last_equity=1000.0))
# 2. Hard kill fires; halted state saved (previous file rotated to .bak).
store.save(EngineState(halted=True, halt_reason="drawdown 45% exceeds max",
                       peak_equity=1000.0, last_equity=550.0))
assert store.load().halted is True  # sanity: intact file reads halted

# 3. Tear: crash/disk truncation leaves only the first bytes of the main file
#    (the escaped '\\"halted\\": true' text is further into the payload).
raw = store.path.read_text()
cut = raw.index('halt_reason')          # truncate before the halted flag bytes
store.path.write_text(raw[:cut])
print("torn main file contents:", store.path.read_text()[:80], "...")

state = store.load()
print(f"load() after tear -> halted={state.halted}, reason={state.halt_reason!r}")
assert state.halted, (
    "BUG CONFIRMED: torn main file + valid stale backup loads as "
    "halted=False — the engine would resume trading after a hard kill")
