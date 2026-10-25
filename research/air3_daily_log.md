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

### 2026-10-20 (Tuesday, after the close)

* **SMH:** close 546.07, taken from the last 5-minute bar. SMA50 577.87,
  SMA200 513.15. Buy level 538.81, sell level 487.49.
  - Astral's 15:30 ET 30-minute bar holds only 15:30–15:35 ET (close
    548.87, volume 102k against 1.1M the day before). The 5-minute bars
    run to 16:00. The daily bar had not posted at 16:41 ET.
* **Position:** held. **No order.** The close is $58.58 (12.0%) above the
  sell level. SMH is 14.5% below the 2026-10-06 open (638.38).
* **ETF scan** (1Y / 6M / YTD %):
  - SOXX 70.7 / 19.7 / 66.0;
  - SMH 57.4 / 17.8 / 51.7;
  - SMHX 38.9 / 16.5 / 43.9;
  - THNQ 35.8 / 28.2 / 40.7;
  - XSD 34.7 / 11.4 / 46.8;
  - XLK 28.7 / 20.0 / 28.8;
  - IYW 26.9 / 20.4 / 26.9;
  - FTEC 26.5 / 18.9 / 27.7;
  - VGT 26.2 / 18.8 / 27.6;
  - WTAI 26.6 / 12.4 / 31.5;
  - CHAT 25.1 / 5.2 / 35.3;
  - AIQ 23.2 / 17.2 / 24.2;
  - QQQ 17.3 / 11.0 / 16.8;
  - context only: USD (2×) 51.9 / 11.4 / 50.2 and SOXL (3×) 130.9 / 1.7 /
    132.1.

  Top 3 unleveraged by 1Y: SOXX, SMH, SMHX. No unswept ETF beats SMH on
  all three, so there is no backtest.
* **FTMO bot shadow: first exit signal.**
  - SPY closed at 768.53, above its SMA5 of 767.92. The plan for
    Wednesday's open is "exit US500": SPY 14.03 lots, entry 765.40, day 4.
    The trade is +$43.97 at the close.
  - QQQ holds: 717.21 against an SMA5 of 720.44 (day 4 of 10).
  - No entry signal: RSI(2) is 38.3 for QQQ, 59.9 for SPY and 90.0 for
    DIA, and IWM is below its 200-day average. The independent
    computation agrees.
  - Equity 15,048.36 (+0.32%), lowest 14,886.01 (−0.76%) at the 09:30 ET
    bar lows. Flags ok, no tick errors.
  - The SPY margin is only $0.61, so I checked the close: Astral's six
    5-minute bars for 15:30–16:00 ET add up to the 30-minute bar, and its
    daily bar also closes at 768.534.
* **Astral 1999:** no orders. It has been flat since the false QQQ exit on
  10-19.
  - Its price feed failed nine times between 13:32 and 18:32 UTC (QQQ,
    DIA, IWM), with feed delays of up to 9 minutes. It re-activated at
    17:43 and 20:07 UTC.
  - Its SPY daily series now stamps the 10-19 and 10-20 sessions
    2026-10-18T20:00Z and 2026-10-19T20:00Z.
  - Not redeployed: the faults are on Astral's side and have hit every
    deployment, and a redeploy needs the operator's approval of a preview.

### 2026-10-21 (Wednesday, after the close)

* **SMH:** close 556.75, taken from the last regular-session 30-minute
  bar (its six 5-minute bars agree). SMA50 577.55, SMA200 514.04. Buy
  level 539.75, sell level 488.34.
  - Astral's SMH daily series now has the same defect as QQQ and SPY: a
    bar stamped 2026-10-20T20:00Z holds the 10-21 session. The levels skip
    it.
  - The 10-20 daily bar has posted at 546.36, and the 30-minute bar now
    says 546.42. The 10-20 entry used 546.07 from the 5-minute bars. The
    10-20 sell level is unchanged at 487.49.
* **Position:** held. **No order.** The close is $68.40 (14.0%) above the
  sell level. SMH is 12.8% below the 2026-10-06 open (638.38).
