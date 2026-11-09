# Research note — the webinar's scale-out exits on FAST-4 under FTMO rules

Written 2026-11-02, **before** any number for V1–V3 was computed. V0's
numbers are the ones already published in `reports/ftmo_bot_policy.md`.
The operator watched a trading webinar and wants the bot to use its trade
management. This note fixes in advance four things: how that management
translates to the bot's index CFDs, what is measured, the bar it must
clear, and how the webinar's claim is checked. There is one run with
canonical parameters and no grid, and losers are kept.

## The request

* The webinar's figures are percentages of an options premium, with
  1R = a 10% stop on the premium. It risks 3% per trade (30% of the
  account × the 10% stop).
* It manages trades this way:
  * at +1R, sell 1/2 and move the stop to breakeven;
  * at +1.2 to +1.5R, sell 1/4 and move the stop to +1R;
  * trail the stop up for the last 1/4.
* It claims 42 winners in 44 trades and +517% in 8 months. It does not
  disclose its entry.
* On index CFDs everything is expressed in R = the initial stop
  distance (entry − initial stop, in price).

## Hypothesis

Taking half off at +1R, a quarter at +1.5R and trailing the rest raises
the bot's odds on FTMO compared with the current exits (V0): the share of
attempts that breach a rule does not rise, and the share that pass both
phases within 18 months does, in both start cohorts. It is falsified if no
variant meets both conditions in both cohorts under both fill bounds (the
rule is below).

## Universe and data source

The same as `research/ftmo_bot_policy.md`:

* US100, US500, US30 and US2000, through QQQ, SPY, DIA and IWM daily
  bars;
* the same Astral exports (sha256 QQQ `cfab2078…`, SPY `66043ca3…`, DIA
  `be0494ef…`, IWM `44cc382e…`);
* common dates 2011-03-23 → 2026-10-29;
* loaded by `ftmo_fast_pass.load_all` unchanged. It keeps the stray
  20:00 UTC bar of 10-29 in SPY and DIA, as documented there.

The indicators are the base module's: SMA200, SMA5, Wilder RSI(2) and
ATR(14).

## The variants (fixed)

These rules apply to every variant:

* long only;
* the signal is taken on the close and filled at the next open;
* at most 2 positions;
* several signals on one day: lowest RSI(2) first. This is the bot's
  tie-break, kept unchanged for V3.

ATR is the signal day's ATR(14).

| variant | entry | R (initial stop distance) | exits |
|---|---|---|---|
| **V0**, baseline | FAST-4: close > SMA200 and RSI(2) < 10 | 3 × ATR | the stop; close > SMA5 or 10 sessions, at the next open |
| **V1** | FAST-4 | 3 × ATR | scale-out |
| **V2** | FAST-4 | 1.5 × ATR | scale-out |
| **V3** | trend: close > SMA200 and close ≥ the highest close of the prior 20 sessions | 3 × ATR | scale-out |

**V0** is the bot's current policy, run by `research/ftmo_bot_policy.py`
itself rather than re-coded. It uses that script's two 3% rows: "cap
0.2%, lock (intraday)" and "cap 0.2%, lock (next open)".

**Scale-out exits (V1–V3):**

* the initial stop is at entry − 1R;
* **TP1** at entry + 1R closes 50% of the initial units and moves the
  stop to the entry;
* **TP2** at entry + 1.5R closes 25% of the initial units and moves the
  stop to entry + 1R;
* the last 25% trails. After each close, stop = max(stop, entry + 1R,
  highest close since entry − 1R). The stop never moves down;
* there is no SMA5 exit and no time exit.

**Sensitivity only:** V1–V3 with TP2 at +1.2R. The stop still moves to
+1R. These rows are reported and never used to pick a winner.

## Rules shared by every variant

* **Sizing:** 3% of the balance is at risk from the entry to the initial
  stop. Notional is capped at 3× balance per position (the bot's
  `notional_cap`). For V2 that cap can bind when markets are quiet (a
  stop closer than 1% of the price). This is part of the rule; the
  average initial risk per trade shows how often it happens.
