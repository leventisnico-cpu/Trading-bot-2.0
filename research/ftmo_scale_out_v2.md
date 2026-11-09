# Research note — two safety rules for the 5-step exits (W1–W3)

Written 2026-11-09, **before** any number for W1–W3 was computed. V0's
and V1's numbers are the ones already published in
`research/ftmo_scale_out.md`.

## Why

The operator ordered the 5-step exits on 2026-11-08 (V1 of
`research/ftmo_scale_out.md`). On 2026-11-09 the order was widened: "Do
what's necessary for the success of the bot". The bot runs V1 now.

Measured at 3% risk on the four index proxies:

* **Speed.** V1 passes both phases within 18 months in 34–41% of 2011–18
  attempts and 19–24% of 2019–26 attempts. V0 manages 7–9% and 14–17%.
* **Breaches.** In 2019–26, V1 breached 12–13% of attempts. V0
  breached 1%.

The note found the cause (its "What was learned", item 3):

* Before TP1 the only exit is the stop. Every loser is a full −1R, and
  many are held for weeks.
* Costs, financing and gaps push 15–20% of the losers past −1.2R.
* After a losing streak, the combined-risk cap sizes new positions to
  fill the room down to 0.2% above the max-loss line. The overshoot
  then crosses it: 41 of V1's 48 pessimistic 2019–26 breaches are
  max-loss breaches.

That note names the two candidate fixes ("What would tempt a re-run"):
the cap's 0.2% buffer and the missing time exit. They are a new
hypothesis, so they get this new note.

## Hypothesis

Either rule cuts V1's breaches without slowing its passes. If so, the
bot keeps the 5 steps and adds that rule.

## The variants (fixed)

Each is V1 with one change. Everything else stays exactly as in
`research/ftmo_scale_out.md`:

* universe, data and sizing;
* costs, financing and resting orders;
* the two same-day fill bounds;
* the FTMO model and checks, the target lock, trading days and the
  keep-alive;
* cohorts and start dates.

| variant | change to V1 |
|---|---|
| **W1**, time stop | If TP1 has not filled after 10 sessions held (the entry session counts as 1), the whole position closes at the next open. |
| **W2**, max-loss buffer | The combined-risk cap keeps all open stops **1.5%** of the initial balance above the max-loss line, not 0.2%. The daily line keeps its 0.2%. |
| **W3** | W1 and W2 together. |

Where the numbers come from:

* **10 sessions** is FAST-4's own maximum hold. A FAST-4 rebound that
  has not reached +1R by then has had the time the entry was tested for.
* **1.5%** is what a −1.5R loss costs at 3% risk. It leaves room for the
  overshoot measured above. The cap's other uses are unchanged.

Nothing else was tried, and there is no grid.

**Sensitivity only:** V1 and W3 at 2% risk per trade. These rows are
reported and never used to pick a winner. 3% is the operator's order of
2026-10-04, and this note does not change it.

## Reported

The same tables as `research/ftmo_scale_out.md`, for V0, V1, W1–W3 and
the sensitivity rows:

* per trade, from the continuous account;
* CAGR and maximum drawdown at 3% risk;
* FTMO by cohort and bound, with fees per pass.

A trade closed by the time stop counts as not having reached TP1. Its
P(+1R before −1R) is still scanned regardless of the exit.

## Pre-registered pass/fail

A variant **beats V1** if three conditions hold.

* In both cohorts (2011–18, 2019–26) and under both bounds:
  * its share of attempts that **breached** a rule is **no higher**
    than V1's;
  * its share passing **both phases within 18 months** is **no lower**
    than V1's.
* In at least one cohort, its breach share is **strictly lower** than
  V1's under both bounds.

How the comparison is made:

* The pessimistic run is compared with V1's pessimistic run, and the
  optimistic run with V1's optimistic run.
* Both use the same start dates and count attempts out of the same
  number.

Which variants are judged, and what happens next:

* Only W1, W2 and W3 at 3% risk are judged.
* If more than one beats V1, the preferred one has the lower highest
  breach rate across the four cells, then the higher lowest 18-month
  pass rate.
* If one beats V1, it becomes the bot's default once the bot's own code,
  tests and review are done. The 5 steps stay, with the rule added. If
  none does, the bot keeps V1.

