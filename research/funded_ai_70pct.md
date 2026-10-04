# Research note — a ≥70% win-rate AI-trade strategy for a prop-firm account

Written 2026-10-04, **before** any number was looked at. Rules, costs,
the evaluation model and the pass bar are fixed here. A changed rule is
a new note. Losers are kept.

## Hypothesis
On the AI/semiconductor trade (SMH; Nasdaq-100 via QQQ), a daily
long-only rule can (a) win at least 70% of its trades in every
walk-forward fold, and (b) pass a typical two-phase prop-firm evaluation
and keep the funded account alive for a year, often enough to be worth
the fee. It is disproved if either bar below is missed.

## Universe and data
* **SMH** daily OHLC, Astral canonical, 2003-09-10 → 2026-10-02, 5,803
  bars, no gaps (sha256 `4e38736c…5b17dd6`).
* **QQQ** daily OHLC, Astral canonical, 2011-03-23 → 2026-10-02 (Astral
  has a 2004-11 → 2011-03 hole, so only the contiguous part is used;
  sha256 `229113a9…f8870e86`).
* Every signal is computed on a completed daily bar and filled at the
  **next day's open**. No intraday data.

## Candidates (both fixed now)
1. **AIR3** (the bot's rule, unchanged): long when close > 1.05 ×
   SMA200 and SMA50 > SMA200; flat when close < 0.95 × SMA200.
2. **DIP2 — buy short dips inside the uptrend** (the classic 2-period
   RSI pullback, Connors-style, standard published parameters, not
   tuned): long when close > SMA200 and RSI(2) < 10; exit when close >
   SMA5, or after 10 trading days in the trade, whichever is first. No
   price stop. One position at a time.

## Costs (prop-firm CFD model)
Spread/commission 0.02% of notional per side; overnight financing 5% a
year on notional for every night held.

## Evaluation model (generic two-phase, the common industry shape)
* Phase 1: +10% profit target. Phase 2: +5% (fresh balance).
* Fail if equity at any **daily low** (open position marked at the
  day's low) is 10% or more below the phase's starting balance.
* Fail if the day's low equity is 5% or more below the previous close's
  equity (daily loss).
* At least 4 days with a trade fill before a phase can pass.
* Fail on **inactivity**: 30 calendar days with no fill.
* No time limit otherwise.
* **Funded stage:** same loss rules, no target; "survives" means not
  breached for 252 trading days. Median 12-month return reported.
* Start dates: every 10 trading days after the 200-day warm-up.
* Sizing: notional = **1.0 × balance (primary)**; 2.0 × reported only,
  never used to pick the verdict.

## Pre-registered bars (all must hold, at 1.0× sizing)
1. **Win rate ≥ 70%** on the full sample **and** in each of 3
   contiguous walk-forward folds (a win = net P&L > 0 after costs).
2. **Evaluation pass rate ≥ 60%** (both phases) across start dates.
3. **Funded 12-month survival ≥ 70%**.

Judged per strategy per symbol. A candidate that clears all three is a
**prop-firm candidate** only. Live trading through the IBKR bot is still
governed by `scripts/expectancy.py`, which this note does not change.

## Result
(filled in after the run, below this line, without editing anything
above)
