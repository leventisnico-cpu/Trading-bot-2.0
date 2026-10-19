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

### 2026-10-06 (Tuesday, after the close)

* **SMH:** close 632.50 (Astral daily bar), SMA50 572.98, SMA200 502.37.
  Buy level 527.49, sell level 0.95 × SMA200 = 477.26.
* **Position:** treated as held from today's open (the BUY reported on
  2026-10-05). **No order.** The close is $155.24 (24.5%) above the sell
  level; an exit needs a close below 477.26.
* **ETF scan (1Y / 6M / YTD %):** SOXX 104.4 / 71.3 / 95.7, USD (2×,
  context) 100.9 / 103.5 / 97.6, SMH 84.2 / 59.7 / 75.6, XSD 65.8 / 64.2 /
  73.6, SMHX 64.2 / 68.8 / 70.3, WTAI 51.6 / 56.6 / 56.5. Top 3 unleveraged
  by 1Y: SOXX, SMH, XSD. Nothing new beats SMH on all three (SOXX already
  swept; USD and SOXL are leveraged), so no backtest.
* **FTMO paper test:** Astral deployment 1999 (redeployed from 1949 on
  2026-10-06) and the bot shadow both made no trades today.

### 2026-10-07 (Wednesday, after the close)

* **SMH:** close 625.17, taken from the last regular-session 30-minute bar
  because Astral had not posted a daily bar for today. Astral's 2026-10-06
  daily bar had been replaced by a partial one (close 637.12 on 91k
  shares), so the 632.50 posted on 2026-10-06 was used instead.
  SMA50 574.89, SMA200 503.76, buy level 528.95, sell level 478.58.
* **Position:** held. **No order.** The close is $146.60 (23.4%) above the
  sell level.
* **ETF scan (1Y / 6M / YTD %):** SOXX 106.7 / 67.6 / 93.5, USD (2×,
  context) 101.7 / 95.7 / 95.7, SMH 85.4 / 56.3 / 73.6, XSD 66.1 / 60.9 /
  70.5, SMHX 63.8 / 65.2 / 68.0, THNQ 49.7 / 64.6 / 55.9. Top 3 unleveraged
  by 1Y: SOXX, SMH, XSD. SMHX and THNQ beat SMH on 6M only, so no backtest.
* **FTMO paper test:** no trades by Astral deployment 1999 or the bot shadow.

### 2026-10-08 (Thursday, after the close)

* **SMH:** close 606.83 (last regular-session 30-minute bar; down 2.9% on
  the day). SMA50 576.94, SMA200 505.02, buy level 530.27, sell level
  479.77.
* **Position:** held. **No order.** The close is $127.06 (20.9%) above the
  sell level.
* **Data problem in Astral's daily bars (found today):**
  - Since 2026-10-05 the daily series carries extra bars stamped 20:00 UTC
    that repeat the next session. SMH 2026-10-05T20:00 is the 10-06
    session; 2026-10-06T20:00 is the 10-07 session. IWM, QQQ and SPY show
    the same pattern.
  - Some daily bars are partial: QQQ 10-07 has 0.5M shares, SPY 10-06 has
    49k, DIA 10-02 has 117k.
  - From now on this check keeps only the midnight-stamped daily bars (one
    per date) and takes recent closes from the last regular-session
    30-minute bar.
  - The 30-minute bars the bot shadow uses are complete: 13 regular-session
    bars per day for QQQ, SPY, DIA and IWM.
* **ETF scan (1Y / 6M / YTD %):** SOXX 93.2 / 52.1 / 87.0, USD (2×,
  context) 78.9 / 68.5 / 82.9, SMH 75.5 / 43.6 / 68.6, XSD 55.7 / 47.0 /
  64.2, SMHX 52.7 / 51.7 / 61.9, THNQ 43.3 / 56.7 / 53.1. Top 3 unleveraged
  by 1Y: SOXX, SMH, XSD. Nothing new beats SMH on all three, so no
  backtest.