**For the record,** each variant is also judged against V0 by the first
note's rule: breached no more often, and passed within 18 months more
often, in all four cells.

## Checks

* **Before the real run:** with no time stop and a 0.2% buffer, the new
  account must reproduce V1's trades exactly, in the continuous account,
  under both bounds. The script asserts this on every run.
* **The script itself:**
  * it is new: `research/ftmo_scale_out_v2.py`;
  * it imports `research/ftmo_scale_out.py` unchanged (sha256
    `af343b8b…`);
  * it runs the same FTMO functions.

Results are appended below under a dated heading. Nothing above is
edited.

## Results — 2026-11-09

**How it was run.**

* Command: `python -B -I research/ftmo_scale_out_v2.py --data-dir <dir>`.
  It took 46 s on four cores.
* Data: the Astral exports of the first note, with sha256 rechecked (QQQ
  `cfab2078…`, SPY `66043ca3…`, DIA `be0494ef…`, IWM `44cc382e…`).
* Script: sha256 `f9a6b2e9888d5812bb61c15d1742eef23783648c9b429682d5688f7736875374`. It imports `research/ftmo_scale_out.py`
  unchanged (`af343b8b…`).
* One run. Nothing was changed after it.

**Checks.**

* With neither rule, the new account reproduces V1's trades in both
  bounds, as asserted.
* V0's and V1's FTMO rows below match `research/ftmo_scale_out.md`
  cell for cell.

Common dates 2011-03-23 → 2026-10-29; continuous account 2012-01-06 → 2026-10-29; start dates (2011–18 / 2019–26): 352 / 368 evaluations. Check passed: with neither rule the new account reproduces V1's trades in both bounds.

* **V0**: FAST-4 exits: close > SMA5 or 10 sessions
* **V1**: the 5 steps (the bot since 2026-11-08)
* **W1**: V1 + time stop: TP1 not filled after 10 sessions -> close at the next open
* **W2**: V1 + the cap keeps open stops 1.5% (not 0.2%) above the max-loss line
* **W3**: W1 + W2
* **V1 2%**: V1 at 2% risk (sensitivity)
* **W3 2%**: W3 at 2% risk (sensitivity)

**Per trade** (continuous account; trades open at the end left out):

| variant | bound | trades | TP1 before stop | P&L win rate | avg win (R) | avg loss (R) | worst (R) | expectancy (R) | P(+1R before −1R) | max consecutive losses | time stops | avg initial risk | median sessions held | CAGR | max DD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| V0 | pessimistic | 396 | 1.0% | 67.4% | +0.32 | -0.51 | -2.50 | +0.052 | 60.2% | 5 | 0 | 2.50% | 3 | +3.0% | 18.6% |
| V0 | optimistic | 396 | 1.0% | 67.4% | +0.32 | -0.51 | -2.50 | +0.052 | 60.2% | 5 | 0 | 2.50% | 3 | +3.0% | 18.6% |
| V1 | pessimistic | 151 | 61.6% | 61.6% | +0.93 | -1.11 | -1.52 | +0.147 | 61.6% | 10 | 0 | 2.55% | 23 | +3.2% | 29.7% |
| V1 | optimistic | 154 | 61.0% | 61.0% | +0.92 | -1.11 | -1.52 | +0.129 | 61.0% | 10 | 0 | 2.56% | 22 | +3.0% | 29.7% |
| W1 | pessimistic | 287 | 21.6% | 54.4% | +0.66 | -0.76 | -2.50 | +0.014 | 56.3% | 8 | 159 | 2.51% | 10 | +0.4% | 27.9% |
| W1 | optimistic | 286 | 21.7% | 54.2% | +0.66 | -0.75 | -2.50 | +0.013 | 56.5% | 8 | 159 | 2.51% | 10 | +0.5% | 27.9% |
| W2 | pessimistic | 151 | 61.6% | 61.6% | +0.93 | -1.11 | -1.52 | +0.147 | 61.6% | 10 | 0 | 2.55% | 23 | +3.2% | 29.7% |
| W2 | optimistic | 154 | 61.0% | 61.0% | +0.92 | -1.11 | -1.52 | +0.129 | 61.0% | 10 | 0 | 2.56% | 22 | +3.0% | 29.7% |
| W3 | pessimistic | 287 | 21.6% | 54.4% | +0.66 | -0.76 | -2.50 | +0.014 | 56.3% | 8 | 159 | 2.51% | 10 | +0.4% | 27.9% |
| W3 | optimistic | 286 | 21.7% | 54.2% | +0.66 | -0.75 | -2.50 | +0.013 | 56.5% | 8 | 159 | 2.51% | 10 | +0.5% | 27.9% |
| V1 2% | pessimistic | 151 | 61.6% | 61.6% | +0.93 | -1.11 | -1.52 | +0.147 | 61.6% | 10 | 0 | 2.00% | 23 | +2.7% | 24.8% |
| V1 2% | optimistic | 154 | 61.0% | 61.0% | +0.92 | -1.11 | -1.52 | +0.129 | 61.0% | 10 | 0 | 2.00% | 22 | +2.4% | 24.8% |
| W3 2% | pessimistic | 289 | 21.5% | 54.3% | +0.67 | -0.76 | -2.50 | +0.016 | 56.1% | 8 | 162 | 1.99% | 10 | +0.2% | 22.3% |
| W3 2% | optimistic | 288 | 21.5% | 54.2% | +0.66 | -0.75 | -2.50 | +0.015 | 56.3% | 8 | 162 | 1.99% | 10 | +0.2% | 22.3% |

