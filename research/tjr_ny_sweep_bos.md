# Research note — TJR "NY session sweep + break of structure" (ICT style)

Written 2026-10-04, **before** any number was looked at. Every rule below
is fixed here; nothing is tuned after the run. A changed rule is a new
note. Losers are kept.

## Hypothesis
The method as the operator described it: on the 4-hour and 1-hour charts
the swing sequence sets the bias; during the New York session price
sweeps a prior high or low; a 5-minute break of structure confirms the
turn; the entry is taken on a retrace into a fair value gap (or the
equilibrium of the move); stop beyond the sweep, fixed risk per trade.
If this is a real edge, a mechanical version of it earns more per dollar
of drawdown than holding the same ETF, net of IBKR costs, out of sample.
It is disproved if it does not pass the repo's gate.

## Universe
SPY, QQQ, SMH. TJR trades index futures (ES/NQ); the TFSA cannot hold
futures, so the matching ETFs stand in. SMH is the asset AIR3 runs on.

## Data source
Astral canonical OHLCV, 5-minute bars, regular hours only (09:30–16:00
ET), 2024-09-10 → 2026-10-02, 516 trading days per symbol (the account's
cap is 40,000 bars, about two years). Daily bars from Astral for the
AIR3 comparison (2023-06 → 2026-10, so its 200-day average exists at the
window start). sha256 of every file is recorded in the result section.
**Known limit: two years is short.** A pass here is weak evidence; a
fail is strong evidence against.

## Mechanical rules (fixed)
* **Bars.** 1-hour and 4-hour bars are built from the 5-minute bars
  inside regular hours (4-hour: 09:30–13:30, 13:30–16:00).
* **Swing points.** A bar is a swing high if its high is above the highs
  of the 2 bars before and the 2 bars after (swing low: mirror). It is
  only *known* 2 bars after it formed.
* **Bias.** On each of 1h and 4h, using swings known at the moment of the
  decision: bullish if the last two swing highs rise AND the last two
  swing lows rise; bearish if both fall; otherwise neutral. A trade needs
  1h and 4h to agree. Neutral → no trade that day.
* **Liquidity.** Long side: the previous day's low and the most recent
  known 15-minute swing low. Short side: mirror (previous day's high,
  latest 15-minute swing high).
* **Sweep.** Between 09:30 and 11:30 ET a 5-minute bar trades through a
  liquidity level against the bias (below it for a long).
* **Break of structure.** After the sweep, before 12:00 ET, a 5-minute
  bar *closes* beyond the most recent known 5-minute swing point that
  formed before the sweep extreme (above the last swing high for a long).
* **Entry.** The most recent bullish fair value gap in the leg from the
  sweep extreme to the break bar (bar i-2 high < bar i low); limit order
  at the gap's midpoint. No gap → limit at the leg's 50% (equilibrium).
  The order is live from the bar after the break until 12:00 ET and is
  cancelled if price trades through the sweep extreme first. A bar that
  opens through the limit fills at its open.
* **Stop** one cent beyond the sweep extreme. **Target** 2R. Anything
  still open is closed at the 15:55 ET bar's close. If one bar touches
  both stop and target, the stop is assumed first.
* **One trade per day.** The first valid setup of the day only.
* **Size.** Risk 1% of current equity: shares = floor(0.01 × equity /
  (entry − stop)), capped so the position never exceeds equity (no
  margin in the TFSA). Fewer than 1 share → no trade.
* **Two variants, both registered now:**
  * **A, two-sided** (longs and shorts): judges the method itself, the
    way TJR trades it on futures.
  * **B, long-only**: the only version the TFSA can run (no shorting).
    **Only B can become deployable.**

## Cost model
IBKR Pro fixed, both sides of every trade: $0.005/share, $1.00 minimum
per order. Limit entries fill at the limit (no slippage); stop and
time exits pay one cent of slippage. Buy-and-hold pays the same
commission once.

## Walk-forward folds
The 516 days split into 3 contiguous, equal folds, plus the full sample.
No parameter is fitted, so the folds test stability, not a fit.

## Benchmarks
1. Buy-and-hold of the same ETF, $10,000, 95% invested at the first open
   of each window.
2. AIR3 (the bot's rule) on the same ETF over the same windows: signal
   on the daily close, fill at the next day's first 5-minute open, 95%
   of equity per entry. Reported for comparison only.

## Pre-registered pass/fail
The repo's gate (`scripts/expectancy.py`), unchanged: **PASS only if, in
≥ 2 of 3 folds AND on the full sample, the strategy either (1) ends
with more equity than buy-and-hold, or (2) earns more per dollar of max
drawdown than buy-and-hold while keeping at least half of its gain.**
Judged per symbol, at $10,000. A second run at $870 (the real account)
is reported to show what the $1.00 minimum does to a small account; it
does not change the verdict.

## Result
(filled in after the run, below this line, without editing anything
above)
