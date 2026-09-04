"""R2 #14 — LOW: the interrupted-save wedge kills the daily job with a raw
traceback and NO report — the refusal contract only covers half the paths.

StateStore.save() has a real crash window between its two os.replace calls
(main renamed to .bak, new file not yet in place). The stricter round-1
load() correctly refuses that layout — but daily_run.main() calls
store.load() (line `state_preview = store.load()`) OUTSIDE its
try/except HaltError, so the StateError (a HaltError subclass the handler
was built for!) escapes main() entirely: no "REFUSED TO TRADE" report is
written, no journal 'refusal' entry is made, and the scheduled job dies
with a traceback. Every other refusal path writes the report; the one that
requires the most urgent human attention writes nothing.
"""
import sys, tempfile
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import pandas as pd

import daily_run
from engine.errors import StateError
from engine.state import EngineState, StateStore

tmp = Path(tempfile.mkdtemp())
(tmp / "state").mkdir()
daily_run.STATE_PATH = tmp / "state" / "paper_state.json"
daily_run.REPORTS_DIR = tmp / "reports"

events = []


class StubJournal:
    def __init__(self, path):
        pass

    def record(self, event_type, **payload):
        events.append((event_type, payload))


daily_run.Journal = StubJournal
idx = pd.bdate_range(end=pd.Timestamp(date.today()), periods=300)
daily_run.fetch_prices = lambda symbols: pd.DataFrame(
    100.0, index=idx, columns=list(symbols))

# Reproduce the exact on-disk layout of a crash inside save(): backup
# present, main missing.
store = StateStore(daily_run.STATE_PATH)
store.save(EngineState(last_equity_date="2026-08-28", cash=500.0))
daily_run.STATE_PATH.rename(store.backup_path)
assert not daily_run.STATE_PATH.exists() and store.backup_path.exists()

escaped = None
try:
    rc = daily_run.main()
    print(f"main() returned {rc}")
except StateError as exc:
    escaped = exc
    print(f"StateError ESCAPED main(): {str(exc)[:90]}...")

reports = list(daily_run.REPORTS_DIR.glob("*")) if daily_run.REPORTS_DIR.exists() else []
refusals = [p for t, p in events if t == "refusal"]
print(f"reports written: {reports}")
print(f"'refusal' journal entries: {refusals}")

assert escaped is None and reports, (
    "BUG CONFIRMED: with main state missing and a backup present (the layout "
    "save() itself can leave after a crash between its two renames), "
    "daily_run.main() dies with an uncaught StateError — no REFUSED TO TRADE "
    "report, no journal 'refusal' entry — because store.load() runs outside "
    "the try/except HaltError that exists precisely to report refusals "
    "(StateError IS a HaltError)"
)
print("fixed: the wedge produces a refusal report instead of a bare traceback")