**FTMO** (cohorts by start date; trade columns from the continuous account):

| policy | period | trades | win rate | profit factor | P1 passed | both ≤6 mo | both ≤18 mo | both, ever | breached | still running | days to pass (p25 / median / p75) | main failure | funded 1y survival | funded 1y return | attempts per pass |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| V0 pessimistic | 2011–18 | 196 | 65% | 1.17 | 56% | 0% | 7% | 24% | 43% | 32% | 511 / 699 / 1049 | P1 daily_loss 22% | 85% | +3.9% | 2.80 |
| V0 pessimistic | 2019–26 | 200 | 70% | 1.46 | 88% | 0% | 14% | 68% | 1% | 31% | 574 / 870 / 1416 | P2 unfinished 20% | 99% | +6.6% | 1.02 |
| V0 optimistic | 2011–18 | 196 | 65% | 1.17 | 57% | 0% | 9% | 29% | 41% | 30% | 465 / 670 / 936 | P1 daily_loss 21% | 85% | +3.9% | 2.40 |
| V0 optimistic | 2019–26 | 200 | 70% | 1.46 | 89% | 0% | 17% | 70% | 1% | 29% | 554 / 858 / 1428 | P2 unfinished 19% | 99% | +6.6% | 1.02 |
| V1 pessimistic | 2011–18 | 74 | 61% | 1.23 | 66% | 5% | 34% | 46% | 37% | 17% | 254 / 344 / 563 | P1 max_loss 17% | 68% | +3.8% | 1.80 |
| V1 pessimistic | 2019–26 | 77 | 62% | 1.44 | 64% | 2% | 19% | 38% | 13% | 49% | 383 / 547 / 766 | P1 unfinished 26% | 95% | +2.8% | 1.35 |
| V1 optimistic | 2011–18 | 77 | 60% | 1.18 | 65% | 5% | 41% | 47% | 37% | 16% | 237 / 310 / 416 | P1 max_loss 18% | 68% | +4.0% | 1.79 |
| V1 optimistic | 2019–26 | 77 | 62% | 1.44 | 65% | 2% | 24% | 42% | 12% | 46% | 350 / 468 / 721 | P1 unfinished 26% | 95% | +2.8% | 1.29 |
| W1 pessimistic | 2011–18 | 140 | 54% | 1.06 | 36% | 1% | 23% | 24% | 45% | 31% | 230 / 289 / 348 | P1 unfinished 27% | 61% | -1.9% | 2.92 |
| W1 pessimistic | 2019–26 | 147 | 54% | 1.08 | 61% | 1% | 23% | 53% | 14% | 33% | 410 / 631 / 1044 | P1 unfinished 27% | 85% | +2.5% | 1.27 |
| W1 optimistic | 2011–18 | 139 | 54% | 1.06 | 37% | 2% | 23% | 24% | 42% | 34% | 226 / 282 / 336 | P1 unfinished 27% | 61% | -1.9% | 2.76 |
| W1 optimistic | 2019–26 | 147 | 54% | 1.08 | 61% | 1% | 27% | 53% | 14% | 33% | 396 / 544 / 1021 | P1 unfinished 27% | 85% | +2.5% | 1.27 |
| W2 pessimistic | 2011–18 | 74 | 61% | 1.23 | 60% | 5% | 31% | 38% | 16% | 47% | 238 / 328 / 475 | P1 unfinished 29% | 81% | +0.5% | 1.42 |
| W2 pessimistic | 2019–26 | 77 | 62% | 1.44 | 63% | 2% | 20% | 37% | 2% | 61% | 364 / 533 / 802 | P1 unfinished 35% | 99% | +2.5% | 1.07 |
| W2 optimistic | 2011–18 | 77 | 60% | 1.18 | 62% | 5% | 38% | 43% | 15% | 42% | 236 / 307 / 385 | P1 unfinished 30% | 81% | +0.5% | 1.34 |
| W2 optimistic | 2019–26 | 77 | 62% | 1.44 | 64% | 2% | 24% | 40% | 2% | 58% | 335 / 459 / 679 | P1 unfinished 35% | 99% | +2.5% | 1.05 |
| W3 pessimistic | 2011–18 | 140 | 54% | 1.06 | 33% | 1% | 21% | 21% | 22% | 57% | 228 / 278 / 341 | P1 unfinished 50% | 73% | -8.3% | 2.08 |
| W3 pessimistic | 2019–26 | 147 | 54% | 1.08 | 55% | 1% | 22% | 46% | 9% | 45% | 413 / 600 / 1157 | P1 unfinished 37% | 89% | +1.3% | 1.20 |
| W3 optimistic | 2011–18 | 139 | 54% | 1.06 | 33% | 2% | 21% | 21% | 20% | 59% | 220 / 270 / 329 | P1 unfinished 50% | 73% | -8.3% | 1.95 |
| W3 optimistic | 2019–26 | 147 | 54% | 1.08 | 55% | 1% | 24% | 47% | 9% | 44% | 408 / 537 / 1147 | P1 unfinished 37% | 89% | +1.3% | 1.20 |
| V1 2% pessimistic | 2011–18 | 74 | 61% | 1.31 | 69% | 0% | 20% | 47% | 21% | 31% | 417 / 593 / 836 | P2 unfinished 21% | 79% | +4.2% | 1.45 |
| V1 2% pessimistic | 2019–26 | 77 | 62% | 1.38 | 60% | 0% | 16% | 38% | 14% | 49% | 459 / 644 / 832 | P1 unfinished 27% | 97% | +1.0% | 1.36 |
| V1 2% optimistic | 2011–18 | 77 | 60% | 1.22 | 68% | 0% | 20% | 41% | 28% | 30% | 393 / 562 / 756 | P1 max_loss 20% | 79% | +4.0% | 1.68 |
| V1 2% optimistic | 2019–26 | 77 | 62% | 1.38 | 60% | 1% | 17% | 39% | 20% | 42% | 449 / 564 / 781 | P1 unfinished 27% | 97% | +1.0% | 1.51 |
| W3 2% pessimistic | 2011–18 | 140 | 54% | 1.04 | 36% | 0% | 17% | 24% | 14% | 62% | 352 / 413 / 563 | P1 unfinished 52% | 89% | -4.0% | 1.59 |
| W3 2% pessimistic | 2019–26 | 149 | 54% | 1.06 | 61% | 0% | 12% | 36% | 1% | 64% | 480 / 901 / 1134 | P1 unfinished 38% | 98% | +1.4% | 1.02 |
| W3 2% optimistic | 2011–18 | 139 | 54% | 1.03 | 36% | 0% | 18% | 22% | 14% | 63% | 360 / 414 / 471 | P1 unfinished 52% | 89% | -4.0% | 1.63 |
| W3 2% optimistic | 2019–26 | 149 | 54% | 1.06 | 62% | 0% | 14% | 40% | 0% | 60% | 477 / 750 / 1130 | P1 unfinished 38% | 98% | +1.4% | 1.00 |

