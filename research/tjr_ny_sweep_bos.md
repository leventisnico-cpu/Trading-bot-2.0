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

Run 2026-10-04 with `python research/tjr_backtest.py --data-dir <dir>`;
full tables in `reports/tjr_ny_sweep_bos.md`. Input sha256:

```
c15309666a81034bf5949c233b9e2fd67f69232b9a54942c996013f63e6e2d17  spy.csv
8075868e78e68a104a5d92d2b134ac0fcc0116e7d48ba8e73313916782901889  qqq.csv
7044ecd37dd7f5d4dddfc4c11b05e09789ec7f05d53810bff3befbd680f96601  smh.csv
0917a7ac89d9858a3ad780748c2796731b8d24ee9f3f4167787ba81c218b2355  spy_1d.csv
762a47ac05821c13e0b654d1144091aabee0436bf6c77b7c536887504c67eae3  qqq_1d.csv
86affc285ab46f9c3bd9638708a0b5ddf514be37a65fab856e15017b5d551879  smh_1d.csv
```

Full sample, $10,000, 2024-09-10 → 2026-10-02:

| symbol | variant | trades | avg R | return | max DD | B&H return | B&H max DD | gate |
|---|---|---|---|---|---|---|---|---|
| SPY | A two-sided | 11 | −0.23 | −0.8% | 1.1% | +37.5% | 17.8% | FAIL (0/3) |
| SPY | B long-only | 10 | −0.15 | −0.5% | 0.8% | +37.5% | 17.8% | FAIL (0/3) |
| QQQ | A two-sided | 13 | −0.08 | −0.6% | 1.5% | +58.1% | 21.2% | FAIL (0/3) |
| QQQ | B long-only | 7 | −0.03 | +0.3% | 0.4% | +58.1% | 21.2% | FAIL (0/3) |
| SMH | A two-sided | 9 | +1.45 | +4.5% | 1.0% | +171.8% | 30.8% | FAIL (0/3) |
| SMH | B long-only | 7 | +1.72 | +4.2% | 0.0% | +171.8% | 30.8% | FAIL (0/3) |
| SPY | AIR3 (comparison) | 1 | | +17.1% | 13.7% | +37.5% | 17.8% | FAIL (0/3) |
| QQQ | AIR3 (comparison) | 2 | | +21.8% | 12.5% | +58.1% | 21.2% | FAIL (0/3) |
| SMH | AIR3 (comparison) | 1 | | +115.0% | 23.9% | +171.8% | 30.8% | FAIL (0/3) |

**Verdict: FAIL on every symbol, both variants.** Not deployable.

What was learned:

1. **It rarely trades.** 7–13 setups in 516 days. The 1-hour and 4-hour
   swing structure agreed on about 93 of SPY's days; only about 19 of
   those produced a sweep and a 5-minute break before noon.
2. **No margin kills the sizing.** A sweep stop on SPY is often 0.1% of
   price, so 1% risk needs about 10× leverage. TJR gets it from
   futures; the TFSA has none. Capped at 100% of equity, each trade
   risks about 0.1% of the account, so even SMH's good run (7 of 9 hit
   the 2R target) added only +4%.
3. **The edge is not established.** SPY and QQQ lost on average; SMH's
   +1.45R comes from 9 trades, too few to separate skill from luck.
4. **AIR3 beat it on every symbol.** AIR3 also fails the gate on this
   two-year window: it was a bull market and AIR3 was in cash for part
   of it. Its long-run verdicts stand in
   `reports/minipropos_expectancy_*.md`.
5. **Tempting re-runs, not allowed under this note:** looser bias (1h
   only), more liquidity levels, a 1R or 3R target, longer kill zone.
   Any of them is a new note, and with only two years of 5-minute
   history there is no untouched data left to test it on.
6. **TFSA tax note (not a backtest result):** the CRA can treat
   frequent short-term trading inside a TFSA as carrying on a business,
   which makes the gains taxable. An intraday method run daily raises
   that risk; AIR3's handful of trades a year does not.
