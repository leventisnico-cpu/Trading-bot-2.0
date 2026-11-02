"""FTMO bot: runs FAST-4 (research/ftmo_fast_pass.md) on an FTMO MT5 account.

The research verdict for FAST-4 is NO-GO for a fast pass (about one
start date in six passes both phases within 18 months at 3% risk). With
this bot's risk controls attempts rarely breach in 2019-2026 (1%) and
often in 2011-2018 (41%), and take about two years to pass
(research/ftmo_bot_policy.md). The operator ordered it built
(2026-10-04). This package does not change those odds.

Layout:
    config.py      settings (no credentials, ever)
    sessions.py    US cash-session daily bars built from intraday bars
    fast4.py       the strategy's signals (pure)
    rules.py       FTMO limits, sizing, the near-breach guard (pure)
    broker.py      the broker interface the runner talks to
    broker_mt5.py  MetaTrader 5 adapter (the only module importing MetaTrader5)
    runner.py      the daily cycle: close phase, open phase, guard, keep-alive
"""
