# Research note — prop-native strategies for FTMO 2-Step Swing

Written 2026-10-04, **before** any number was looked at. The two
previous notes (`funded_ai_70pct.md`, `funded_ftmo_swing.md`) showed
that FTMO's balance-based daily loss acts as a ~5% stop on every open
position and that AIR3/DIP2 were not built for it. These two designs
are built for it from the start. **This is the third idea tested on the
same history, so the bar is stricter than before** (below). Exactly two
designs are registered; nothing else will be tried under this note.

## Shared rules
* **Instrument for the verdict: QQQ** (the US100 proxy; FTMO offers
  US100.cash). SMH is reported for information only (no FTMO CFD).
* Daily bars, Astral canonical (same files and sha256 as the previous
  notes). Signals on the close, entries at the next open.
* **ATR** = 14-day Wilder average true range, taken on the signal day.
* **Risk sizing:** notional = 1.5% of balance ÷ (stop distance as a
  fraction of entry), capped at 5× balance (FTMO index leverage 1:15).
* **Hard stop** in the market: exit at the stop, or at the open if the
  day opens through it. Long only.
* Costs 0.02% of notional per side, 5%/yr financing on notional.

### PROP-A — dip in the uptrend, with a stop
* Entry: close > SMA200 and RSI(2) < 10.
* Initial stop: entry − 2 × ATR.
* Exit: close > SMA5 (next open), the stop, or 10 trading days.

### PROP-B — breakout in the uptrend, with a trailing stop
* Entry: close > SMA200, SMA50 > SMA200, and close at a new 20-day high.
* Initial stop: entry − 2 × ATR. Trailing: highest close since entry −
  3 × ATR; the stop only moves up.
* Exit: the stop, or close < SMA200 (next open).

## FTMO model (unchanged from `funded_ftmo_swing.md`)
CAD 15,000; Phase 1 +10%, Phase 2 +5%; equity (at the day's low, or at
the stop if stopped out) above 90% of initial; equity above day-start
balance − 5% of initial; ≥4 trading days per phase; 30-day inactivity
in the evaluation with the 25-day keep-alive trade; funded: same loss
rules, 252 days, 80% reward.

**Fix to the previous model:** only start dates with at least 18 months
of data after them count for the evaluation, and at least 252 trading
days for the funded test (late starts are no longer counted as fails).

## Pre-registered GO bar (stricter: all must hold, QQQ)
1. Both phases passed within 18 months in **≥ 60%** of start dates.
2. And in **≥ 50% within each third** of the start dates (stability).
3. Funded account survives 12 months in **≥ 70%** of start dates.
4. Full-sample profit factor **> 1.2** after costs.

Win rate is reported against the operator's 70% target but is not part
of the bar.

## Result
(filled in after the run, below this line, without editing anything
above)