* **FTMO paper test:** no trades by Astral or the bot shadow.
  - A separate RSI(2) calculation from the 30-minute closes agrees: no
    symbol is below 10 (QQQ 15.8, IWM 14.5).
  - IWM closed at 277.54, just above its SMA200 of 276.71.

### 2026-10-09 (Friday): Astral paper deployment misfired (found 2026-10-12)

* **What happened:** Astral deployment 1999 (FAST-4, saved 6489) bought
  QQQ (9.833 @ 751.89) and SPY (9.499 @ 776.25) at Friday's open.
  - Its signals came from the defective daily bars noted on 2026-10-08:
    the order payloads cite bars stamped 2026-10-07T20:00Z, which are
    really the 10-08 session.
  - On clean closes, the FAST-4 rule did not fire on 10-08: RSI(2) was
    15.8 for QQQ and 32.1 for SPY. The bot shadow correctly took no trade.
* **Exit:** 10–30 seconds later Astral closed both positions as
  "protection_activation_failed" emergency exits (QQQ @ 751.54, SPY @
  776.19). The round trips lost about $4 of paper money. No positions are
  open.
* **Afterwards:** the deployment's event log shows about 20 re-activations
  between 2026-10-09 18:48Z and 2026-10-11 21:22Z.
* **Reported to Astral:** bug report d573b589-4c4c-4011-8f69-ba7ccd2c12c8,
  covering the daily-bar defects, the false entries, the failed stop
  protection and the re-activation loop.
* **Divergence verdict:** this is not a bot bug.
  - The bot reads 30-minute bars, which are complete.
  - Until Astral fixes its daily bars, deployment 1999's signals are not a
    valid check of the rule. It stays deployed (paper) so the fix can be
    seen, and its trades are logged as platform errors.

### 2026-10-09, 10-12 and 10-13 (written 2026-10-15: these daily runs were missed)

The session stalled and the daily runs for these three sessions did not
happen. The levels below are recomputed from Astral's SMH daily series
downloaded on 2026-10-14 at 20:43 UTC. That download is clean: one bar
per date, all stamped 04:00 or 05:00 UTC, and the 2026-10-06 bar matches
the 632.50 used on that day.

| session | SMH close | SMA50 | SMA200 | buy level | sell level | above sell |
|---|---|---|---|---|---|---|
| 2026-10-09 | 603.33 | 578.24 | 506.24 | 531.55 | 480.92 | $122.41 (25.5%) |
| 2026-10-12 | 590.99 | 579.25 | 507.38 | 532.74 | 482.01 | $108.98 (22.6%) |
| 2026-10-13 | 588.12 | 580.10 | 508.50 | 533.92 | 483.07 | $105.05 (21.7%) |

* **Position:** held. **No order** on any of the three days.
* **ETF scans:** missed. They cannot be rebuilt afterwards because the
  bulk performance call only returns current values.
* **FTMO paper test:** the bot shadow (caught up on 2026-10-14) planned
  nothing on these days. Astral deployment 1999 made no trades. Its event
  log shows repeated `protection_source_failed` / `source_recovered`
  episodes (QQQ, SPY, DIA, IWM price feed timeouts) on 10-12 and 10-13;
  each one cleared on its own.

### 2026-10-14 (Wednesday, after the close; written 2026-10-15)

* **SMH:** close 564.74 (Astral daily bar), SMA50 579.88, SMA200 509.49.
  Buy level 534.96, sell level 0.95 × SMA200 = 484.02.
* **Position:** held. **No order.** The close is $80.72 (16.7%) above the
  sell level.
* **ETF scan** (taken 2026-10-15 13:53 UTC, so it reflects this close;
  1Y / 6M / YTD %): SOXX 73.4 / 24.1 / 65.6, SMH 59.0 / 19.9 / 50.9, SMHX
  39.7 / 22.0 / 43.4, THNQ 36.3 / 32.9 / 41.0, XSD 33.1 / 18.4 / 44.8.
  - Top 3 unleveraged by 1Y: SOXX, SMH, SMHX.
  - Nothing unswept in the routine's list beats SMH on all three.
  - Outside that list, FTXL (First Trust Nasdaq Semiconductor, history
    since 2011) beats SMH on all three: 89.2 / 23.3 / 71.8. It has not
    been swept with the AIR3 rule. It is a candidate for the next sweep.
