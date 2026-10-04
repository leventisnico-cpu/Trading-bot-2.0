# AIR3 on SMH — daily watch log

Paper deployment: AIR3 SMH ride (5% band), Astral paper, $870 (the
size of our real starting capital), saved 6422, deployment 1924, run
01096684, account a0d10371…. Operator redeployed it at $870 on
2026-10-04 04:08 UTC, replacing deployment 1922 ($10,000, run 6456096e,
no fills).
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

## Redeployment at $870 — 2026-10-04

Operator redeployed saved 6422 at $870 (deployment 1924, run 01096684).
Rule, account and bar size unchanged (verified against the saved
strategy). Scale check: the same rule at $870 reproduces the $10k numbers
exactly — full 2014-11 → 2026-10 +1,144%, 23.6%/yr, DD −27.6%, 5 closed
+ 1 open, 80% win (bt_e7987dd3922f6737); recent 2023-11 → 2026-10
+206%, 47.6%/yr, DD −24.0% (bt_e1b69f5310b7bf80). Astral paper sizes
fractional shares, so the 95% allocation ($826.50 ≈ 1.31 SMH at the
2026-10-02 close of 630.60) is exact; a whole-share broker would hold 1
share = 72.5% of equity.

State at the 2026-10-02 close: SMA200 499.50, SMA50 569.85, buy level
524.47, sell level 474.52, close 26.2% above the 200-day, 24.8% above
the exit. In dollars: max historical DD −27.6% ≈ −$240; a full trend
break from here would cost ≈ −$205 on the ≈ $826 position before the
rule sells. First signal is evaluated at the 2026-10-05 close.

Drawbacks found and handled:
- Routines (daily watch, morning fill check, weekly re-validation,
  hourly check-in) referenced deployment 1922/run 6456096e/$10k —
  updated to 1924/01096684/$870.
- Deployment 1924's Astral notification channels are email + toast only
  (1922 also had app push). Cannot be changed from here without a
  redeploy; operator can enable push on the deployment in the Astral
  dashboard.
- Costs at this size are negligible on paper (3 bp/side ≈ $0.25); a
  live IBKR Pro order carries a $1 minimum, ≈ 12 bp/side on $826 —
  still small, but every whipsaw costs ≈ $2 in commissions plus the
  price move.

## Live-readiness build — 2026-10-04 (funds reach the TFSA 2026-10-05)

The AIR3 rule now exists in this repo as `mini_prop_os/strategy/air3_trend.py`
(registered as `air3_trend`, same 50/200-day averages and 5% bands as
Astral saved strategy 6422) with `deploy/config.tfsa-paper-air3.yaml`
(SMH, daily bars, one share, IB Gateway paper port 4002, loose $130/15%
daily-loss breaker because the rule has no stop). SMH daily closes
2007-04-12 → 2026-10-02 were added to `data/prices_us.csv` (Astral
canonical OHLCV, unadjusted). Expectancy gate on SMH
(`reports/minipropos_expectancy_smh.md`): 0/3 folds, full sample no →
NOT DEPLOYABLE, marker `DEPLOYABLE: no`; the gate measures final equity
against buy-and-hold and a cash-in-bear-markets rule loses that by
construction. Astral's broker portal does not list Interactive Brokers,
so the Astral deployment cannot execute in the TFSA; the live options
(keep the gate / execute signals by hand / amend the gate by order) are
laid out in `docs/LIVE_READINESS.md` with a Monday checklist. 12 new
tests; suite green; CI's `--all` gate on SPY stays consistent.

## Daily entries
