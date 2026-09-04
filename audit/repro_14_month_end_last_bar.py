"""BUG (minor): month_end_schedule flags the FINAL bar of the dataset as a
decision day even when it is mid-month (period != NaN-shifted comparison is
always True at the last row). The backtest then runs a full decision leg
(pre_trade, strategy, order computation) on a non-month-end bar; any
refusal/halt it produces is recorded, and with a custom caller the pending
orders would fill on the next bar of a longer frame.
"""
import sys; sys.path.insert(0, "/home/user/Trading-bot-2.0")
import pandas as pd
from engine.backtest import month_end_schedule

idx = pd.bdate_range("2026-01-05", "2026-02-11")  # ends mid-February
f = month_end_schedule(idx)
days = [idx[i].date() for i in range(len(idx)) if f(i)]
print("decision days:", days)
assert str(days[-1]) != "2026-02-11", (
    "BUG CONFIRMED: 2026-02-11 (a mid-month Wednesday, merely the last row of "
    "the frame) is treated as a last-trading-day-of-month decision day")
