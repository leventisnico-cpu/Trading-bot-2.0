"""R2 #10 — LOW: the round-1 #14 fix over-corrects — a dataset ending on the
genuine LAST TRADING DAY of a holiday-shortened month gets no decision day.

month_end_schedule's final-bar guard compares against pd.bdate_range, which
knows weekends but not exchange holidays. 2024-03-29 was Good Friday (TSX
and NYSE closed), so 2024-03-28 was the real last trading day of March 2024.
With data through April, the 2024-03-28 bar IS flagged (the period-shift
rule uses the data itself); with data ending 2024-03-28, the SAME bar is
NOT flagged — the backtest silently skips the final month's rebalance, and
where the two calendars disagree the backtest also diverges from
daily_run.is_last_trading_day_of_month (which fires on the holiday itself,
with stale data). The fix for "don't fabricate a decision day" now
suppresses a real one.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd

from engine.backtest import month_end_schedule

# Trading calendar Jan–Mar 2024; 2024-03-29 (Good Friday) is not a bar.
idx_short = pd.bdate_range("2024-01-02", "2024-03-28")
sched_short = month_end_schedule(idx_short)
short_flag = sched_short(len(idx_short) - 1)

# Same month, but the data continues into April: same bar, per the data rule.
idx_long = pd.bdate_range("2024-01-02", "2024-04-10")
idx_long = idx_long[idx_long != pd.Timestamp("2024-03-29")]
sched_long = month_end_schedule(idx_long)
i = list(idx_long).index(pd.Timestamp("2024-03-28"))
long_flag = sched_long(i)

print(f"2024-03-28 (real last trading day of March 2024; 03-29 = Good Friday)")
print(f"  flagged when it is the dataset's FINAL bar: {short_flag}")
print(f"  flagged when data continues into April:     {long_flag}")

assert short_flag == long_flag, (
    "BUG CONFIRMED: the same bar (2024-03-28, the genuine last trading day "
    "of March 2024) is a decision day when data continues but NOT when it is "
    "the final bar — the calendar guard uses business days, not trading days, "
    "so month-ends that fall before an exchange holiday are silently skipped "
    "at the dataset edge"
)
print("fixed: holiday month-ends at the dataset edge are recognized")
