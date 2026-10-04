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

Run 2026-10-04, `python research/prop_native.py --data-dir <dir>`; full
table in `reports/prop_native.md`.

| symbol | strategy | trades | win rate | profit factor | pass ≤18 mo | funded 1y survival | median funded 1y | verdict |
|---|---|---|---|---|---|---|---|---|
| QQQ | PROP-A | 154 | 65% | 1.30 | 0% | 100% | +1.2% | **NO-GO** |
| QQQ | PROP-B | 81 | 41% | 1.21 | 0% | 100% | +0.4% | **NO-GO** |
| SMH | PROP-A | 174 | 67% | 1.57 | 0% | 100% | +1.2% | info only |
| SMH | PROP-B | 101 | 40% | 1.18 | 3% | 100% | +0.0% | info only |

What was learned:

1. **The stop fixed survival completely.** No funded account breached in
   any 12-month window; FTMO's loss rules stop being the problem once
   every trade risks 1.5% behind a hard stop.
2. **But the edge is far too small to pass in time.** A median trade
   earns about 0.1–0.2% of the account, so +10% then +5% takes a median
   of 5–12 years (1,688–4,404 days). Nothing passes within 18 months.
3. **The trade-off across all three notes is now clear.** Strategies
   that earn fast enough to pass (AIR3 at full size) breach the loss
   rules; strategies that respect the loss rules earn too slowly to
   pass. On daily data, none of the five rules tested sits in between.
4. **PROP-A wins 65–67%**, the closest to the operator's 70%, with a
   profit factor of 1.30–1.57, but it earns about +1% a year on a funded
   account at this risk (about CAD 150 of reward a year on CAD 15,000).
5. Raising risk per trade would speed it up and bring back breaches;
   any such change is a new hypothesis and a new note, and a fourth
   attempt on this history would need a stricter bar still.
