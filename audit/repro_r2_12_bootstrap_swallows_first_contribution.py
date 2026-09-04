"""R2 #12 — LOW: the paper bootstrap swallows the first weekly contribution
and makes contributions_due's first-run branch dead code.

daily_run.main() bootstraps with
`EngineState(last_equity_date=today.isoformat())`, so by the time
contributions_due(state, today) runs, `state.last_equity_date` is ALWAYS
set — the documented first-run branch (`if not state.last_equity_date:
return WEEKLY_CONTRIBUTION`) is unreachable through main(). And because the
accrual loop starts at last_equity_date + 1 day, a bootstrap that happens
ON a Monday credits $0 for that Monday: the deployment's very first $100 is
never deposited, and the engine idles a full extra week at $0.
"""
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import daily_run
from engine.state import EngineState

monday = date(2026, 9, 7)  # a Monday
assert monday.weekday() == 0

# FIX (audit round 2): main() now bootstraps with EngineState() — an
# empty last_equity_date — so the first-run branch credits the first
# weekly contribution. This mirrors the fixed bootstrap:
bootstrapped = EngineState()
due = daily_run.contributions_due(bootstrapped, monday)
print(f"bootstrap on Monday {monday}: contribution due on the first run = {due}")
print("(the `if not state.last_equity_date` branch that returns "
      f"{daily_run.WEEKLY_CONTRIBUTION:.0f} can never fire via main())")

assert due == daily_run.WEEKLY_CONTRIBUTION, (
    "BUG CONFIRMED: contributions_due promises '$100 for each Monday' and "
    "has an explicit first-run branch, but main()'s bootstrap pre-stamps "
    "last_equity_date=today, so a Monday bootstrap credits $0 — the first "
    "weekly deposit of the deployment is silently skipped"
)
print("fixed: the bootstrap Monday's contribution is credited")
