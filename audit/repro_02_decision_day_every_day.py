"""BUG: scripts/daily_run.py is_last_trading_day_of_month() returns True on
essentially EVERY day of the month, because the fetched price index only
extends to *today* — so the max trading day of the current month is always
<= today. The paper account therefore rebalances on the FIRST trading day
of each month (and keeps retrying daily), not the last, breaking parity
with the backtest (which decides on the last trading day, month_end_schedule).
"""
import sys; sys.path.insert(0, "/home/user/Trading-bot-2.0")
from datetime import date
import pandas as pd
from scripts.daily_run import is_last_trading_day_of_month

# Simulate what yfinance returns when run daily: data up to and including today.
results = {}
for today in [date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 12), date(2026, 8, 31)]:
    idx = pd.bdate_range("2024-08-01", today)   # data ends at 'today', as fetched live
    results[today] = is_last_trading_day_of_month(today, idx)
    print(f"{today} ({today.strftime('%A')}): decision_day = {results[today]}")

# Aug 3 2026 is the FIRST trading day of August (Aug 1-2 are weekend).
assert results[date(2026, 8, 3)] is False, (
    "BUG CONFIRMED: the first trading day of the month is classified as the "
    "LAST trading day of the month — the live/paper engine rebalances a month "
    "early, every month, unlike the backtest (month-END schedule)")