* **Combined-risk cap,** as in `ftmo_bot.rules.risk_room`:
  * all open stops together stay 0.2% of the initial balance above the
    daily line (day-start balance − 5%) and above the max-loss line
    (90%);
  * a new position gets at most the room that is left;
  * the committed risk of an open position is its remaining units ×
    max(0, entry − current stop). It is zero once the stop is at the
    entry or above.
* **Cost model:**
  * 0.02% of notional per side (the base model's `SIDE_COST`), on the
    entry and on every partial or full close;
  * financing at 5% a year on the notional still open, per calendar
    night.
* **Resting orders:** the stop and the targets work from the entry
  fill. A day that opens through a level fills at the open: the stop if
  the open is at or below it, and TP1 then TP2 if the open is at or
  above them.
* **Same-day ambiguity:** a daily bar can have run open → low → high →
  close or open → high → low → close. Both orders are walked through
  each open position's levels:
  * the **pessimistic** bound takes the order that leaves the position
    worth less at the close (cash taken plus the remaining units at the
    close). On a tie it takes the order with the lower intraday low;
  * the **optimistic** bound takes the order that leaves it worth more.
    On a tie it takes the order with the higher intraday low;
  * in practice, if the low reaches the stop in force and the high
    reaches a target, the pessimistic bound stops out first. The
    optimistic bound takes the target(s) first, then the raised stop;
  * if the high reaches a target and the low reaches only the stop that
    the target raised, the pessimistic bound closes the rest at that
    raised stop. The optimistic bound keeps it, unless the close is at
    or below it;
  * the trailing stop moves only at the close.
* **FTMO checks,** as in the bot policy:
  * equity at its lowest = cash + each position's lowest value along
    the chosen order;
  * all positions' lows count as simultaneous (the base model's
    convention);
  * a daily-loss or max-loss breach is checked before the target.
* **Target lock** at target + 0.3%, as in the bot policy:
  * the pessimistic bound uses the "next open" lock: it decides on the
    close and flattens at the next open;
  * the optimistic bound uses the "intraday" lock: the sum of each
    position's highest value, filled there;
  * V0's two rows use the same pairing.
* **Trading days** are days on which a position was opened; a partial
  close counts for nothing. There is a keep-alive trade after 25 idle
  days and an inactivity breach at 30.

## FTMO model, cohorts and benchmark

* **FTMO model:** unchanged, and run by the same functions (`phase`,
  `evaluation`, `funded` and `stats` of `research/ftmo_bot_policy.py`),
  given the scale-out account:
  * Phase 1 +10%, Phase 2 +5%;
  * max loss 10%;
  * daily loss 5% of the initial balance, from the day-start balance;
  * at least 4 trading days per phase;
  * no time limit.
* **Start dates:** every 5 sessions from session 200.
* **Cohorts,** by start date: 2011–18 (before 2019-01-01) and 2019–26.
  An evaluation start needs 6 months of data after it; a funded start
  needs 252 sessions.
* **Funded account:** 252 sessions, the same loss rules, no lock.
* **No selection period:** no parameter is chosen, so both cohorts are
  out of sample for this question.
* **Benchmark:** V0.

## Reported (every variant, both bounds)

1. **Per trade.** Trades come from one account per variant, run
   continuously from session 200 to the end with no FTMO stop:
   * its cap measures the loss lines from each session's day-start
     balance, not from the initial balance. All open stops together
     stay within 4.8% of the day-start balance, so the account keeps
     risking 3% as it grows or shrinks (see the amendment below);
   * V0's rule runs in the same account. With the cap's lines at the
     initial balance, that account reproduces the bot policy's V0
     trades exactly; the script checks this on every run;
   * trades still open at the end are left out.

   Reported:
   * the trade count;
   * the **webinar-style win rate**: the share of trades in which TP1
     filled before the initial stop. V0 has no TP1, so for V0 it is the
     share whose price reached entry + 1R while the trade was open;
   * the **P&L win rate**: net P&L > 0 after costs and financing;
   * the average win and the average loss in R, and the **expectancy**
     = the mean R per trade. R = initial units × initial stop distance;
     all figures are net of costs and financing;
   * **P(+1R before −1R)**: scanning forward from each trade's entry,
     regardless of the variant's own exits, the share of trades that
     reach entry + 1R before entry − 1R:
     * a gap at the open counts;
     * a bar touching both levels counts −1R first in the pessimistic
       bound and +1R first in the optimistic bound;
     * trades unresolved at the end are left out;
     * for V1–V3 this equals the webinar-style win rate by
       construction;
   * the **maximum run of consecutive losses**: trades with net
     P&L ≤ 0, in entry order;
   * the **average initial risk** per trade (% of balance), since the
     cap and the notional cap can cut it below 3%.
