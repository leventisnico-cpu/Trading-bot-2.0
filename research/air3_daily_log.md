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
Folds at $100k (2026-10-03): +121% / +58% / +304%.

Buy-and-hold SMH benchmark (2026-10-04, strategy 41122: buy 95% once on
the first eligible bar, same warm-up, same costs):

| Window | AIR3 on SMH | Buy-and-hold SMH |
|---|---|---|
| Full 2014-11 → 2026-10 ($10k) | +1,144%, 23.6%/yr, DD −27.6%, Sharpe 0.99 | +2,212%, 30.3%/yr, DD −44.9%, Sharpe 1.00 |
| F1 2014-01 → 2018-06 ($100k) | +121%, DD −18.0% | +134%, DD −22.9% |
| F2 2018-04 → 2022-08 ($100k) | +58%, DD −27.6% | +98%, DD −37.3% |
| F3 2022-06 → 2026-09 ($100k) | +304%, DD −24.1% | +424%, DD −34.9% |

B&H wins return in every window; AIR3 wins drawdown in every window
(gap 5–17 points). Backtests: full bt_fd3c1cde41ddec00, folds
bt_0e5af4da72c629d4 / bt_c2bbfa64019a89da / bt_4c789e42603fcfc2.

Cash stretches in the full-sample AIR3 run (from the sampled curve):
2015-07 → 2016-04, 2018-10 → 2019-03, 2020-03 → 2020-05, 2022-03 →
2023-01, 2025-03 → 2025-06. Closed trades: −0.5%, +72%, +8%, +61%,
+90%; open trade since 2025-07 at +120%.

Study guide for the operator (Claude Doc):
https://claude.ai/code/artifact/2e9ffdd9-8286-4d90-8476-85de18cc4a6a

Switch history: AIR3-SOXX (saved 6054, deployment 1861) ran 2026-10-02
→ 2026-10-04 with no fills; its scheduled 10-05 entry was cancelled
before dispatch and the deployment replaced by AIR3-SMH.

## Daily entries
