# Research note — slots and sizing around the 5 steps (S1–S3)

Written 2026-11-09, **before** any number for S1–S3 was computed. The
numbers quoted for V1 and W2 are already published
(`research/ftmo_scale_out.md`, `research/ftmo_scale_out_v2.md`) or are
diagnostics of V1 as it stands, listed under "What was known before".

## Why

The operator's order of 2026-11-09: "fix all issues that bot has, as
well as the strategy, there is a mistake somewhere that is not allowing
the 5 step system to properly implement its full potential [...] Fix the
bugs and make this system profitable".

The exits were audited first. 2,190 deals of the bot's own code match an
oracle written separately (`reports/ftmo_bot_replay.md`): the 5 steps are
implemented as written. Two rules *around* them are not what the 5 steps
intend. Both were measured on V1 as it stands.

**1. The account takes 153 of 990 signals.** V1's continuous account,
pessimistic bound, 2012–2026 (the optimistic bound differs by a few
counts):

| what happened to a FAST-4 signal | signals |
|---|---|
| taken | 153 |
| not taken: that index was already held | 408 |
| … of which by a position that can no longer lose (stop at or above its entry) | 179 |
| not taken: both slots full | 429 |
| … of which at least one slot held by a position that can no longer lose | 250 |
| … of which both | 161 |

* Both slots are full on 2,341 of 3,725 sessions (63%). On 1,706 of
  those a slot is held by a position that can no longer lose.
* Such positions make up 2,990 of 5,295 position-days (56%).
* The median trade holds 23 sessions. A trade that reached +1R holds 35
  (mean 46, the longest 172).

In the deck every trade is 30% of the account and the last quarter of a
trade is 7.5% of it: it does not stand in the way of the next trade. In
the bot a position takes one of the two slots until its last unit is
sold, so a risk-free quarter blocks a full new trade for weeks.

**2. The cap lets one entry use all the room that is left.** After
losses the next entry is sized so that its stop-out ends exactly on the
buffer above the max-loss line. A stop-out then leaves the account
frozen (flat, no room, cannot pass:
`research/ftmo_frozen_accounts.py`), and a stop that slips breaches it.
17–47% of attempts end frozen. The replayed challenge chain shows one:
four losses by April 2016, then nothing for 10½ years
(`reports/ftmo_bot_replay.md`).

## Hypotheses

* **Slots (S2).** If a position that can no longer lose stops taking a
  slot, the account takes materially more of the signals, at about the
  same payoff per trade, and passes both phases within 18 months more
  often.
* **Sizing (S1).** If an entry may risk only a share of the room over
  the max-loss line, fewer attempts breach or freeze, and more pass
  within the data.

If neither shows, the slots and the sizing are not what holds the
system back, and the bot keeps its rules.

## The variants (fixed)

Each is V1 with one change. Everything else stays exactly as in
`research/ftmo_scale_out.md` and `research/ftmo_scale_out_v2.md`:

* universe, data, the FAST-4 entry, the 5-step exits;
* costs, financing and resting orders, the two same-day fill bounds;
* 3% risk, the 3× notional cap, one position per index;
* the FTMO model and checks, the target lock, trading days, keep-alive;
* cohorts and start dates.

| variant | change to V1 |
|---|---|
| **S1**, share of the room | An entry risks at most the smallest of: 3% of the balance; the room over the daily line (as now); **one third** of the room over the max-loss line. V1 allows all of that last room. |
| **S2**, free slots | A position whose stop is at or above its entry price takes no slot. Entries are planned and taken while fewer than two positions have their stop below their entry. |
| **S3** | S1 and S2 together. |

The rooms, as the cap already computes them (shares of the initial
balance; open risk = the open positions' units × the distance from
entry down to the stop, zero for a stop at or above the entry):

* room over the daily line = balance − open risk − (day-start balance −
  5% + 0.2%);
* room over the max-loss line = balance − open risk − (90% + buffer).

Where the numbers come from:

* **One third.** At the start the room over the max-loss line is 9.8%
  of the account and the ordered 3% is 31% of it. One third is the
  round share that leaves the first trade at the ordered 3% and keeps
  that proportion as the room shrinks: no three losses in a row use it
  up.
* **Stop at or above the entry.** That is step 3's own line: from there
  the position cannot lose against its entry unless the price gaps
  through the stop.

Nothing else was tried on the data, and there is no grid.

**Both buffers.** The bot runs W2 (the 1.5% buffer over the max-loss
line) by the operator's order; the pre-registered verdict of the last
note was V1 (0.2%). So each variant runs at both buffers and is judged
against the rule it would replace:

| buffer over the max-loss line | baseline | judged |
|---|---|---|
| 0.2% | V1 | S1, S2, S3 |
| 1.5% | W2 | W2+S1, W2+S2, W2+S3 |

**Sensitivity only:** S1 and S3 with one half in place of one third, at
the 0.2% buffer. Reported, never used to pick.

## What was known before

* V1's and W2's published tables, the frozen-account table and the
  replay audit named above.
* The signal counts above. They come from a scratch run of V1's own
  account with counters added. The study script prints the same table
  for every variant and asserts that its V1 row reproduces these counts.