2. **At 3% risk over the full sample:** the CAGR and the maximum
   drawdown of that account's daily closing equity.
3. **FTMO,** by start cohort (2011–18 and 2019–26), in the layout of
   `reports/ftmo_bot_policy.md`:
   * P1 passed;
   * both phases passed within 6 months and within 18 months;
   * both phases passed within the data;
   * breached a rule;
   * still running;
   * days to pass (p25 / median / p75);
   * the main failure;
   * funded 1-year survival, and the median 1-year return of the
     survivors;
   * the fees per pass.

   The layout's trade columns (trades, win rate, profit factor) come
   from the item-1 account.
4. **The verdict,** by the rule below.

## Pre-registered pass/fail

* **A variant beats V0** only if both conditions hold in **both**
  cohorts and under **both** bounds, on the same start dates. Its
  pessimistic run is compared with V0's next-open row, and its
  optimistic run with V0's intraday row. The conditions are:
  * its share of attempts that **breached** a rule is **no higher**
    than V0's;
  * its share passing **both phases within 18 months** is **higher**.
* Only V1, V2 and V3 at TP2 = 1.5R are judged; the 1.2R rows are not.
* If no variant beats V0, the bot keeps V0. If more than one does, the
  preferred variant is the one with the higher lowest 18-month pass rate
  across the four cells, then the lower highest breach rate.
* A variant that beats V0 is a candidate for the bot, not a deployment.
  It still needs the bot's own code, tests and shadow run.
* **The webinar's hit rate** (42 of 44 = 95%) is called implausible for
  a mechanical entry on these markets if the binomial probability of at
  least 42 hits in 44 trades is below 1%. That probability is taken at
  the highest P(+1R before −1R) measured here (any variant, optimistic
  bound).
* **For scale:** +517% over 44 trades at 3% risk needs a mean of about
  +1.4R per trade, compounded.

## Amendment (2026-11-02, before any real-data run of V1–V3)

* **The first draft:** the per-trade figures and the CAGR came from an
  account whose cap keeps its loss lines at the initial balance, as the
  bot policy's trade columns do.
* **The problem:** a check of the code on synthetic random-walk prices
  showed that such an account stops trading for good once it falls to
  within 0.2% of the max-loss line, because the cap leaves no room. For
  some variants that happened after 15–20 trades, and two variants
  differing only in TP2 gave 164 and 15 trades. The statistics would
  then describe the freeze, not the variant.
* **The fix:** the continuous account (items 1–2) measures the cap's
  lines from each session's day-start balance.
* **Unchanged:** the FTMO runs (item 3) use the bot's cap exactly, with
  every attempt starting at its initial balance.

Results are appended below under a dated heading, without editing
anything above.

## Results — 2026-11-02

Run 2026-11-02 with `python -B -I research/ftmo_scale_out.py --data-dir
<dir>`: 77 s on four cores, on the files above (sha256 rechecked).

* Common dates 2011-03-23 → 2026-10-29.
* The continuous account runs 2012-01-06 → 2026-10-29.
* Start dates (2011–18 / 2019–26): 352 / 368 evaluations and 352 / 343
  funded.
* There was one run, and nothing was changed after it.

**Checks.**

* **Before the run,** on the code only:
  * hand-built bars through the order walk: gaps, both orders, TP1 and
    TP2, the trail;
  * synthetic random-walk prices for the invariants: the accounting
    identity, stops never lowered, committed risk ≥ 0, and TP1 fills
    equal to the ±1R scan. This is the check that found the freeze in
    the amendment;
  * V0's rule in the scale-out account, with the bot's cap, on the real
    data. It reproduces the bot policy's 396 V0 trades, and every FTMO
    figure and per-start outcome, in both cohorts and both bounds.