* **FTMO paper test: first FAST-4 signal of the test.**
  - **Bot shadow:** the plan at the close was "buy US100, buy US500" for
    Thursday's open.
  - **Independent check** from the 30-minute closes:

    | symbol | close | SMA200 | RSI(2) | signal |
    |---|---|---|---|---|
    | QQQ | 728.91 | 673.69 | 3.2 | entry |
    | SPY | 769.53 | 724.05 | 7.4 | entry |
    | IWM | 271.35 | 277.21 | 3.0 | none (below SMA200) |
    | DIA | 515.60 | 503.94 | 42.3 | none |

  - **Astral 1999 bought QQQ at 19:54 UTC (15:54 ET)**, six minutes
    before the close. It used two market orders from two runtime runs one
    second apart:
    - 10.077224 at 729.17;
    - 0.201537 at 729.197.

    The total is 10.278761 shares ($7,495), 50.0% of the $15,000 rather
    than the rule's 49%. The order payloads cite one-second live "bars"
    (open = high = low = close, volume 0), not the daily bar.
  - **Astral placed no SPY order**, although SPY met the rule at the close.
  - **Divergences:**
    1. Entry before the close instead of at the next open.
    2. SPY missed.
    3. A duplicate top-up order, despite `accumulate: false`.

    These are platform behaviour, not a bot bug: the shadow's plan matches
    the rule computed independently. A second Astral bug report was
    prepared on 2026-10-15 but not filed, because the operator declined the
    report call. The details are in this entry.
  - **Deployment health:** price-feed timeouts at 13:31 and 15:19 UTC
    cleared on their own. The deployment re-activated at 19:54 and 20:09
    UTC and was ready to trade at 20:09 UTC.

### 2026-10-15 (Thursday)

* **Morning fill check (13:52 UTC):** Astral placed no orders at the open.
  It still held QQQ 10.278761 at 729.17, and its health was ok (the QQQ
  protection feed had recovered at 13:51 UTC).
* **SMH:** close 558.76, taken from the last regular-session 30-minute bar
  because the daily bar had not posted. SMA50 579.66, SMA200 510.46. Buy
  level 535.99, sell level 484.94.
* **Position:** held. **No order.** The close is $73.82 (15.2%) above the
  sell level. SMH is 12.5% below the 2026-10-06 open (638.38) at which the
  operator was told to buy.
* **ETF scan** (routine list; 1Y / 6M / YTD %):
  - SOXX 79.0 / 28.1 / 71.0;
  - SMH 63.5 / 23.4 / 55.2;
  - SMHX 43.6 / 25.5 / 47.4;
  - THNQ 40.2 / 36.7 / 45.1;
  - XSD 38.0 / 22.7 / 50.0;
  - XLK 33.1 / 25.8 / 31.4;
  - IYW 31.6 / 26.1 / 29.6;
  - FTEC 30.2 / 24.9 / 30.0;
  - VGT 30.0 / 24.8 / 29.8;
  - WTAI 32.2 / 20.0 / 36.0;
  - CHAT 31.5 / 13.8 / 41.3;
  - AIQ 26.8 / 21.6 / 26.0;
  - QQQ 20.9 / 14.2 / 18.5;
  - context only: USD (2×) 62.6 / 20.8 / 56.8 and SOXL (3×) 168.5 / 24.9 /
    155.4.

  Top 3 unleveraged by 1Y: SOXX, SMH, SMHX. No unswept ETF beats SMH on
  all three, so there is no backtest.