* **ETF scan** (1Y / 6M / YTD %):
  - SOXX 75.2 / 21.3 / 69.5;
  - SMH 61.2 / 19.8 / 54.5;
  - SMHX 43.0 / 17.6 / 47.1;
  - THNQ 38.8 / 30.5 / 44.0;
  - XSD 39.8 / 11.8 / 49.8;
  - XLK 30.8 / 21.9 / 30.9;
  - IYW 28.7 / 22.7 / 28.7;
  - FTEC 28.7 / 21.1 / 29.9;
  - VGT 28.4 / 21.0 / 29.7;
  - WTAI 29.2 / 14.3 / 33.7;
  - CHAT 28.3 / 7.2 / 37.8;
  - AIQ 25.4 / 19.2 / 25.8;
  - QQQ 18.6 / 12.6 / 18.1;
  - context only: USD (2×) 60.7 / 16.4 / 56.2 and SOXL (3×) 148.7 / 5.3 /
    145.6.

  Top 3 unleveraged by 1Y: SOXX, SMH, SMHX. No unswept ETF beats SMH on
  all three, so there is no backtest.
* **FTMO bot shadow: first exit done, QQQ exit planned.**
  - At 10:05 ET it sold SPY 14.03 lots at 770.67 (bought 10-15 at 765.40)
    for +$73.91. Balance 15,073.91.
  - QQQ closed at 725.42, above its SMA5 of 719.77, so the plan for
    Thursday's open is "exit US100" (day 5 of 10).
  - No entry signal: RSI(2) is 75.1 for QQQ, 83.3 for SPY and 95.1 for
    DIA, and IWM is below its 200-day average. The independent
    computation agrees.
  - Equity 15,209.04 (+1.39%). The lowest, 15,048.36, is the opening mark
    at Tuesday's close. Trading days 2. Flags ok, no tick errors.
* **Astral 1999:** no orders, flat.
  - Its price feeds failed six more times (QQQ, DIA, SPY), and one DIA
    episode lasted two hours.
  - The QQQ feed was still down at the close.

### 2026-10-22 (Thursday, after the close)

* **SMH:** close 523.18, taken from the last regular-session 30-minute
  bar (its 5-minute bars agree). Astral's daily bar says 523.35. SMA50
  576.31, SMA200 514.72. Buy level 540.46, sell level 488.99.
  - SMH fell 6.0% on the day, from 556.70 to 523.35 on the daily bars.
  - Astral has removed the misdated 2026-10-20T20:00Z bar from the SMH
    daily series.
  - The 30-minute series now closes 10-21 at 556.63 (556.75 in the
    10-21 entry), and the 10-21 daily bar has posted at 556.70. The
    10-21 sell level is unchanged at 488.34.
* **Position:** held. **No order.** The close is $34.19 (7.0%) above the
  sell level. SMH is 18.0% below the 2026-10-06 open (638.38).
* **ETF scan** (1Y / 6M / YTD %):
  - SOXX 67.4 / 10.2 / 58.0;
  - SMH 54.6 / 9.8 / 45.3;
  - SMHX 36.2 / 7.0 / 37.2;
  - THNQ 35.4 / 23.1 / 38.1;
  - XSD 36.3 / 2.6 / 40.6;
  - XLK 27.8 / 15.4 / 26.7;
  - IYW 25.9 / 16.3 / 24.7;
  - FTEC 26.4 / 15.1 / 26.0;
  - VGT 26.1 / 15.1 / 25.9;
  - WTAI 23.0 / 3.6 / 25.0;
  - CHAT 22.5 / −2.5 / 29.6;
  - AIQ 23.2 / 12.9 / 22.0;
  - QQQ 16.3 / 7.5 / 14.7;
  - context only: USD (2×) 45.9 / −1.6 / 38.8 and SOXL (3×) 113.9 /
    −22.3 / 95.4.

  Top 3 unleveraged by 1Y: SOXX, SMH, XSD (XSD 36.32 edges SMHX 36.20).
  No unswept ETF beats SMH on all three, so there is no backtest.
* **FTMO bot shadow: QQQ sold. Both trades are closed and the bot is
  flat.**
  - At 10:05 ET it sold QQQ 15.91 lots at 714.33 (bought 10-15 at
    716.93) for −$41.41. The price is the 09:30 ET bar's close, 714.36,
    less the simulated 0.005% half spread.
  - QQQ opened at 713.63, 1.6% below the 10-21 close of 725.42 that
    signalled the exit. The trade was worth +$135.06 at that close and
    filled at a loss. FAST-4 exits at the next open by design, and the
    research models the same fill.
  - Balance 15,032.51: +$32.51 (+0.22%) for the round trip (SPY +$73.91,
    QQQ −$41.41).
  - No entry signal: RSI(2) is 18.0 for QQQ, 21.2 for SPY and 95.3 for
    DIA, and IWM is below its 200-day average. The independent
    computation agrees. QQQ would have to close below 682.60 and SPY
    below 745.43 to signal, well under the day's lows (702.00 and
    761.22). SPY's last 30-minute bar looks thin (volume 2.1M against
    3.9M for the bar before), but no plausible close changes the answer.
  - Equity 15,032.51. The lowest, 14,993.22, is QQQ at the 09:30 ET
    bar's low (711.86) before the sale. The daily floor moved up with the
    SPY profit, to 14,323.91 (day-start balance 15,073.91 less 750).
    Trading days 3. Flags ok, no tick errors.
  - Astral has since revised QQQ's 10-21 close to 725.21 and SPY's
    10-20 close to 769.01. Both are still above their SMA5s (719.78 and
    768.04), so both exits stand.