* **In the run:**
  * V0's FTMO rows below reproduce `reports/ftmo_bot_policy.md` cell for
    cell;
  * V0's trade columns come from the continuous account, so its 2019–26
    profit factor reads 1.46 here against 1.50 there. The trades and win
    rates are the same; only the sizing follows the day-start cap.

### Per trade (continuous account, 3% risk)

| variant | bound | trades | webinar-style win rate | P&L win rate | avg win (R) | avg loss (R) | expectancy (R/trade) | P(+1R before −1R) | max consecutive losses | avg initial risk | median sessions held |
|---|---|---|---|---|---|---|---|---|---|---|---|
| V0 | both | 396 | 1.0% | 67.4% | +0.32 | -0.51 | +0.052 | 60.2% | 5 | 2.50% | 3 |
| V1 | pessimistic | 151 | 61.6% | 61.6% | +0.93 | -1.11 | +0.147 | 61.6% | 10 | 2.55% | 23 |
| V1 | optimistic | 154 | 61.0% | 61.0% | +0.92 | -1.11 | +0.129 | 61.0% | 10 | 2.56% | 22 |
| V2 | pessimistic | 399 | 55.6% | 55.4% | +0.95 | -1.11 | +0.032 | 55.6% | 15 | 2.54% | 5 |
| V2 | optimistic | 393 | 55.7% | 55.5% | +1.03 | -1.11 | +0.076 | 55.7% | 15 | 2.54% | 6 |
| V3 | both | 114 | 60.5% | 60.5% | +0.88 | -1.13 | +0.086 | 60.5% | 7 | 2.54% | 37 |

* "Both": the two bounds give identical figures.
* V0's webinar-style column is the share of trades whose price reached
  +1R while open. V0 sells on the first close above SMA5 (median 3
  sessions), so it almost never gets there.
* 4 V0 trades were unresolved in the ±1R scan at the end.
* 1–2 positions per variant were open at the end; they are left out.
* The cap cut about 40% of entries below 3% risk, in every variant (the
  second position).

### At 3% risk over the full sample (2012-01-06 → 2026-10-29)

| variant | bound | final equity | CAGR | max drawdown (daily close) |
|---|---|---|---|---|
| V0 | both | 1.56× | +3.0% | 18.6% |
| V1 | pessimistic | 1.60× | +3.2% | 29.7% |
| V1 | optimistic | 1.54× | +3.0% | 29.7% |
| V2 | pessimistic | 0.90× | -0.7% | 62.9% |
| V2 | optimistic | 1.38× | +2.2% | 56.2% |
| V3 | both | 1.18× | +1.1% | 23.6% |

### FTMO (the layout of `reports/ftmo_bot_policy.md`)

* **Pessimistic:** stop first, and the next-open lock. For V0, that is
  the bot policy's next-open row.
* **Optimistic:** target first, and the intraday lock. For V0, that is
  the bot policy's intraday row.
* The trade columns come from the continuous account.

