# Research note — FAST-4: a ≥70% win-rate system to pass FTMO quickly

Written 2026-10-04, **before** any number was looked at. Operator's goal
(2026-10-04): an automated system with at least a 70% win rate that
passes FTMO's 2-Step evaluation as quickly as possible. **Fourth idea
tested on this history** (after `funded_ai_70pct.md`,
`funded_ftmo_swing.md`, `prop_native.md`), so: one system only, one
free parameter chosen on the first half and judged on the second half,
and a bar that must hold out of sample.

## The system (fixed)
* **Universe:** four FTMO index CFDs via their ETF proxies — US100
  (QQQ), US500 (SPY), US30 (DIA), US2000 (IWM). Daily bars, Astral
  canonical, common window 2011-03-23 → 2026-10-02 (sha256 recorded in
  the result).
* **Entry** (per instrument, signal on the close, fill at the next
  open): close > SMA200 and RSI(2) < 10.
* **Stop:** entry − 3 × ATR(14) of the signal day, resting in the market
  (fill at the stop, or at the open if it gaps through).
* **Exit:** close > SMA5 (next open), or 10 trading days, or the stop.
* **At most 2 positions open.** Several signals on one day: lowest
  RSI(2) first.
* **Size:** risk r% of current balance per position; notional capped at
  5× balance per position (FTMO index leverage 1:15).
* Costs 0.02% of notional per side, 5%/yr financing on notional.
* **Keep-alive:** a 0.01-lot open/close if 25 days pass with no fill
  (as in the previous notes).

## FTMO model (as in `funded_ftmo_swing.md`)
CAD 15,000; Phase 1 +10%, Phase 2 +5%; equity (all positions at the
day's low, or at their stop if stopped) above 90% of initial; equity
above day-start balance − 5% of initial; ≥4 trading days per phase;
30-day inactivity in the evaluation; funded: same loss rules, 252 days.
Start dates every 5 trading days.

## The one free parameter, chosen in-sample only
r ∈ {0.5, 1.0, 1.5, 2.0, 2.5, 3.0}%. **Selection period:** start dates
2011-03-23 → 2018-12-31. Choose the r with the highest share of
evaluations passed **within 6 months**, among those whose funded
one-year survival is ≥ 70% in the selection period. Ties → lower r.

## Pre-registered GO bar — test period only (starts 2019-01-01 → end)
All must hold at the chosen r:
1. **Win rate ≥ 70%** on trades entered in the test period.
2. Both phases passed **within 6 months** in **≥ 50%** of test start
   dates (start dates need 6 months of data after them).
3. Funded account survives 12 months in **≥ 70%** of test start dates.
4. Test-period profit factor **> 1.2**.

Median days to pass is reported as the speed measure. Results for every
r are reported in both periods, so the choice can be audited.

## Result
(filled in after the run, below this line, without editing anything
above)
