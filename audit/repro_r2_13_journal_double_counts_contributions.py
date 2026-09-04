"""R2 #13 — LOW (round-1 unproven suspicion, now proven): daily_run journals
the SAME contribution again on every refused/halted run.

main() records `journal.record("contribution", amount=...)` BEFORE run_cycle
runs. When run_cycle refuses (halted engine, bad data...), state is never
saved, so last_equity_date does not advance and the next scheduled run
re-derives the same Mondays — and journals the same deposit again. The
journal is the system's evidence (§11): after N halted days it shows N
deposits where the schedule owed one.
"""
import sys, tempfile
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import pandas as pd

import daily_run
from engine.state import EngineState, StateStore

# --- sandbox daily_run: temp state/report dirs, stub journal, offline prices
tmp = Path(tempfile.mkdtemp())
(tmp / "state").mkdir()
daily_run.STATE_PATH = tmp / "state" / "paper_state.json"
daily_run.REPORTS_DIR = tmp / "reports"

events: list[tuple[str, dict]] = []


class StubJournal:
    def __init__(self, path):
        pass

    def record(self, event_type, **payload):
        events.append((event_type, payload))


daily_run.Journal = StubJournal
idx = pd.bdate_range(end=pd.Timestamp(date.today()), periods=300)
daily_run.fetch_prices = lambda symbols: pd.DataFrame(
    100.0, index=idx, columns=list(symbols))

# A halted engine whose last recorded equity is 8 days ago (>= 1 Monday since).
last = date.today() - timedelta(days=8)
StateStore(daily_run.STATE_PATH).save(EngineState(
    halted=True, halt_reason="drawdown kill",
    last_equity_date=last.isoformat(), cash=0.0))

owed = daily_run.contributions_due(
    EngineState(last_equity_date=last.isoformat()), date.today())
print(f"deposits actually owed since {last}: {owed:.0f}")

rc1 = daily_run.main()   # refused (halted) — journals the contribution anyway
rc2 = daily_run.main()   # next scheduled run: same state, same Mondays again
contribs = [p["amount"] for t, p in events if t == "contribution"]
print(f"return codes: {rc1}, {rc2}")
print(f"'contribution' events journaled: {contribs} "
      f"(total {sum(contribs):.0f} vs owed {owed:.0f})")

assert sum(contribs) <= owed, (
    f"BUG CONFIRMED: two refused runs journaled {sum(contribs):.0f} of "
    f"deposits when the schedule owed {owed:.0f} — the journal (the §11 "
    "evidence record) double-counts the same Monday's $100 on every "
    "halted/refused day, because 'contribution' is recorded before run_cycle "
    "and state never advances on a refusal"
)
print("fixed: refused runs no longer journal phantom deposits")
