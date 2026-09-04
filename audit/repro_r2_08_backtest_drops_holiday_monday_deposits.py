"""R2 #8 — MEDIUM: the backtest silently drops every contribution that lands
on a non-trading day, while live credits all of them — the two model
DIFFERENT deposit streams for the same schedule.

run_backtest only calls `contribution(today)` for dates present in the price
index, so a $100 Monday deposit on a market holiday (Labour Day, Family Day,
Victoria Day, Thanksgiving... the TSX closes on ~5 Mondays a year) simply
never happens. daily_run.contributions_due counts every CALENDAR Monday.
Over the same 7-Monday span containing one holiday Monday, the backtest
deposits $600 while the live engine deposits $700. phase4_backtest's
headline "$0 start, $100/week" row therefore under-funds the strategy by
~$500/yr (~10% of the contribution stream) relative to the deployment it
claims to model — final-wealth numbers are not comparable with what the
paper/live engine will actually do.
"""
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import pandas as pd

from engine.backtest import run_backtest
from engine.config import load_config
from engine.state import EngineState
import daily_run

cfg = load_config(REPO / "config" / "engine.toml")

# Trading calendar for Aug 3 – Sep 18 2026, minus Labour Day (Mon 2026-09-07,
# a real TSX/NYSE holiday).
idx = pd.bdate_range("2026-08-03", "2026-09-18")
idx = idx[idx != pd.Timestamp("2026-09-07")]
prices = pd.DataFrame(100.0, index=idx, columns=["XUU.TO"])


def weekly(d: date) -> float:
    return 100.0 if d.weekday() == 0 else 0.0


class Cash:
    def target_weights(self, p, t):
        return {}


res = run_backtest(prices, Cash(), cfg, initial_equity=0.0,
                   contribution=weekly, is_decision_day=lambda i: False)

mondays = sum(1 for d in pd.date_range("2026-08-03", "2026-09-18")
              if d.weekday() == 0)
live = daily_run.contributions_due(EngineState(last_equity_date="2026-08-02"),
                                   date(2026, 9, 18))
print(f"calendar Mondays in span: {mondays}")
print(f"backtest contributions_total: {res.contributions_total:.0f}")
print(f"daily_run.contributions_due over the same span: {live:.0f}")

assert res.contributions_total == live, (
    f"BUG CONFIRMED: same $100/Monday schedule, same span — backtest "
    f"deposited {res.contributions_total:.0f} but the live engine deposits "
    f"{live:.0f}; the holiday Monday's $100 vanishes from the backtest "
    "(contribution() is only evaluated on price-index dates), so Phase 4's "
    "deployment-shape results model a different funding stream than deployment"
)
print("fixed: backtest and live agree on the deposit stream")