| policy | period | trades | win rate | profit factor | P1 passed | both ≤6 mo | both ≤18 mo | both, ever | breached | still running | days to pass (p25 / median / p75) | main failure | funded 1y survival | funded 1y return (median, survivors) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| V0 pessimistic | 2011–18 | 196 | 65% | 1.17 | 56% | 0% | 7% | 24% | 43% | 32% | 511 / 699 / 1049 | P1 daily_loss 22% | 85% | +3.9% |
| V0 pessimistic | 2019–26 | 200 | 70% | 1.46 | 88% | 0% | 14% | 68% | 1% | 31% | 574 / 870 / 1416 | P2 unfinished 20% | 99% | +6.6% |
| V0 optimistic | 2011–18 | 196 | 65% | 1.17 | 57% | 0% | 9% | 29% | 41% | 30% | 465 / 670 / 936 | P1 daily_loss 21% | 85% | +3.9% |
| V0 optimistic | 2019–26 | 200 | 70% | 1.46 | 89% | 0% | 17% | 70% | 1% | 29% | 554 / 858 / 1428 | P2 unfinished 19% | 99% | +6.6% |
| V1 pessimistic | 2011–18 | 74 | 61% | 1.23 | 66% | 5% | 34% | 46% | 37% | 17% | 254 / 344 / 563 | P1 max_loss 17% | 68% | +3.8% |
| V1 pessimistic | 2019–26 | 77 | 62% | 1.44 | 64% | 2% | 19% | 38% | 13% | 49% | 383 / 547 / 766 | P1 unfinished 26% | 95% | +2.8% |
| V1 optimistic | 2011–18 | 77 | 60% | 1.18 | 65% | 5% | 41% | 47% | 37% | 16% | 237 / 310 / 416 | P1 max_loss 18% | 68% | +4.0% |
| V1 optimistic | 2019–26 | 77 | 62% | 1.44 | 65% | 2% | 24% | 42% | 12% | 46% | 350 / 468 / 721 | P1 unfinished 26% | 95% | +2.8% |
| V2 pessimistic | 2011–18 | 213 | 57% | 1.03 | 43% | 10% | 18% | 18% | 35% | 47% | 131 / 178 / 260 | P1 unfinished 35% | 66% | -6.0% |
| V2 pessimistic | 2019–26 | 186 | 54% | 1.01 | 54% | 15% | 42% | 43% | 49% | 8% | 156 / 221 / 309 | P1 daily_loss 24% | 42% | +20.5% |
| V2 optimistic | 2011–18 | 208 | 57% | 1.15 | 51% | 20% | 28% | 28% | 31% | 41% | 106 / 144 / 209 | P1 unfinished 29% | 68% | -3.4% |
| V2 optimistic | 2019–26 | 185 | 54% | 1.07 | 55% | 23% | 45% | 45% | 46% | 8% | 132 / 183 / 272 | P1 daily_loss 27% | 42% | +20.9% |
| V3 pessimistic | 2011–18 | 49 | 67% | 1.38 | 69% | 3% | 25% | 59% | 26% | 16% | 345 / 640 / 821 | P1 max_loss 19% | 91% | +1.1% |
| V3 pessimistic | 2019–26 | 65 | 55% | 1.05 | 48% | 1% | 23% | 29% | 32% | 39% | 294 / 409 / 522 | P1 unfinished 32% | 87% | +2.7% |
| V3 optimistic | 2011–18 | 49 | 67% | 1.38 | 69% | 4% | 24% | 57% | 28% | 15% | 338 / 610 / 828 | P1 max_loss 19% | 91% | +1.2% |
| V3 optimistic | 2019–26 | 65 | 55% | 1.05 | 49% | 1% | 21% | 30% | 36% | 33% | 264 / 411 / 585 | P1 unfinished 32% | 87% | +2.7% |

Attempts per pass (fees at EUR 89 per attempt), shown as 2011–18 /
2019–26:

| variant | pessimistic | optimistic |
|---|---|---|
| V0 | 2.80 / 1.02 | 2.40 / 1.02 |
| V1 | 1.80 / 1.35 | 1.79 / 1.29 |
| V2 | 2.94 / 2.15 | 2.09 / 2.02 |
| V3 | 1.44 / 2.10 | 1.49 / 2.20 |

### Verdict

| variant | cohort | bound | breached: variant vs V0 | both ≤18 mo: variant vs V0 | condition met |
|---|---|---|---|---|---|
| V1 | 2011–18 | pessimistic | 130/352 (36.9%) vs 153/352 (43.5%) | 119/352 (33.8%) vs 23/352 (6.5%) | yes |
| V1 | 2011–18 | optimistic | 130/352 (36.9%) vs 143/352 (40.6%) | 143/352 (40.6%) vs 32/352 (9.1%) | yes |
| V1 | 2019–26 | pessimistic | 48/368 (13.0%) vs 5/368 (1.4%) | 71/368 (19.3%) vs 53/368 (14.4%) | no |
| V1 | 2019–26 | optimistic | 45/368 (12.2%) vs 4/368 (1.1%) | 90/368 (24.5%) vs 63/368 (17.1%) | no |
| V2 | 2011–18 | pessimistic | 124/352 (35.2%) vs 153/352 (43.5%) | 64/352 (18.2%) vs 23/352 (6.5%) | yes |
| V2 | 2011–18 | optimistic | 109/352 (31.0%) vs 143/352 (40.6%) | 100/352 (28.4%) vs 32/352 (9.1%) | yes |
| V2 | 2019–26 | pessimistic | 180/368 (48.9%) vs 5/368 (1.4%) | 156/368 (42.4%) vs 53/368 (14.4%) | no |
| V2 | 2019–26 | optimistic | 171/368 (46.5%) vs 4/368 (1.1%) | 167/368 (45.4%) vs 63/368 (17.1%) | no |
| V3 | 2011–18 | pessimistic | 90/352 (25.6%) vs 153/352 (43.5%) | 88/352 (25.0%) vs 23/352 (6.5%) | yes |
| V3 | 2011–18 | optimistic | 98/352 (27.8%) vs 143/352 (40.6%) | 86/352 (24.4%) vs 32/352 (9.1%) | yes |
| V3 | 2019–26 | pessimistic | 118/368 (32.1%) vs 5/368 (1.4%) | 84/368 (22.8%) vs 53/368 (14.4%) | no |
| V3 | 2019–26 | optimistic | 134/368 (36.4%) vs 4/368 (1.1%) | 78/368 (21.2%) vs 63/368 (17.1%) | no |

