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

Run 2026-10-04, `python research/funded_backtest.py --data-dir <dir>`;
full tables in `reports/funded_ai_70pct.md`.

| symbol | strategy | trades | win rate | fold win rates | eval pass | funded 1y survival | verdict |
|---|---|---|---|---|---|---|---|
| SMH | AIR3 | 10 | 60% | 25% / 67% / 100% | 0% | 32% | FAIL |
| SMH | DIP2 | 156 | 69% | 76% / 58% / 73% | 0% | 81% | FAIL |
| QQQ | AIR3 | 8 | 62% | 33% / 50% / 100% | 0% | 57% | FAIL |
| QQQ | DIP2 | 133 | 68% | 67% / 59% / 77% | 0% | 86% | FAIL |

**Verdict: no prop candidate.** What was learned:

1. **The 30-day inactivity rule decides everything.** 85–97% of
   evaluation attempts end as "inactive". AIR3 holds one position for
   months and DIP2 trades about 7 times a year, so both regularly go 30
   days without a fill. Whether a real firm counts an *open position*
   as activity, and whether it has an inactivity rule in the evaluation
   at all, is a fact about the firm, not the strategy; it must be read
   from the firm's rules before any money is spent.
2. **DIP2 is close to 70% but not there.** 68–69% over 15–23 years, with
   one fold at 58–59%. A rule that wins 70% everywhere was not found.
   Its average loss is about as large as its average win, so win rate
   alone is not the edge.
3. **DIP2 keeps a funded account alive** (81–86% one-year survival at
   1.0×) but earns only about +4% a year there. At 2.0× the 5% daily
   loss rule takes most accounts.
4. **AIR3's win rate on SMH is 60% from 2003** (the 75% quoted before was
   2007 onward, 8 trades): ten trades are too few for a win rate to mean
   much.
5. Not allowed under this note: changing RSI thresholds, exit rules,
   sizing or the inactivity assumption to get over 70%. A firm-specific
   rerun (that firm's published rules replacing the generic model) is a
   new note.
