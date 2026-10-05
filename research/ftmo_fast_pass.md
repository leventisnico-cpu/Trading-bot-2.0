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

Run 2026-10-04, `python research/ftmo_fast_pass.py --data-dir <dir>`;
full table (every risk level, both periods) in
`reports/ftmo_fast_pass.md`. Input sha256: QQQ `229113a9…`, SPY
`a5da4f81…`, DIA `604ed1d5…`, IWM `53f030a2…`. 392 trades, 196 in each
period (checked: the even split is real).

| risk/trade | test win rate | test PF | pass ≤6 mo (test) | pass ≤18 mo (test) | median days to pass (test) | funded 1y survival (test) |
|---|---|---|---|---|---|---|
| 0.5% (chosen) | 70% | 1.41 | 0% | 0% | — | 100% |
| 1.0% | 70% | 1.41 | 0% | 0% | 1,470 | 100% |
| 2.0% | 70% | 1.41 | 0% | 7% | 1,086 | 100% |
| 3.0% | 70% | 1.41 | 0% | 18% | 392 | 37% |

**Verdict: NO-GO.** The selection rule picked 0.5% (no level passed
within 6 months in the selection period, so the tie went to the lowest
risk). At 0.5% nothing passes; no other level passes within 6 months in
either period either, so the choice does not change the verdict.

What was learned:

1. **The 70% win rate is real out of sample.** FAST-4 won 70% of its
   2019–2026 trades (65% in 2011–2018) with a profit factor of 1.41.
2. **The edge per trade is too small for FTMO's clock.** At risk levels
   that survive (≤2%), passing takes a median of 3–4 years. At 2.5–3%
   it passes faster but two positions stopped on the same day breach the
   5% daily limit (37–62% of attempts).
3. **No daily-bar rule tested here can pass in 6 months.** Passing +10%
   then +5% within about 6 months, while never falling 10% (or 5% in a
   day), needs a return-to-risk profile far stronger than any of the six
   rules tested across the four notes.
4. A fifth attempt on this history would be data-mining: the four notes
   are the record and none is a candidate. A genuinely new source of
   edge (for example intraday data with more history than the two years
   Astral provides) would be needed for a new, honest test.

### Addendum 2026-10-05: the operator's question, "profitable within a year?"

The question was asked by the operator and computed with this note's
simulator. The settings are 3% risk, no combined-risk cap, and challenge
start dates every 5 sessions from 2019 onward with a full year of data
after them (339 starts).

| outcome 12 months after starting the challenge | share of starts |
|---|---|
| no funded account yet (failed or still in the evaluation) | 91% (310) |
| funded but breached | 1% (4) |
| funded, no breach, not in profit | 5% (18) |
| **funded, no breach, in profit** | **2% (7)** |

Win rate by calendar year, 2012–2026: 55%–88%. It is below 70% in 9 of
the 15 years (2012 66%, 2013 67%, 2014 66%, 2015 61%, 2016 65%,
2018 57%, 2019 55%, 2020 68%, 2026 to date 61%). The 70% is a long-run
average, not a floor.