### Verdict against V1, by the pre-registered rule

| variant | cohort | bound | breached: variant vs V1 | both ≤18 mo: variant vs V1 |
|---|---|---|---|---|
| W1 | 2011–18 | pessimistic | 159/352 (45.2%) vs 130/352 (36.9%) | 81/352 (23.0%) vs 119/352 (33.8%) |
| W1 | 2011–18 | optimistic | 148/352 (42.0%) vs 130/352 (36.9%) | 82/352 (23.3%) vs 143/352 (40.6%) |
| W1 | 2019–26 | pessimistic | 53/368 (14.4%) vs 48/368 (13.0%) | 86/368 (23.4%) vs 71/368 (19.3%) |
| W1 | 2019–26 | optimistic | 53/368 (14.4%) vs 45/368 (12.2%) | 99/368 (26.9%) vs 90/368 (24.5%) |
| W2 | 2011–18 | pessimistic | 55/352 (15.6%) vs 130/352 (36.9%) | 110/352 (31.2%) vs 119/352 (33.8%) |
| W2 | 2011–18 | optimistic | 52/352 (14.8%) vs 130/352 (36.9%) | 135/352 (38.4%) vs 143/352 (40.6%) |
| W2 | 2019–26 | pessimistic | 9/368 (2.4%) vs 48/368 (13.0%) | 73/368 (19.8%) vs 71/368 (19.3%) |
| W2 | 2019–26 | optimistic | 7/368 (1.9%) vs 45/368 (12.2%) | 89/368 (24.2%) vs 90/368 (24.5%) |
| W3 | 2011–18 | pessimistic | 79/352 (22.4%) vs 130/352 (36.9%) | 73/352 (20.7%) vs 119/352 (33.8%) |
| W3 | 2011–18 | optimistic | 70/352 (19.9%) vs 130/352 (36.9%) | 74/352 (21.0%) vs 143/352 (40.6%) |
| W3 | 2019–26 | pessimistic | 34/368 (9.2%) vs 48/368 (13.0%) | 81/368 (22.0%) vs 71/368 (19.3%) |
| W3 | 2019–26 | optimistic | 34/368 (9.2%) vs 45/368 (12.2%) | 89/368 (24.2%) vs 90/368 (24.5%) |