* **Astral 1999:** no orders, flat since 10-19.
  - One price-feed failure today (DIA at 13:54 UTC, hard timeout). It
    re-activated at 21:13 UTC on 10-21 and at 20:40 UTC today.
  - No divergence: neither Astral nor the shadow had an entry signal.

### 2026-10-23 (Friday, after the close)

* **SMH:** close 527.20. The last regular-session 30-minute bar and
  Astral's daily bar agree. SMA50 575.07, SMA200 515.43. Buy level
  541.20, sell level 489.66.
* **Position:** held. **No order.** The close is $37.54 (7.7%) above the
  sell level. SMH is 17.4% below the 2026-10-06 open (638.38).
* **ETF scan** (1Y / 6M / YTD %):
  - SOXX 64.4 / 8.5 / 58.9;
  - SMH 52.9 / 9.4 / 46.4;
  - SMHX 32.3 / 6.0 / 37.1;
  - THNQ 34.0 / 26.8 / 39.3;
  - XSD 32.0 / 0.6 / 41.1;
  - XLK 26.8 / 17.6 / 27.3;
  - IYW 25.0 / 18.1 / 25.2;
  - FTEC 25.2 / 17.3 / 26.6;
  - VGT 25.1 / 17.3 / 26.5;
  - WTAI 21.1 / 5.8 / 25.7;
  - CHAT 21.6 / −0.1 / 30.7;
  - AIQ 21.9 / 16.4 / 22.5;
  - QQQ 15.4 / 8.1 / 14.7;
  - context only: USD (2×) 42.6 / −1.1 / 39.4 and SOXL (3×) 103.0 /
    −25.9 / 98.8.

  Top 3 unleveraged by 1Y: SOXX, SMH, THNQ (THNQ 34.0 ahead of SMHX 32.3
  and XSD 32.0). THNQ beats SMH on 6M only. No unswept ETF beats SMH on
  all three, so there is no backtest.
* **FTMO bot shadow:** flat, no trade, no entry signal.
  - RSI(2) is 19.4 for QQQ, 15.4 for SPY and 20.4 for DIA, and IWM is
    below its 200-day average. The independent computation agrees.
  - Astral's last 30-minute bars for QQQ, SPY and DIA are cut short
    again (QQQ volume 270k against 10.0M the day before), so I checked
    the closes. SPY's 5-minute bars run to 16:00 ET and close at 759.73,
    and its daily bar says 759.97, against 760.21 on the 30-minute bar.
    The daily bars give QQQ 704.28 and DIA 521.37.
  - None of this is near a signal. A buy needs a close below 754.70 for
    SPY, 693.58 for QQQ and 512.76 for DIA, all under the day's lows
    (758.68, 701.36 and 519.88).
  - Balance and equity 15,032.51 (+0.22%). Daily floor 14,282.51
    (day-start balance less 750). Trading days 3. Flags ok, no tick
    errors.
  - Astral revised the 10-22 closes: SPY 762.07 to 763.97 (the thin bar
    noted in that entry was incomplete), QQQ 704.50 to 704.56 and DIA
    527.82 to 527.88. The 10-22 no-entry answer stands.
* **Astral 1999:** no orders, flat since 10-19.
  - Price-feed failures: DIA at 14:18 UTC (recovered after 4 minutes),
    DIA at 15:52 UTC (recovered after 3 minutes), DIA again at 16:46
    UTC, then all four symbols at 17:54 UTC.
  - From 17:54 UTC the deployment was "degraded", and at the close it
    was still not ready to trade. It had not re-activated by 20:42 UTC.
    There was no signal today, so nothing was missed.
  - Not redeployed, for the same reasons as before: the faults are on
    Astral's side, and a redeploy needs the operator's approval of a
    preview. Monday's morning check will look at its health again.

## Weekly re-validation (2026-10-25, Sunday 22:11 UTC)

**Method.** Astral's backtest tool needs an approval in the app.
* The 10-11 and 10-18 re-validations did not run.
  `astral_backtest_start` was called 11 times between 2026-10-12 03:15
  UTC and 2026-10-18 22:11 UTC. Each call waited for that approval and
  closed unanswered.