**No variant beats V0; the bot keeps V0.**

* In the 2011–18 cohort all three would beat it: they breach less and
  pass both phases within 18 months 2.7–5.2 times as often.
* In the 2019–26 cohort each one breaches far more often than V0's 1%:
  V1 12–13%, V3 32–36%, V2 46–49%. So the first condition fails in all
  six of those cells.

**The webinar's hit rate is implausible** by the pre-registered test.

* The highest P(+1R before −1R) measured (optimistic bound) is 61.0%
  (V1). At that rate, the probability of at least 42 hits in 44 trades
  is 1.5 × 10⁻⁷. At the highest of all rows, 61.6%, it is 2.2 × 10⁻⁷.
* Even a 1% chance needs an entry with P(+1R before −1R) of 82% or more.
* The trade management cannot supply that. TP1 before the stop is the
  same event as +1R before −1R, which is a property of the entry and of
  R.
* For scale: +517% over 44 trades at 3% risk needs +1.41R per trade,
  compounded. The best measured here is +0.15R.

### Sensitivity: TP2 at 1.2R (reported, not used)

| variant (TP2 1.2R) | bound | expectancy (R/trade) | P(+1R before −1R) | CAGR | max drawdown | both ≤18 mo, 2011–18 / 2019–26 | breached, 2011–18 / 2019–26 |
|---|---|---|---|---|---|---|---|
| V1 | pessimistic | +0.086 | 59.3% | +2.1% | 29.7% | 35% / 30% | 45% / 20% |
| V1 | optimistic | +0.108 | 60.0% | +3.0% | 29.7% | 45% / 30% | 40% / 20% |
| V2 | pessimistic | +0.035 | 55.5% | -0.4% | 60.4% | 13% / 41% | 38% / 53% |
| V2 | optimistic | +0.080 | 54.9% | +2.6% | 59.5% | 34% / 44% | 29% / 49% |
| V3 | pessimistic | +0.058 | 58.9% | +1.0% | 24.1% | 16% / 22% | 35% / 30% |
| V3 | optimistic | +0.040 | 57.2% | +0.5% | 27.4% | 19% / 26% | 28% / 32% |

The 1.2R rows also breach at least 20% of 2019–26 attempts. They would
not change the verdict. The script prints their full rows.

### What was learned

1. **The scale-out changes the shape of the trades as designed, but not
   the account.**
   * V1 wins 61% of its trades, by the webinar's count and by P&L. It
     earns +0.13 to +0.15R a trade, against V0's +0.05R.
   * But it holds a median of 22–23 sessions instead of 3, so it takes
     151 trades in 15 years instead of 396.
   * The account ends where V0's does: +3.0–3.2% a year against +3.0%.
     Its drawdown is deeper (30% against 19%) and its longest losing
     streak twice as long (10 against 5).
2. **On FTMO it is faster but breaches more.**
   * In 2011–18, V1 passed both phases within 18 months in 34–41% of
     start dates against 7–9%, and breached less (37% against 41–43%).
   * In 2019–26, V0's good years, V1 breached 12–13% of attempts against
     1%. It also passed within the data less often (38–42% against
     68–70%).
