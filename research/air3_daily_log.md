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

## Gate amendment, step 2: per-entry sizing (2026-10-04)

The gate now re-sizes each strategy entry to 95% of current equity
(`CompoundingLot` in `scripts/expectancy.py`), as Astral does. Results:

| symbol | folds passed | full sample | verdict |
|---|---|---|---|
| SMH | 1/3 | no (gain/DD 3.71 vs 3.72) | NOT DEPLOYABLE |
| SPY | 2/3 | YES (2) (6.95 vs 6.13, 76% of B&H gain, DD 18.9% vs 53.1%) | DEPLOYABLE |

The rule was not loosened further. On SMH AIR3 keeps under half of
buy-and-hold's gain in 2013–2020 and 2020–2026. The module stays
`DEPLOYABLE: no`. Two operator routes are in `docs/LIVE_READINESS.md`:
run AIR3 on SPY with a gate-backed approval, or keep SMH, which needs the
operator's own amendment to the review rule first. A waiver path for SMH
was built, blocked by the repo's safety reviewer (it weakens the live-
start refusal), and withdrawn. The gate now also charges IBKR's $1.00
per-order minimum at each order's actual size.

## Operator decision: SMH (2026-10-04)

The operator chose AIR3 on SMH. The gate still marks it NOT DEPLOYABLE on
SMH, so the TFSA runs it by hand from the Astral signal (route B in
`docs/LIVE_READINESS.md`) until the operator commits the review-rule
amendment that allows a signed waiver. SMH closed 630.60 on 2026-10-02,
21% above the 524.47 buy level: the first signal on Monday's close is
expected to be a BUY for Tuesday's open.

## Weekly re-validation (2026-10-04, Sunday 22:12 UTC)

Astral strategy 41110 (AIR3 SMH ride, hysteresis 5%) against 41122
(buy-and-hold SMH, aligned), $100k, 1 bp commission, 2 bp slippage.

| window | AIR3 return | AIR3 CAGR | AIR3 max DD | trades | win rate | B&H return | B&H max DD | AIR3 lower DD |
|---|---|---|---|---|---|---|---|---|
| full 2014-01 → 2026-10 | +1,144% | 23.6% | −27.6% | 5 closed + 1 open | 80% | +2,190% | −44.9% | yes |
| fold 1 2013-03 → 2018-06 | +121% | 19.5% | −18.0% | 1 + 1 open | 100% | +134% | −22.9% | yes |
| fold 2 2017-06 → 2022-08 | +58% | 11.1% | −27.6% | 3 | 67% | +99% | −37.2% | yes |
| fold 3 2021-08 → 2026-10 | +319% | 39.6% | −24.1% | 1 + 1 open | 100% | +445% | −34.9% | yes |

Against the 2026-10-04 baseline: full sample, fold 1 and fold 2 are
unchanged; fold 3 moved from +304% to +319% (AIR3) and +424% to +445%
(B&H) because the window now runs to Friday's close. **No flag:** win
rate 80% (≥ 70%), AIR3's drawdown is lower than buy-and-hold's in every
fold, nothing moved by a wide margin.

Paper deployment 1924 ($870): flat, no orders yet. SMH closed 630.60
on Friday, 21% above the 524.47 entry level with SMA50 above SMA200, so
the first evaluation at Monday's close is expected to schedule a BUY for
Tuesday's open. No exit distance applies until a position is open.

## 2026-10-04 23:10 UTC: paper deployment 1924 stopped

On the operator's choice, AIR3's Astral paper deployment 1924 was
undeployed (flat, no orders, nothing to close) so the single Astral
paper slot can run the FTMO bot's FAST-4 test (deployment 1949). AIR3
stays the TFSA plan (route B): the daily check computes SMH's levels
from Astral daily bars and reports the order. Monday 2026-10-05: if SMH
closes at or above 524.47 with SMA50 above SMA200, BUY at Tuesday's open.

### 2026-10-05 (Monday, after the close)

* **SMH:** close 633.85 (last 30-minute bar; Astral's daily bar for today
  had not posted), SMA50 571.30, SMA200 500.91. Buy level 1.05 × SMA200
  = 525.95, sell level 0.95 × SMA200 = 475.86. Close is 20.5% above the
  buy level and SMA50 > SMA200.
* **AIR3 order for the TFSA (route B): BUY SMH at Tuesday 2026-10-06's
  open.** The operator places it by hand in IBKR. Once held, the exit is
  a close below the sell level (475.86 today, 25% below the close).
* **Paper deployment:** none for AIR3 since 1924 was stopped on
  2026-10-04 (the paper slot runs the FTMO bot test, deployment 1949).
* **ETF scan (1Y / 6M / YTD %):** SOXX 104.4 / 71.3 / 95.8, USD (2×, context)
  99.4 / 101.9 / 96.1, SMH 84.6 / 60.1 / 76.0, XSD 64.0 / 62.4 / 71.8,
  SMHX 61.1 / 65.6 / 67.1, THNQ 48.9 / 67.4 / 58.4. Top 3 unleveraged by
  1Y: SOXX, SMH, XSD. Nothing new beats SMH on all three (SOXX already
  swept; USD and SOXL are leveraged), so no backtest.