**No variant beats V1** by the rule; the bot keeps V1.

### For the record: against V0 (the first note's rule)

| variant | all four cells: breached ≤ V0 and both ≤18 mo > V0 |
|---|---|
| V1 | no |
| W1 | no |
| W2 | no |
| W3 | no |

### What was learned

1. **W1, the time stop, hurts.**
   * By 10 sessions most FAST-4 rebounds that will reach +1R have not
     yet done so: TP1-before-stop falls from 61% to 22% of trades, and
     159 trades are time-stopped.
   * Expectancy falls from +0.13 to +0.15R down to +0.01R, and CAGR from
     about 3% to 0.4%.
   * Breaches rise in all four cells.
2. **W2, the 1.5% max-loss buffer, does what the first note's diagnosis
   predicted.**
   * Breaches fall from 37% to 15–16% of 2011–18 attempts, and from
     12–13% to 2% of 2019–26 attempts. That is a 58–84% cut in every
     cell.
   * Its per-trade figures equal V1's. Against FTMO's static max-loss
     line, the buffer binds only once the day-start balance is below
     about 96.3% of the initial balance. In the continuous account, whose
     lines follow the day-start balance, it never binds.
   * Within 18 months it passed 31% / 38% of 2011–18 attempts against
     V1's 34% / 41% (pessimistic / optimistic). In 2019–26 it passed 20%
     / 24% against 19% / 24%.
   * By start dates, that is 9, 8 and 1 fewer passes in three cells and 2
     more in the fourth. Those start dates overlap heavily, so the
     difference is far smaller than the breach cut.
   * The cost is time. More attempts are still running when the data ends
     (42–47% and 58–61%), and fewer finish within it (38–43% and 37–40%,
     against 46–47% and 38–42%).
   * Fees per pass fall: 1.34–1.42 attempts against 1.79–1.80, and
     1.05–1.07 against 1.29–1.35.
   * Funded 1-year survival rises from 68% to 81% and from 95% to 99%.
     The median funded return of the survivors falls from +3.8–4.0% to
     +0.5% (2011–18) and from +2.8% to +2.5% (2019–26).