3. **Why the scale-out breaches.**
   * Before TP1 the only exit is the stop, so every loser is a full −1R,
     and many are held for weeks.
   * Costs, financing and gaps push 15–20% of the scale-out losers past
     −1.2R, against 2% of V0's.
   * After a losing streak, the cap sizes the next positions to fill the
     room down to 0.2% above the max-loss line, and the overshoot
     crosses it. 41 of V1's 48 pessimistic 2019–26 breaches are
     max-loss breaches.
   * The breaches cluster in a few episodes: May 2019, February 2020,
     September 2021 and March 2023 (19 of the 48). So the evidence is a
     handful of market episodes, not 368 independent attempts.
4. **V2's tight stop (1.5×ATR)** reaches +1R less often (56% against
   61%). Gaps take it, with the worst loss at −2.2R. It breaches 46–49%
   of 2019–26 attempts; Phase 1's daily line alone ends 24–27% of all
   attempts. Its drawdown reaches 56–63%.
5. **V3's trend entry** is the steadiest scale-out variant in 2011–18
   (26–28% breached). But it has the thinnest edge: +0.086R a trade, 114
   trades, +1.1% a year.
6. **The fill bounds** barely matter at R = 3×ATR, because a bar that
   spans ±3 ATR almost never happens; they matter for V2.
   * They are bounds per bar. A different fill changes which trades come
     after it, so the aggregates are not strictly bracketed.
   * V1's continuous account ends lower in its optimistic run (1.54×
     against 1.60×). That run took 8 trades the pessimistic run did not,
     −1.6R in total.
   * On the 146 trades common to both runs, the results differ by at
     most 0.03R.
7. **What would tempt a re-run.** The breach mechanism points at two
   things: the cap's 0.2% buffer, which ignores costs, financing and
   gaps, and the missing time exit. A scale-out with a wider buffer or a
   time stop is a new hypothesis and needs a new note; it is not a
   re-run of this one.

**Caveats.**

* The bot's near-breach guard (flatten within 0.2% of a line) is not
  modelled, as in `ftmo_bot_policy.py`. For V1–V3 it might turn some
  max-loss breaches into accounts stuck at the line, which do not pass
  either.
* All positions' lows count as simultaneous, as in the base model.
* In V1–V3, the equity high of a position closed during the day counts
  along its walked order. The bot policy's own code counts it at its
  exit price. For V0's rule this made no difference.

## Review corrections and caveats (2026-11-02)

A code review re-ran the script (byte-identical output) and checked the
order walk against an independent tick-by-tick simulator: 60,000 random
bars in both orders, no mismatch. It found no look-ahead and confirmed
the verdict and both figures in it (P ≥ 42/44 = 1.49 × 10⁻⁷ at
p = 0.610; +1.41R a trade for +517% over 44 trades at 3%). The text
above is left as written. These corrections and caveats apply to it:

1. **"(19 of the 48)" should read "(43 of the 48)".** The four named
   episodes hold 43 of V1's 48 pessimistic 2019–26 breaches: May 2019 8,
   February 2020 11, September 2021 5, March 2023 19. Nineteen is March
   2023 alone. The breaches cluster more than stated.
2. **"Cell for cell" is too strong.** V0 reproduces every FTMO cell of
   `reports/ftmo_bot_policy.md` except the 2019–26 profit factor (1.46
   here against 1.50), for the sizing reason given in the next bullet
   above: its trade columns come from the continuous account.
3. **Caveat: the bounds are defined by value at the close, but FTMO
   breaches depend on the equity trough.** In every bar where the two
   orders differ (3 position-bars for V1, 56–57 for V2, none for V3),
   the pessimistic path has the shallower trough, by up to 0.46% (V1)
   and 2.2% (V2) of the initial balance. This can only add breaches to
   the variants, so it cannot flip the verdict.
4. **Caveat: a stop raised after a target fill takes effect within the
   same bar.** It changes the outcome in 2–5 of about 5,400 V1
   position-bars, 2 of 5,373 for V3 and 15–71 of about 3,600–3,900 for
   V2. It would matter if a variant were adopted: the live bot polls
   once a minute and has no resting partial take-profit.
5. **Scope of the conclusion.** The comparison is at equal nominal risk
   (3% to the initial stop), but V1–V3's average loser is −1.11R against
   V0's −0.51R. "No variant beats V0" is what the pre-registered rule
   says. It does not show that a scale-out cannot help at equal
   *realized* risk; testing that would be a new note.
