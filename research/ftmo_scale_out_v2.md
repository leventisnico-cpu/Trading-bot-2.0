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