* **A coin-flip model of the sizing rule, not market data.** Trades
  drawn independently with V1's measured statistics (61.6% reach +1R
  first, +0.93R average win, −1.11R average loss), Phase 1 then
  Phase 2, 3% risk, 200,000 runs:

  | entry may use | buffer | passed within 70 trades | within 15 trades | breached | frozen | still active |
  |---|---|---|---|---|---|---|
  | all the room (V1) | 0.2% | 55.3% | 27.2% | 20.8% | 23.7% | 0.2% |
  | all the room (W2) | 1.5% | 49.3% | 26.7% | 0.0% | 50.6% | 0.1% |
  | 1/2 of the room | 0.2% | 58.5% | 26.3% | 0.0% | 36.8% | 4.7% |
  | 1/2 of the room | 1.5% | 53.7% | 25.3% | 0.0% | 41.9% | 4.3% |
  | 1/3 of the room | 0.2% | 60.7% | 24.0% | 0.0% | 17.7% | 21.5% |
  | 1/3 of the room | 1.5% | 56.6% | 22.3% | 0.0% | 20.8% | 22.5% |
  | 1/5 of the room | 0.2% | 57.1% | 12.3% | 0.0% | 1.7% | 41.2% |
  | 1/5 of the room | 1.5% | 53.5% | 8.3% | 0.0% | 2.1% | 44.4% |

  It is why one third is the judged share: the highest share of passes
  in the model, at a small cost in speed. Its three inputs are V1's
  trade statistics from the same data, so the choice is not blind to
  the data. The model has no gaps, no costs beyond those averages, no
  second position and no clustering of losses. It also says what to
  expect: S1 passes somewhat **less** often within the first 15 trades
  than V1.
* **A smoke test on a made-up market, not market data.** Before this
  note was committed the script ran end to end on four correlated
  random walks. On that fake market S1 passed *less* often within 18
  months than V1, and its unfinished attempts were neither frozen nor
  stuck: they traded on at a small size for years. So the tables also
  report passes within 36 months, and the verdict counts passes only.
* **What that means for the rule below.** "No worse anywhere" includes
  passing within 18 months. If S1 behaves on the data as it does in the
  model and on the fake market, S1 and W2+S1 fail the rule. That is
  known and accepted before the run: a rule that makes attempts safer
  but slower is not adopted by this note.
* No account with S1, S2 or S3 has been run on the data.

## Reported

For V1, W2, the six judged variants and the two sensitivity rows:

* **Per trade**, from the continuous account: trades, trades per year,
  share reaching +1R before the stop, P&L win rate, average win and
  loss in R, payoff per trade in R, average first risk, median sessions
  held, the most positions open at once, CAGR and maximum drawdown.
* **Signals**: the table above.
* **FTMO**, by cohort and bound, the columns of the last note, plus:
  * both phases passed **within 36 months**;
  * **frozen**, exactly as in `research/ftmo_frozen_accounts.py`: flat
    when the data ends, with under 0.05% of the initial balance of room
    (the smaller of the room over the daily line and the room over the
    max-loss line; for a flat account that is the max-loss room, except
    on the day of a daily loss);
  * **stuck**: flat when the data ends, and the rules allow a new entry
    to risk less than 0.5% of the initial balance (a sixth of the
    normal 3%). Every frozen attempt is stuck. The measure is the same
    for every variant: with S1 an account does not freeze, its entries
    shrink instead;
  * attempts per pass, a stuck attempt counted as lost.

## Pre-registered pass/fail

A variant **beats its baseline** if both hold.

* **No worse anywhere.** In both cohorts (2011–18, 2019–26) and under
  both bounds, out of the same start dates:
  * its count of attempts that **breached** a rule is no higher;
  * its count passing **both phases within 18 months** is no lower;
  * its count passing **both phases within the data** is no lower.
* **Better somewhere.** In at least one cohort, under both bounds, it
  passes strictly more often: within 18 months, or within the data.

The pessimistic run is compared with the baseline's pessimistic run and
the optimistic with the optimistic. Frozen and stuck counts are
reported, not judged: a variant gets no credit for an account that
neither passes nor breaches.

If more than one variant beats a baseline, the preferred one has the
higher lowest share passing within the data across the four cells, then
the lower highest breach share. A remaining tie goes to the variant
with fewer changes.

**What happens next.**

* The buffer is the operator's order and this note does not change it.
* A variant that beats **W2 at the 1.5% buffer** becomes the bot's
  default, once the bot's own code, tests, the full-history replay
  audit and review are done.
* A variant that beats only **V1 at the 0.2% buffer** goes into the bot
  as a setting, switched off, and the operator is told which
  combination won.
* If none beats its baseline, the bot keeps its rules. A failed rule is
  not adopted by judgment; the numbers go to the operator.

## Checks

* **Before the real run:** with the share at one and free slots off,
  the new account must reproduce V1 and W2 exactly: every trade of the
  continuous account under both bounds, and every FTMO figure of every
  cell. The script asserts both on every run.
* **During every run:** never more than two positions with a stop below
  their entry at an entry; never more than one position per index; an
  entry's risk never above the three limits of S1.
* **The verdict rule** is one function of the script (`judge`), tested
  on hand-made counts in `tests/test_ftmo_slots_sizing.py`.
* **The script:** new, `research/ftmo_slots_sizing.py`, committed with
  this note, before the run. It imports `research/ftmo_scale_out_v2.py`
  (sha256 `f9a6b2e9…`) and through it `research/ftmo_scale_out.py`
  (`af343b8b…`), both unchanged, and runs the same FTMO functions.
* **Run on the data before this note was committed:** only
  `--check-only`, which runs the first check above for V1 and W2 and
  computes nothing for S1–S3. It passed.

## Not tested here

* A second position in an index whose first one can no longer lose (179
  of the signals above).
* More markets, or another entry.
* Another share, or part-slots. Each would be a new note.

Results are appended below under a dated heading. Nothing above is
edited.