* **FTMO paper test: the bot shadow's first trades.**
  - It bought at 10:05 ET:
    - QQQ 15.91 lots at 716.93, stop 688.66 (3 × ATR 9.42);
    - SPY 14.03 lots at 765.40, stop 746.15 (3 × ATR 6.42).
  - The SPY entry was cut from 23.37 lots by the combined-risk cap: the
    open stops already risked $449.82, which left $270.18 of room.
  - At the close:
    - equity 15,267.31 (+1.78%), lowest equity 14,998.89;
    - daily floor 14,250, max-loss floor 13,500, trading days 1;
    - flags ok, no tick errors.
  - **No exit planned.** Each close is below its SMA5 (QQQ 728.11 vs
    739.56; SPY 771.78 vs 775.20), and these are day 1 of 10.
  - **Astral 1999:** no new orders. It holds QQQ 10.278761 at 729.17, about
    −$10.9 at the 728.11 close. It holds no SPY.

    | symbol | bot shadow | Astral 1999 |
    |---|---|---|
    | QQQ | 15.91 @ 716.93 (10-15 10:05 ET) | 10.28 @ 729.17 (10-14 15:54 ET) |
    | SPY | 14.03 @ 765.40 (10-15 10:05 ET) | none |

    The sizing difference is by design. The timing difference and the
    missing SPY are not; they are Astral's (see 2026-10-14).

### 2026-10-16 (Friday, after the close)

* **SMH:** close 539.79, taken from the last regular-session 30-minute
  bar. SMA50 579.03, SMA200 511.35. Buy level 536.91, sell level 485.78.
  - Astral's daily series is defective again. A bar stamped
    2026-10-14T20:00Z holds the 10-15 session (close 558.76), and the
    2026-10-15 bar is partial (close 550.86).
  - The levels use the clean daily bars through 10-14 plus the 30-minute
    closes for 10-15 (558.76) and 10-16.
* **Position:** held. **No order.** The close is $54.01 (11.1%) above the
  sell level. SMH is 15.4% below the 2026-10-06 open (638.38).
* **ETF scan** (1Y / 6M / YTD %):
  - SOXX 70.7 / 21.5 / 63.8;
  - SMH 57.2 / 18.7 / 49.9;
  - SMHX 37.5 / 19.1 / 41.9;
  - THNQ 36.6 / 30.0 / 40.1;
  - XSD 32.9 / 14.4 / 43.7;
  - XLK 29.0 / 20.7 / 27.4;
  - IYW 27.9 / 21.6 / 25.8;
  - FTEC 26.7 / 20.0 / 26.2;
  - VGT 26.7 / 20.0 / 26.1;
  - WTAI 26.1 / 12.6 / 29.5;
  - CHAT 24.3 / 6.5 / 34.0;
  - AIQ 22.7 / 15.9 / 21.9;
  - QQQ 18.3 / 10.8 / 15.5;
  - context only: USD (2×) 49.4 / 11.8 / 46.6 and SOXL (3×) 130.9 / 6.0 /
    122.9.

  Top 3 unleveraged by 1Y: SOXX, SMH, SMHX. No unswept ETF beats SMH on
  all three, so there is no backtest.