6. **Provenance.** The script as run has sha256
   `af343b8b1485445e709aad793d1d986800c98f6fa1e7ac4c0234c064e76b9be9`.
   The checks cited under "Checks" (hand-built bars, synthetic
   invariants, V0's FTMO-level equivalence) and the review's own tests
   ran from the session scratchpad and are not in the repo. The script
   itself asserts only V0's trade-level equality.
7. **Not ported to the bot.** If a scale-out variant were ever adopted,
   the bot's combined-risk sum (`ftmo_bot/runner.py`, `committed`) would
   need to clamp each position's open risk at 0 once its stop is at or
   above entry, as this script does. Today no stop is ever raised, so it
   is unreachable.

## Operator's order and the port to the bot (2026-11-08)

The operator ordered the bot to follow the 5 steps ("the bot should lose
1 trade per 31"). V1 is now in the bot as `exit_mode: scale_out`, the
default (`ftmo_bot/scale_out.py`, `Runner.manage`). The verdict above is
unchanged: this is an order, not a pass of the pre-registered rule.

**What was ported, as V1 specifies:**

* R = the first stop's distance, 3 × ATR(14).
* TP1 at +1R closes 1/2 and moves the stop to the entry.
* TP2 at +1.5R closes 1/4 and moves the stop to +1R.
* From TP2 on, the stop rises after each session's close to
  max(entry + 1R, highest close since entry − 1R).
* There is no SMA5 or time exit.

**What differs from the study:**

* The live bot has no resting take-profit. It polls every minute,
  weekdays 09:31–17:00 New York, and sells at the bid once it touches a
  level. A touch outside those hours does not count.
* A part close that rounds below the minimum lot is not sent.

**Caveat 7 is done.** The combined-risk sum now counts each position's
open risk as max(0, …), so a stop at or above its entry adds no room.

**A gap the study did not have.** The bot's keep-alive was refused when
both slots were full. 5-step positions are held a median of 22–23
sessions. Two of them could therefore starve FTMO's 30-day inactivity
clock, which the study's model never starves. The round trip now runs
whatever is held.

**The 1-in-31 claim.** It means P(+1R before −1R) ≥ 96.8%. The highest
measured above is 61.6%, so 38–39% of trades lose. The trade management
cannot change that (see "The webinar's hit rate is implausible").

### Live shadow comparison, 2026-10-05 → 11-06 (same bars, same code)

Both runs use `scripts/ftmo_shadow.py` with the same Astral 30-minute
exports (2025-08-14 → 2026-11-06). The first tick is 10-05 09:35 New
York.

* A replay with `--exit-mode fast4` matches the code before this change
  exactly: deals, balance and bot state.
* It differs from the committed `research/ftmo_shadow/` (14,945.96) by a
  first-session keep-alive and slightly revised bars.

| exits | trades closed | realized P&L | balance | equity 11-06 | lowest equity | open |
|---|---|---|---|---|---|---|
| FAST-4 (`fast4`) | 4 + keep-alive | QQQ −45.18, SPY +71.78, DIA +182.26, QQQ −268.81 | 14,938.78 (−0.4%) | 14,938.78 | — | none |
| 5 steps (`scale_out`) | 2 + keep-alive | QQQ −449.80 (stop), SPY −270.02 (stop) | 14,280.19 (−4.8%) | 13,974.12 (−6.8%) | 13,872.46 (−7.5%) | DIA 28.79 @ 522.86, stop 507.70 |

**The October rebound was too small for the 5 steps.**

* The QQQ and SPY entries of 10-15 peaked at +0.44R and +0.53R (bar
  highs) before their stops. TP1 sat at +1R, 3 ATR above entry.
* The DIA entry of 11-02 has reached +0.91R so far.
* FAST-4's 5-day-average exit sold that rebound within a week.
* The 5-step positions were held into the late-October and 11-05
  sell-offs and stopped out at the full −1R.
* Two losers in two trades are not evidence about a 61%-win rule
  (0.39² ≈ 15%). The comparison does show the mechanism above: every
  loser is a full stop, held for weeks.
* `research/ftmo_shadow_5step/` is continued daily next to
  `research/ftmo_shadow/`.