3. **W3 inherits W1's damage.** Its breaches are lower than V1's, but
   its 18-month passes fall to 21% in 2011–18.
4. **2% risk is not the fix.**
   * V1 at 2% breached 21–28% of 2011–18 attempts (down from 37%) and
     14–20% of 2019–26 ones (up from 12–13%).
   * It passed both phases within 18 months in only 20% and 16–17% of
     attempts.
   * Lower risk slows the passes without fixing the overshoot past a cap
     filled to 0.2% of the line.
   * W3 at 2% is safe (0–1% breached in 2019–26) but slow (12–18%
     within 18 months).
5. **By the pre-registered rule, no variant beats V1.** W2 misses on the
   18-month condition in three cells, by the margins above.

### Notes on the run

* **A label edge case in W1 and W3.** A position flagged for the time
  stop at a session's close is labelled `time_stop` if anything closes
  it at the next open. That includes the target lock's flattening, when
  it comes first.
  * The label feeds only the time-stop count and the exemption from the
    TP1-equals-the-scan check.
  * The P&L, the FTMO outcomes and the verdict do not depend on it.
* **Overlapping start dates.** One start date every 5 sessions makes the
  attempts overlap heavily. The cell counts are not independent trials.

## Decision (2026-11-09)

**The bot keeps V1.** This is the pre-registered verdict:

* `cap_max_loss_buffer: 0.002`, the default and in both shipped configs;
* the same 0.2% as before this note.

**W2 is built and available,** behind `cap_max_loss_buffer: 0.015`
(`rules.risk_room`'s max-loss buffer). Turning it on is the operator's
call. A failed pre-registered condition is not overridden without his
explicit order.

The trade-off, as measured above, against V1 (2011–18 / 2019–26):

* **Breached:** 15–16% / 2%, against 37% / 12–13%. A 58–84% cut in
  every cell.
* **Both phases within 18 months:** 31–38% / 20–24%, against 34–41% /
  19–24%. That is 9, 8 and 1 fewer passes of 352–368 start dates in three
  cells, and 2 more in the fourth.
* **Still running when the data ends:** 42–47% / 58–61%, against
  16–17% / 46–49%. **Passed within the data:** 38–43% / 37–40%, against
  46–47% / 38–42%.
* **Attempts per pass (fees):** 1.34–1.42 / 1.05–1.07, against 1.79–1.80
  / 1.29–1.35.
* **Funded account:**
  * survival over 1 year: 81% / 99%, against 68% / 95%;
  * median 1-year return of the survivors: +0.5% / +2.5%, against
    +3.8–4.0% / +2.8%.

In short, the buffer only ever makes an entry smaller, and only once the
day-start balance is under about 96.3% of the initial balance. It trades
long-run income and speed of finishing for far fewer lost accounts.

## Operator's order (2026-11-09): the buffer is on

* **The question.** After the decision above, the operator was asked in
  this session's chat whether the 1.5% buffer should be on for the
  $100k challenge. He was given the trade-off:
  * far fewer lost accounts, 2–16% of attempts instead of 12–37%;
  * about the same pass speed;
  * smaller income once funded.

  The recommendation given was: "on for the challenge, then decide again
  once funded".
* **The answer,** verbatim: "buffer on".
* **What changed:**
  * `cap_max_loss_buffer: 0.015` is now the code default.
  * Both shipped configs carry it too. The question named only the $100k
    challenge. The free trial also runs the buffer because it rehearses
    the challenge: the bot's choice, not the operator's words.
    `cap_max_loss_buffer: 0.002` in the trial config reverses it.
  * The bot prints and logs its cap: `risk cap: all open stops together
    stay 0.2% above the daily line and 1.5% above the max-loss line`.
  * The funded account is to be decided again when there is one.
    `0.002` turns the buffer off.
* **The verdict above is unchanged.** W2 did not pass its pre-registered
  rule. It runs on the operator's order, with the costs listed in
  "Decision".