* **FTMO paper test, last session:**
  - **Bot shadow:** holds QQQ 15.91 at 716.93 (stop 688.66) and SPY 14.03
    at 765.40 (stop 746.15).
    - Equity 14,863.32 (−0.91%), lowest 14,781.21.
    - Flags ok, no tick errors.
    - No exit planned: QQQ closed at 710.01 against an SMA5 of 731.31,
      SPY at 763.51 against 772.19.
  - **Astral 1999:** no trades. It still holds QQQ 10.278761 at 729.17,
    about −$197 at the 710.01 close; its position mark has stayed at
    729.197 since entry.
  - The readiness verdict is in `docs/FTMO_BOT.md` ("Result
    (2026-10-16)").

### 2026-10-19 (Monday, after the close)

* **SMH:** close 548.21, taken from the last regular-session 30-minute
  bar (the daily bar says 548.46). SMA50 578.33, SMA200 512.28. Buy level
  537.90, sell level 486.67.
  - Astral's SMH daily series is clean again: one bar per session, and
    the 10-15 and 10-16 daily closes (558.84 and 539.79) are within $0.20
    of the 30-minute closes.
* **Position:** held. **No order.** The close is $61.54 (12.6%) above the
  sell level. SMH is 14.1% below the 2026-10-06 open (638.38).
* **ETF scan** (1Y / 6M / YTD %):
  - SOXX 71.4 / 20.8 / 66.7;
  - SMH 58.0 / 18.2 / 52.3;
  - SMHX 39.6 / 18.2 / 44.5;
  - THNQ 35.4 / 28.8 / 40.3;
  - XSD 34.2 / 13.4 / 46.2;
  - XLK 29.0 / 20.4 / 29.1;
  - IYW 27.3 / 21.0 / 27.3;
  - FTEC 26.7 / 19.6 / 27.9;
  - VGT 26.3 / 19.5 / 27.7;
  - WTAI 27.3 / 13.3 / 32.2;
  - CHAT 26.0 / 7.0 / 36.3;
  - AIQ 22.8 / 16.4 / 23.8;
  - QQQ 17.5 / 10.7 / 16.9;
  - context only: USD (2×) 53.0 / 11.5 / 51.2 and SOXL (3×) 133.8 / 4.3 /
    135.0.

  Top 3 unleveraged by 1Y: SOXX, SMH, SMHX. No unswept ETF beats SMH on
  all three, so there is no backtest.
* **FTMO bot shadow** (day 3 of 10 for both trades):
  - Holds QQQ 15.91 at 716.93 (stop 688.66) and SPY 14.03 at 765.40 (stop
    746.15).
  - Equity 15,035.31 (+0.24%). Flags ok, no tick errors.
  - The day's lowest mark, 14,857.62 (−0.95%), is the opening mark at
    Friday's close. During the session equity never went below 15,002.87
    (at the 10:00 ET bar lows).
  - Astral revised Friday's last 30-minute bars after the 10-16 entry was
    written (QQQ 710.01 to 709.86, SPY 763.51 to 763.27). Friday's equity
    is therefore 14,857.62 now, not 14,863.32. Closing figures logged on
    the day can drift like this.
  - No exit planned: QQQ closed at 718.24 against an SMA5 of 725.73, SPY
    at 766.44 against 769.82.
  - No entry signal: RSI(2) is 42.3 for QQQ, 41.5 for SPY and 51.4 for
    DIA, and IWM is below its 200-day average. The independent
    computation agrees.
* **Astral 1999 sold its QQQ position mid-session, on a false signal.**
  - At 15:53:40 UTC (11:53 ET), one second after the deployment
    re-activated, it sold 10.077224 at 724.00 and 0.201537 at 724.002.
    The order reason is `strategy_rule_exit:exit QQQ`. The trade lost
    $53.15 (bought 10-14 at 729.17).
  - Cause, reconstructed from Astral's own daily bars:
    - Astral's QQQ daily series has a bar stamped 2026-10-18T20:00Z, a
      Sunday, that holds the 10-19 session.
    - Counting that bar as well as the live price pulls the 5-day average
      down to 722.95, under the 724.00 price, so the exit rule fired.
    - On the clean series the average is 726.86 and the rule is false. At
      the close QQQ (718.24) was still below its SMA5 (725.73), and the
      bot shadow correctly holds.
  - These are the same two defects as before: a duplicate daily bar, and
    a daily rule evaluated on a live price after a re-activation (the
    10-14 entry also fired at a re-activation).
  - The QQQ protection feed failed twice before the exit (14:22 and 14:55
    UTC). The DIA, IWM, QQQ and SPY feeds failed after it. The deployment
    re-activated at 20:21 UTC and reports health ok, ready to trade, and
    flat.
  - Not yet reported to Astral. The operator declined the earlier report
    call on 2026-10-15.

  | symbol | bot shadow | Astral 1999 |
  |---|---|---|
  | QQQ | 15.91 @ 716.93, open | sold 10-19 11:53 ET @ 724.00, −$53.15 |
  | SPY | 14.03 @ 765.40, open | none |
