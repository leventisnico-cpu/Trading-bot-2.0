# AIR3 on SMH — daily watch log

Paper deployment: AIR3 SMH ride (5% band), Astral paper, $10,000,
saved 6422, deployment 1922, run 6456096e, account a0d10371….
Rule: buy SMH (95% of equity) when close > 1.05×200d SMA and 50d > 200d;
sell on close < 0.95×200d. Daily bars, signal at the close, fill at the
next open. No other stop.

Routines (all into this session, all paper-only, none may deploy,
undeploy, cancel or trade without explicit operator approval):
- hourly: PR #4 CI + deployment health, orders, positions.
- weekdays 09:50 ET: fill check after the open.
- weekdays 16:40 ET: daily watch — P&L, exit distance, ETF scan, log entry.
- Sundays 18:10 ET: weekly re-validation — full sample + 3 folds + B&H.

## Baseline — 2026-10-03 (data through 2026-10-02), $10k, 1+2 bp

| Window | Return | CAGR | Max DD | Trades | Win rate |
|---|---|---|---|---|---|
| Full 2014-11 → 2026-10 | +1,144% | 23.6% | −27.6% | 5 closed + 1 open | 80% |
| Recent 2023-11 → 2026-10 | +206% | 47.6% | −24.0% | 1 closed + 1 open | 100% |

Backtests: bt_d96c6baa56bd91e8 (full), bt_fa47e1b4450cb2a0 (recent).
Folds at $100k (2026-10-03): +121% / +58% / +304%; buy-and-hold SMH
comparison pending the first weekly re-validation.

Switch history: AIR3-SOXX (saved 6054, deployment 1861) ran 2026-10-02
→ 2026-10-04 with no fills; its scheduled 10-05 entry was cancelled
before dispatch and the deployment replaced by AIR3-SMH.

## Daily entries