* This week uses `research/air3_replica.py`, a local replica of 41110
  (AIR3) and 41122 (buy-and-hold), tested in
  `tests/test_air3_replica.py`.
* Data: Astral's SMH daily export, 3,724 bars, 2012-01-03 →
  2026-10-23, sha256
  `e52e4095a9ef2bc7d92f97397b7edb3b8e1091739620162b419d0645fd6f3235`.
  Its closes equal the SMH column of `data/prices_us.csv` on all 3,708
  shared dates. That file has no opens and ends on 10-02.
* Settings: $100k, 1 bp commission, 2 bp slippage. Trading starts after
  220 warm-up bars inside each window, as on Astral.

**Calibration** (data through 10-02, against the 10-04 Astral runs):
* An entry whose condition already holds on the first eligible bar
  fills at that bar's close. Every later order fills at the next open.
  This rule is inferred from the 10-04 runs; confirm it on the next real
  Astral run.
* With it, AIR3 reproduces all eight Astral figures to rounding (full
  sample, then folds 1–3):
  - returns +1,144% / +121% / +58% / +319%;
  - CAGRs 23.6% / 19.5% / 11.1% / 39.6%.
* Trade counts and win rates are identical. Drawdowns are within 0.1
  point (−27.7% against −27.6% in the full sample and fold 2).
* The closed trades on equity, −0.5% / +72% / +8% / +61% / +90%, match
  the 2026-10-03 list.
* Buy-and-hold is within 6 points in three windows: full +2,196%
  (Astral +2,190%), fold 1 +134% (+134%), fold 2 +97% (+99%).
* Fold 3 buy-and-hold is unexplained: +457.5% against Astral's +445%,
  with drawdowns of −35.3% against −34.9%. No single entry date after
  the warm-up reproduces both the +445% and the −34.9%.

| window | AIR3 return | AIR3 CAGR | AIR3 max DD | trades | win rate | B&H return | B&H max DD | AIR3 lower DD |
|---|---|---|---|---|---|---|---|---|
| full 2014-01 → 2026-10-23 | +945% | 21.7% | −27.7% | 5 closed + 1 open | 80% | +1,820% | −44.9% | yes |
| fold 1 2013-03 → 2018-06 | +121% | 19.5% | −18.0% | 1 + 1 open | 100% | +134% | −22.9% | yes |
| fold 2 2017-06 → 2022-08 | +58% | 11.1% | −27.7% | 3 | 67% | +97% | −37.4% | yes |
| fold 3 2021-08 → 2026-10-23 | +252% | 33.5% | −24.1% | 1 + 1 open | 100% | +367% | −35.3% | yes |

Closed trades on equity in the full sample: −0.5%, +72%, +8%, +61% and
+90%. The open trade was bought at the 2025-07-01 open (276.80). On
equity it is +85% now, against +120% at 10-02.

**Against 10-04** (replica on both dates):
* The full sample fell from +1,144% to +945% (−199 points). Fold 3 fell
  from +319% to +252% (−67 points).
* Both fell because SMH dropped 16.4% from 630.60 (10-02) to 527.20
  (10-23) while the rule held its open trade.
* Folds 1 and 2 are closed windows and did not change.
* No window changed its trade counts, win rates or drawdowns.

**Flags:**
* Win rate 80% (≥ 70%): no flag.
* AIR3's drawdown is lower than buy-and-hold's in every fold: no flag.
* **Wide move, flagged:** −199 points on the full sample and −67 on
  fold 3.
  - It is the open trade marked down with the market, not a change in
    the rule's record.
  - AIR3's equity is 20.7% below its 2026-06-22 peak (SMH −21.2% from
    668.91). The worst drawdown so far is −24.1% in fold 3 and −27.7% in
    the full sample.
  - An SMH close below about 503.6, 4.5% under Friday's close, would set
    a new fold-3 drawdown. That would still be well short of
    buy-and-hold's −35.3%.

**Paper deployment 1924** ($870, saved 6422) has been undeployed since
2026-10-04 23:10 UTC, so there is no paper position to report. Astral's
paper slot runs the FTMO bot test.

**TFSA position** (the operator follows the rule by hand):
* Held since the 10-06 open at 638.38.
* At Friday's close of 527.20 it is −17.4%, or −$111.18 per share.
* The sell level is 489.66 (0.95 × SMA200 515.43). The close is $37.54
  (7.7%) above it.
* SMA50 (575.07) is still above SMA200.
