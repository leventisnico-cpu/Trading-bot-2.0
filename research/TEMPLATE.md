# Research note — <candidate name>

No strategy is coded without this note being written **first**, with the
pass/fail rule fixed before any number is looked at. Losers are kept.

## Hypothesis
One falsifiable sentence: what edge, why it should exist, what would
disprove it.

## Universe
Instruments and why (US: `data/prices_us.csv`; CAD: `data/prices_cad.csv`).

## Data source
File, field (adjusted close = total-return approximation), date range,
known gaps.

## Cost model
Commission and slippage per side, as applied on every rebalance, for
both the candidate and the benchmark.

## Walk-forward folds
How the sample is split (contiguous, non-overlapping, equal), and the
full sample.

## Benchmark
Buy-and-hold of the same instrument with the same starting capital and
the same costs.

## Pre-registered pass/fail
Written before running: **PASS only if the candidate's final wealth
beats the benchmark's in ≥ 2 of 3 folds AND on the full sample** (the
same rule as `scripts/expectancy.py`). Anything else is a FAIL, whatever
the Sharpe looks like.

## Result
The measured table, the verdict, and what was learned — including
anything that would tempt a re-run with different parameters (which is
not allowed under this note; a new hypothesis needs a new note).
