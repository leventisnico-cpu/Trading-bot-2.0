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

## Results — 2026-11-09

**How it was run.**

* Command: `python -B -I research/ftmo_slots_sizing.py --data-dir <dir>`.
  It took 4.5 minutes on four cores.
* The note, the script and its tests were committed and pushed first
  (commit `629095c`, 21:48 UTC); the run started after that.
* Data: the Astral exports of the earlier notes, sha256 QQQ `cfab2078…`,
  SPY `66043ca3…`, DIA `be0494ef…`, IWM `44cc382e…`.
* Script: sha256 `203706b9a0c2cbc87cc454bb5121305916554110a127c09957005a17a5c9b562`,
  unchanged since that commit.
* One run. Nothing was changed after it.

Common dates 2011-03-23 → 2026-10-29; continuous account 2012-01-06 → 2026-10-29; start dates (2011–18 / 2019–26): 352 / 368 evaluations. Checks passed: with the share at one and free slots off, the new account reproduces V1 and W2 trade by trade and in every FTMO figure; V1's signal counts are the note's; V1's and W2's frozen shares are the published ones.

* **V1**: the 5 steps, 0.2% buffer (the last note's verdict)
* **W2**: the 5 steps, 1.5% buffer over the max-loss line (the bot today, by order)
* **S1**: V1 + an entry risks at most 1/3 of the room over the max-loss line
* **S2**: V1 + a position with its stop at or above its entry takes no slot
* **S3**: S1 + S2
* **W2+S1**: W2 + the 1/3 share
* **W2+S2**: W2 + free slots
* **W2+S3**: W2 + both
* **S1 at 1/2**: S1 with 1/2 (sensitivity)
* **S3 at 1/2**: S3 with 1/2 (sensitivity)

**Per trade** (continuous account; trades open at the end left out):

| variant | bound | trades | trades per year | TP1 before stop | P&L win rate | avg win (R) | avg loss (R) | payoff (R/trade) | avg first risk | median sessions held | most open at once | CAGR | max DD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| V1 | pessimistic | 151 | 10.2 | 61.6% | 61.6% | +0.93 | -1.11 | +0.147 | 2.55% | 23 | 2 | +3.2% | 29.7% |
| V1 | optimistic | 154 | 10.4 | 61.0% | 61.0% | +0.92 | -1.11 | +0.129 | 2.56% | 22 | 2 | +3.0% | 29.7% |
| W2 | pessimistic | 151 | 10.2 | 61.6% | 61.6% | +0.93 | -1.11 | +0.147 | 2.55% | 23 | 2 | +3.2% | 29.7% |
| W2 | optimistic | 154 | 10.4 | 61.0% | 61.0% | +0.92 | -1.11 | +0.129 | 2.56% | 22 | 2 | +3.0% | 29.7% |
| S1 | pessimistic | 151 | 10.2 | 61.6% | 61.6% | +0.93 | -1.11 | +0.147 | 2.54% | 23 | 2 | +3.3% | 29.5% |
| S1 | optimistic | 154 | 10.4 | 61.0% | 61.0% | +0.92 | -1.11 | +0.129 | 2.54% | 22 | 2 | +3.0% | 29.5% |
| S2 | pessimistic | 214 | 14.4 | 58.9% | 58.9% | +0.92 | -1.13 | +0.079 | 2.45% | 22 | 4 | +1.4% | 37.3% |
| S2 | optimistic | 214 | 14.4 | 58.9% | 58.9% | +0.92 | -1.13 | +0.079 | 2.45% | 22 | 4 | +1.4% | 37.3% |
| S3 | pessimistic | 214 | 14.4 | 58.9% | 58.9% | +0.92 | -1.13 | +0.079 | 2.43% | 22 | 4 | +1.5% | 37.3% |
| S3 | optimistic | 214 | 14.4 | 58.9% | 58.9% | +0.92 | -1.13 | +0.079 | 2.43% | 22 | 4 | +1.5% | 37.3% |
| W2+S1 | pessimistic | 151 | 10.2 | 61.6% | 61.6% | +0.93 | -1.11 | +0.147 | 2.43% | 23 | 2 | +3.2% | 28.6% |
| W2+S1 | optimistic | 154 | 10.4 | 61.0% | 61.0% | +0.92 | -1.11 | +0.129 | 2.44% | 22 | 2 | +2.9% | 28.6% |
| W2+S2 | pessimistic | 214 | 14.4 | 58.9% | 58.9% | +0.92 | -1.13 | +0.079 | 2.45% | 22 | 4 | +1.4% | 37.3% |
| W2+S2 | optimistic | 214 | 14.4 | 58.9% | 58.9% | +0.92 | -1.13 | +0.079 | 2.45% | 22 | 4 | +1.4% | 37.3% |
| W2+S3 | pessimistic | 214 | 14.4 | 58.9% | 58.9% | +0.92 | -1.13 | +0.079 | 2.34% | 22 | 4 | +1.6% | 37.1% |
| W2+S3 | optimistic | 214 | 14.4 | 58.9% | 58.9% | +0.92 | -1.13 | +0.079 | 2.34% | 22 | 4 | +1.6% | 37.1% |
| S1 at 1/2 | pessimistic | 151 | 10.2 | 61.6% | 61.6% | +0.93 | -1.11 | +0.147 | 2.55% | 23 | 2 | +3.2% | 29.7% |
| S1 at 1/2 | optimistic | 154 | 10.4 | 61.0% | 61.0% | +0.92 | -1.11 | +0.129 | 2.56% | 22 | 2 | +3.0% | 29.7% |
| S3 at 1/2 | pessimistic | 214 | 14.4 | 58.9% | 58.9% | +0.92 | -1.13 | +0.079 | 2.45% | 22 | 4 | +1.4% | 37.3% |
| S3 at 1/2 | optimistic | 214 | 14.4 | 58.9% | 58.9% | +0.92 | -1.13 | +0.079 | 2.45% | 22 | 4 | +1.4% | 37.3% |

**Signals** (continuous account, pessimistic bound; 'free': a position whose stop is at or above its entry):

| variant | signals | planned for the next open | entered | not taken: index already held | … by a free position | not taken: slots full | … while a free position was open | … while every open position was free | sessions with two or more positions open |
|---|---|---|---|---|---|---|---|---|---|
| V1 | 990 | 153 | 153 | 408 | 179 | 429 | 250 | 161 | 2341 of 3725 |
| W2 | 990 | 153 | 153 | 408 | 179 | 429 | 250 | 161 | 2341 of 3725 |
| S1 | 990 | 153 | 153 | 408 | 179 | 429 | 250 | 161 | 2341 of 3725 |
| S2 | 990 | 216 | 216 | 550 | 191 | 224 | 45 | 5 | 2428 of 3725 |
| S3 | 990 | 216 | 216 | 550 | 191 | 224 | 45 | 5 | 2428 of 3725 |
| W2+S1 | 990 | 153 | 153 | 408 | 179 | 429 | 250 | 161 | 2341 of 3725 |
| W2+S2 | 990 | 216 | 216 | 550 | 191 | 224 | 45 | 5 | 2428 of 3725 |
| W2+S3 | 990 | 216 | 216 | 550 | 191 | 224 | 45 | 5 | 2428 of 3725 |
| S1 at 1/2 | 990 | 153 | 153 | 408 | 179 | 429 | 250 | 161 | 2341 of 3725 |
| S3 at 1/2 | 990 | 216 | 216 | 550 | 191 | 224 | 45 | 5 | 2428 of 3725 |

**FTMO** (cohorts by start date). Frozen: flat at the end with under 0.05% of room. Stuck: flat at the end and a new entry may risk under 0.5% (every frozen attempt is stuck). Attempts per pass counts a stuck attempt as lost.

| policy | period | P1 passed | both ≤6 mo | both ≤18 mo | both ≤36 mo | both, ever | breached | frozen | stuck | still trading | days to pass (p25 / median / p75) | main failure | funded 1y survival | funded 1y return | attempts per pass |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| V1 pessimistic | 2011–18 | 66% | 5% | 33.8% | 46.3% | 46.3% | 36.9% | 16.8% | 16.8% | 0.0% | 254 / 344 / 563 | P1 max_loss 17% | 68% | +3.8% | 2.16 |
| V1 pessimistic | 2019–26 | 64% | 2% | 19.3% | 37.8% | 37.8% | 13.0% | 29.9% | 29.9% | 19.3% | 383 / 547 / 766 | P1 unfinished 26% | 95% | +2.8% | 2.14 |
| V1 optimistic | 2011–18 | 65% | 5% | 40.6% | 46.6% | 46.6% | 36.9% | 16.5% | 16.5% | 0.0% | 237 / 310 / 416 | P1 max_loss 18% | 68% | +4.0% | 2.15 |
| V1 optimistic | 2019–26 | 65% | 2% | 24.5% | 41.8% | 41.8% | 12.2% | 30.2% | 30.2% | 15.8% | 350 / 468 / 721 | P1 unfinished 26% | 95% | +2.8% | 2.01 |
| W2 pessimistic | 2011–18 | 60% | 5% | 31.2% | 37.5% | 37.5% | 15.6% | 46.9% | 46.9% | 0.0% | 238 / 328 / 475 | P1 unfinished 29% | 81% | +0.5% | 2.67 |
| W2 pessimistic | 2019–26 | 63% | 2% | 19.8% | 36.1% | 36.7% | 2.4% | 41.6% | 41.6% | 19.3% | 364 / 533 / 802 | P1 unfinished 35% | 99% | +2.5% | 2.20 |
| W2 optimistic | 2011–18 | 62% | 5% | 38.4% | 43.5% | 43.5% | 14.8% | 41.8% | 41.8% | 0.0% | 236 / 307 / 385 | P1 unfinished 30% | 81% | +0.5% | 2.30 |
| W2 optimistic | 2019–26 | 64% | 2% | 24.2% | 39.7% | 40.2% | 1.9% | 41.6% | 41.6% | 16.3% | 335 / 459 / 679 | P1 unfinished 35% | 99% | +2.5% | 2.08 |
| S1 pessimistic | 2011–18 | 56% | 5% | 23.6% | 33.5% | 33.8% | 20.2% | 0.0% | 0.0% | 46.0% | 240 / 358 / 636 | P1 unfinished 26% | 84% | -2.7% | 1.60 |
| S1 pessimistic | 2019–26 | 68% | 2% | 13.6% | 17.7% | 17.9% | 1.4% | 0.0% | 0.0% | 80.7% | 280 / 396 / 540 | P2 unfinished 50% | 99% | +0.1% | 1.08 |
| S1 optimistic | 2011–18 | 60% | 4% | 30.4% | 40.3% | 40.6% | 19.9% | 0.0% | 0.0% | 39.5% | 244 / 342 / 538 | P1 unfinished 26% | 84% | -2.7% | 1.49 |
| S1 optimistic | 2019–26 | 68% | 1% | 16.0% | 17.9% | 18.2% | 1.4% | 0.0% | 0.0% | 80.4% | 307 / 433 / 500 | P2 unfinished 50% | 99% | +0.1% | 1.07 |
| S2 pessimistic | 2011–18 | 51% | 5% | 34.4% | 37.8% | 37.8% | 42.6% | 19.6% | 19.6% | 0.0% | 210 / 265 / 338 | P1 max_loss 21% | 62% | +1.7% | 2.65 |
| S2 pessimistic | 2019–26 | 57% | 9% | 30.4% | 30.4% | 30.4% | 18.5% | 40.2% | 40.2% | 10.9% | 166 / 308 / 376 | P1 unfinished 30% | 87% | +3.2% | 2.93 |
| S2 optimistic | 2011–18 | 53% | 9% | 35.5% | 38.6% | 38.6% | 43.8% | 17.6% | 17.6% | 0.0% | 188 / 244 / 335 | P1 max_loss 22% | 61% | +2.1% | 2.59 |
| S2 optimistic | 2019–26 | 63% | 11% | 39.7% | 39.7% | 39.7% | 17.1% | 34.0% | 34.0% | 9.2% | 168 / 267 / 350 | P1 unfinished 24% | 87% | +3.2% | 2.29 |
| S3 pessimistic | 2011–18 | 44% | 5% | 31.0% | 31.0% | 31.0% | 13.9% | 0.0% | 0.0% | 55.1% | 201 / 273 / 345 | P1 unfinished 42% | 80% | -5.0% | 1.45 |
| S3 pessimistic | 2019–26 | 54% | 9% | 29.3% | 45.7% | 47.0% | 5.7% | 0.0% | 0.0% | 47.3% | 249 / 449 / 665 | P1 unfinished 41% | 94% | +0.8% | 1.12 |
| S3 optimistic | 2011–18 | 46% | 8% | 31.2% | 35.5% | 35.5% | 13.6% | 0.0% | 0.0% | 50.9% | 190 / 257 / 398 | P1 unfinished 40% | 80% | -4.8% | 1.38 |
| S3 optimistic | 2019–26 | 61% | 11% | 39.9% | 51.9% | 53.8% | 5.7% | 0.0% | 0.0% | 40.5% | 207 / 346 / 598 | P1 unfinished 34% | 94% | +0.8% | 1.11 |
| W2+S1 pessimistic | 2011–18 | 52% | 3% | 22.2% | 25.3% | 27.0% | 21.3% | 0.0% | 0.0% | 51.7% | 231 / 346 / 404 | P1 unfinished 30% | 86% | -3.5% | 1.79 |
| W2+S1 pessimistic | 2019–26 | 65% | 2% | 12.0% | 17.1% | 17.4% | 1.4% | 0.0% | 0.0% | 81.2% | 296 / 434 / 569 | P2 unfinished 47% | 99% | -0.8% | 1.08 |
| W2+S1 optimistic | 2011–18 | 54% | 5% | 26.1% | 31.0% | 33.0% | 20.2% | 0.0% | 0.0% | 46.9% | 222 / 329 / 502 | P1 unfinished 29% | 86% | -3.2% | 1.61 |
| W2+S1 optimistic | 2019–26 | 65% | 1% | 17.4% | 22.6% | 22.8% | 1.4% | 0.0% | 0.0% | 75.8% | 292 / 386 / 539 | P2 unfinished 42% | 99% | -0.8% | 1.06 |
| W2+S2 pessimistic | 2011–18 | 45% | 5% | 33.8% | 35.2% | 35.2% | 21.0% | 43.8% | 43.8% | 0.0% | 209 / 260 / 322 | P1 unfinished 35% | 77% | -6.7% | 2.84 |
| W2+S2 pessimistic | 2019–26 | 52% | 9% | 30.4% | 42.4% | 42.4% | 8.4% | 38.3% | 38.3% | 10.9% | 214 / 360 / 602 | P1 unfinished 41% | 92% | +1.7% | 2.10 |
| W2+S2 optimistic | 2011–18 | 48% | 8% | 34.1% | 35.5% | 35.5% | 19.3% | 45.2% | 45.2% | 0.0% | 188 / 237 / 302 | P1 unfinished 34% | 77% | -6.4% | 2.82 |
| W2+S2 optimistic | 2019–26 | 58% | 12% | 39.4% | 51.9% | 51.9% | 7.3% | 31.8% | 31.8% | 9.0% | 192 / 309 / 519 | P1 unfinished 34% | 92% | +1.7% | 1.75 |
| W2+S3 pessimistic | 2011–18 | 43% | 5% | 26.4% | 32.4% | 32.4% | 6.5% | 0.0% | 0.0% | 61.1% | 220 / 306 / 426 | P1 unfinished 51% | 88% | -5.5% | 1.20 |
| W2+S3 pessimistic | 2019–26 | 52% | 9% | 26.6% | 45.7% | 47.3% | 1.9% | 0.0% | 0.0% | 50.8% | 256 / 505 / 787 | P1 unfinished 46% | 98% | -0.6% | 1.04 |
| W2+S3 optimistic | 2011–18 | 45% | 6% | 28.1% | 31.2% | 31.2% | 6.5% | 0.0% | 0.0% | 62.2% | 194 / 279 / 386 | P1 unfinished 49% | 88% | -5.1% | 1.21 |
| W2+S3 optimistic | 2019–26 | 54% | 11% | 30.2% | 45.4% | 47.0% | 1.6% | 0.0% | 0.0% | 51.4% | 193 / 447 / 792 | P1 unfinished 45% | 98% | -0.5% | 1.03 |
| S1 at 1/2 pessimistic | 2011–18 | 64% | 5% | 26.1% | 31.8% | 32.4% | 24.4% | 21.6% | 21.6% | 21.6% | 225 / 328 / 468 | P1 unfinished 24% | 81% | +0.1% | 2.42 |
| S1 at 1/2 pessimistic | 2019–26 | 63% | 2% | 14.7% | 38.6% | 38.6% | 2.4% | 0.0% | 0.0% | 59.0% | 426 / 633 / 829 | P1 unfinished 36% | 99% | +1.1% | 1.06 |
| S1 at 1/2 optimistic | 2011–18 | 64% | 5% | 38.1% | 44.6% | 45.2% | 19.9% | 21.3% | 21.3% | 13.6% | 236 / 309 / 404 | P1 unfinished 24% | 81% | +0.8% | 1.91 |
| S1 at 1/2 optimistic | 2019–26 | 64% | 1% | 16.8% | 38.6% | 38.6% | 2.4% | 0.0% | 0.0% | 59.0% | 434 / 626 / 823 | P1 unfinished 35% | 99% | +1.1% | 1.06 |
| S3 at 1/2 pessimistic | 2011–18 | 47% | 5% | 32.1% | 33.0% | 33.0% | 25.6% | 28.1% | 28.1% | 13.4% | 206 / 266 / 338 | P1 unfinished 29% | 76% | -3.7% | 2.63 |
| S3 at 1/2 pessimistic | 2019–26 | 52% | 9% | 29.9% | 45.9% | 45.9% | 8.4% | 0.0% | 0.0% | 45.7% | 259 / 442 / 616 | P1 unfinished 41% | 92% | +1.7% | 1.18 |
| S3 at 1/2 optimistic | 2011–18 | 49% | 8% | 35.8% | 37.2% | 37.2% | 23.0% | 26.1% | 26.1% | 13.6% | 189 / 245 / 326 | P1 unfinished 29% | 76% | -3.6% | 2.32 |
| S3 at 1/2 optimistic | 2019–26 | 59% | 11% | 38.6% | 53.3% | 53.3% | 7.3% | 0.0% | 0.0% | 39.4% | 207 / 328 / 561 | P1 unfinished 34% | 92% | +1.7% | 1.14 |

### Verdict against V1, by the pre-registered rule

| variant | cohort | bound | breached: variant vs V1 | both ≤18 mo | both, ever | no worse |
|---|---|---|---|---|---|---|
| S1 | 2011–18 | pessimistic | 71/352 (20.2%) vs 130/352 (36.9%) | 83/352 (23.6%) vs 119/352 (33.8%) | 119/352 (33.8%) vs 163/352 (46.3%) | no |
| S1 | 2011–18 | optimistic | 70/352 (19.9%) vs 130/352 (36.9%) | 107/352 (30.4%) vs 143/352 (40.6%) | 143/352 (40.6%) vs 164/352 (46.6%) | no |
| S1 | 2019–26 | pessimistic | 5/368 (1.4%) vs 48/368 (13.0%) | 50/368 (13.6%) vs 71/368 (19.3%) | 66/368 (17.9%) vs 139/368 (37.8%) | no |
| S1 | 2019–26 | optimistic | 5/368 (1.4%) vs 45/368 (12.2%) | 59/368 (16.0%) vs 90/368 (24.5%) | 67/368 (18.2%) vs 154/368 (41.8%) | no |
| **S1** | | | | | | no worse anywhere: no; better somewhere: no |
| S2 | 2011–18 | pessimistic | 150/352 (42.6%) vs 130/352 (36.9%) | 121/352 (34.4%) vs 119/352 (33.8%) | 133/352 (37.8%) vs 163/352 (46.3%) | no |
| S2 | 2011–18 | optimistic | 154/352 (43.8%) vs 130/352 (36.9%) | 125/352 (35.5%) vs 143/352 (40.6%) | 136/352 (38.6%) vs 164/352 (46.6%) | no |
| S2 | 2019–26 | pessimistic | 68/368 (18.5%) vs 48/368 (13.0%) | 112/368 (30.4%) vs 71/368 (19.3%) | 112/368 (30.4%) vs 139/368 (37.8%) | no |
| S2 | 2019–26 | optimistic | 63/368 (17.1%) vs 45/368 (12.2%) | 146/368 (39.7%) vs 90/368 (24.5%) | 146/368 (39.7%) vs 154/368 (41.8%) | no |
| **S2** | | | | | | no worse anywhere: no; better somewhere: yes |
| S3 | 2011–18 | pessimistic | 49/352 (13.9%) vs 130/352 (36.9%) | 109/352 (31.0%) vs 119/352 (33.8%) | 109/352 (31.0%) vs 163/352 (46.3%) | no |
| S3 | 2011–18 | optimistic | 48/352 (13.6%) vs 130/352 (36.9%) | 110/352 (31.2%) vs 143/352 (40.6%) | 125/352 (35.5%) vs 164/352 (46.6%) | no |
| S3 | 2019–26 | pessimistic | 21/368 (5.7%) vs 48/368 (13.0%) | 108/368 (29.3%) vs 71/368 (19.3%) | 173/368 (47.0%) vs 139/368 (37.8%) | yes |
| S3 | 2019–26 | optimistic | 21/368 (5.7%) vs 45/368 (12.2%) | 147/368 (39.9%) vs 90/368 (24.5%) | 198/368 (53.8%) vs 154/368 (41.8%) | yes |
| **S3** | | | | | | no worse anywhere: no; better somewhere: yes |

**No variant beats V1** by the rule.

### Verdict against W2, by the pre-registered rule

| variant | cohort | bound | breached: variant vs W2 | both ≤18 mo | both, ever | no worse |
|---|---|---|---|---|---|---|
| W2+S1 | 2011–18 | pessimistic | 75/352 (21.3%) vs 55/352 (15.6%) | 78/352 (22.2%) vs 110/352 (31.2%) | 95/352 (27.0%) vs 132/352 (37.5%) | no |
| W2+S1 | 2011–18 | optimistic | 71/352 (20.2%) vs 52/352 (14.8%) | 92/352 (26.1%) vs 135/352 (38.4%) | 116/352 (33.0%) vs 153/352 (43.5%) | no |
| W2+S1 | 2019–26 | pessimistic | 5/368 (1.4%) vs 9/368 (2.4%) | 44/368 (12.0%) vs 73/368 (19.8%) | 64/368 (17.4%) vs 135/368 (36.7%) | no |
| W2+S1 | 2019–26 | optimistic | 5/368 (1.4%) vs 7/368 (1.9%) | 64/368 (17.4%) vs 89/368 (24.2%) | 84/368 (22.8%) vs 148/368 (40.2%) | no |
| **W2+S1** | | | | | | no worse anywhere: no; better somewhere: no |
| W2+S2 | 2011–18 | pessimistic | 74/352 (21.0%) vs 55/352 (15.6%) | 119/352 (33.8%) vs 110/352 (31.2%) | 124/352 (35.2%) vs 132/352 (37.5%) | no |
| W2+S2 | 2011–18 | optimistic | 68/352 (19.3%) vs 52/352 (14.8%) | 120/352 (34.1%) vs 135/352 (38.4%) | 125/352 (35.5%) vs 153/352 (43.5%) | no |
| W2+S2 | 2019–26 | pessimistic | 31/368 (8.4%) vs 9/368 (2.4%) | 112/368 (30.4%) vs 73/368 (19.8%) | 156/368 (42.4%) vs 135/368 (36.7%) | no |
| W2+S2 | 2019–26 | optimistic | 27/368 (7.3%) vs 7/368 (1.9%) | 145/368 (39.4%) vs 89/368 (24.2%) | 191/368 (51.9%) vs 148/368 (40.2%) | no |
| **W2+S2** | | | | | | no worse anywhere: no; better somewhere: yes |
| W2+S3 | 2011–18 | pessimistic | 23/352 (6.5%) vs 55/352 (15.6%) | 93/352 (26.4%) vs 110/352 (31.2%) | 114/352 (32.4%) vs 132/352 (37.5%) | no |
| W2+S3 | 2011–18 | optimistic | 23/352 (6.5%) vs 52/352 (14.8%) | 99/352 (28.1%) vs 135/352 (38.4%) | 110/352 (31.2%) vs 153/352 (43.5%) | no |
| W2+S3 | 2019–26 | pessimistic | 7/368 (1.9%) vs 9/368 (2.4%) | 98/368 (26.6%) vs 73/368 (19.8%) | 174/368 (47.3%) vs 135/368 (36.7%) | yes |
| W2+S3 | 2019–26 | optimistic | 6/368 (1.6%) vs 7/368 (1.9%) | 111/368 (30.2%) vs 89/368 (24.2%) | 173/368 (47.0%) vs 148/368 (40.2%) | yes |
| **W2+S3** | | | | | | no worse anywhere: no; better somewhere: yes |

**No variant beats W2** by the rule.

## Verdict (2026-11-09)

**No variant beats its baseline. The bot keeps its rules.** Nothing is
ported. Both hypotheses are refuted.

## What was learned

1. **S1, the share of the room, fails on passes.**
   * It does what it was built for: breaches fall (37% to 20% for
     2011–18 starts, 12–13% to 1.4% for 2019–26) and no account
     freezes.
   * But far fewer attempts pass. Within 18 months: 24–30% against
     34–41% (2011–18) and 14–16% against 19–25% (2019–26). Within the
     data: 34–41% against 46–47%, and 18% against 38–42%.
   * The attempts it saves do not come back. They trade on at a small
     size: 40–46% (2011–18) and 80–81% (2019–26) are still unfinished
     when the data ends. At about ten trades a year, an account that
     has shrunk its entries needs years to recover.
   * The coin-flip model that suggested one third was wrong about
     passes. It drew trades independently; real losses come in
     clusters, on indices that fall together.
   * One half (sensitivity) is no better: 15–17% within 18 months for
     2019–26.
2. **S2, free slots, takes more signals and earns less.**
   * It enters 216 of the 990 signals instead of 153, and holds up to
     four positions at once.
   * The payoff per trade falls from +0.13R–0.15R to +0.08R. The
     continuous account's growth falls from +3.0–3.2% to +1.4% a year,
     and its deepest drawdown grows from 30% to 37%.
   * On FTMO it ends attempts sooner, both ways. For 2019–26 starts,
     30–40% pass within 18 months against 19–25%. But it breaches more
     often in every cell (43–44% against 37%; 17–19% against 12–13%)
     and fewer attempts pass within the data in every cell.
3. **S3, both together, splits by period.**
   * 2019–26 starts: better on all three counts. Within 18 months
     29–40% pass against 19–25%; within the data 47–54% against
     38–42%; 6% breach against 12–13%.
   * 2011–18 starts: fewer passes. Within 18 months 31% against
     34–41%; within the data 31–36% against 46–47%. Breaches fall from
     37% to 14%.
   * A rule that wins in one period and loses in the other is what the
     pass/fail rule exists to reject.
4. **With the 1.5% buffer the picture is the same.** W2+S3 beats W2 on
   all three counts for 2019–26 starts and passes less often for
   2011–18 starts.
5. **Funded accounts do no better.**
   * S1 and S3: the median funded year is negative for 2011–18 starts
     (−2.7%; −4.8% to −5.0%) and +0.1% to +0.8% for 2019–26 starts,
     against V1's +3.8–4.0% and +2.8%.
   * S2: fewer accounts survive the year (61–62% against 68%; 87%
     against 95%). The survivors' median year is +1.7–2.1% against
     +3.8–4.0% for 2011–18 starts and +3.2% against +2.8% for 2019–26.

**Post hoc, not part of the verdict.** A scratch comparison of V1's and
S2's continuous accounts (`so.full_run` on `CONT_POL`, pessimistic
bound), their trades matched by index and entry session; R per trade
with its standard error:

| trades | count | payoff per trade | total |
|---|---|---|---|
| V1, all | 151 | +0.147R ± 0.087 | +22.2R |
| S2, all | 214 | +0.079R ± 0.073 | +17.0R |
| S2's trades that V1 also takes | 111 | +0.098R ± 0.099 | +10.9R |
| S2's trades that V1 does not take | 103 | +0.059R ± 0.108 | +6.1R |
| V1's trades that S2 no longer takes | 40 | +0.283R ± 0.183 | +11.3R |

* The signals V1 skips are not as good as the ones it takes. S2 adds
  103 trades worth +0.06R each and gives up 40 worth +0.28R each (when
  V1's entry comes, S2 already holds that index, has both slots at
  risk, or has no risk room left).
* For 2019–26 the added trades made about nothing (−0.01R each, 50 of
  them); for 2012–18 they made +0.13R each (53).
* Every figure in this table is within about one standard error of the
  others. With 150 to 200 trades in 15 years the study cannot tell
  +0.15R from +0.05R, and V1's own +0.13R–0.15R is only about one and
  a half standard errors above zero.

**The conclusion.** The slots and the sizing are not what holds the
system back. The bot takes the better part of a thin edge, about ten
times a year. More of the same signals does not add to it, and safer
sizing only slows it.

**What would tempt a re-run, and is not done:** keeping S3 for "the
recent regime", another share, or counting a free position as half a
slot. Each would be a choice made after seeing these tables.

## Operator's order, 2026-11-10: free slots on

Appended 2026-11-10. Nothing above is changed, and the verdict stands:
**S2 did not pass its pre-registered rule.**

* **The order.** On 2026-11-10 the operator was told what the tables
  above say about free slots: 216 of 990 signals taken instead of 153,
  less earned per trade, more breaches. He answered: "free slots on".
  A failed pre-registered rule is overridden only by the operator's
  explicit order. This is that order, recorded here. It is not a new
  finding and no table was re-read to justify it.
* **What the bot runs from this commit.** `free_slots: true`, the
  default in `ftmo_bot/config.py` and in both shipped configs. With the
  5 steps and the 1.5% buffer (the operator's orders of 2026-11-08 and
  2026-11-09) that is **W2+S2** above. `free_slots: false` gives W2
  back.
* **What that costs and buys, from the tables above** (W2+S2 against
  W2; pessimistic to optimistic; 2011–18 / 2019–26 starts):

  | measure | W2 (free slots off) | W2+S2 (the bot now) |
  |---|---|---|
  | trades a year; payoff per trade | 10.2–10.4; +0.129R to +0.147R | 14.4; +0.079R |
  | breached | 14.8–15.6% / 1.9–2.4% | 19.3–21.0% / 7.3–8.4% |
  | both phases within 18 months | 31.2–38.4% / 19.8–24.2% | 33.8–34.1% / 30.4–39.4% |
  | both phases, ever | 37.5–43.5% / 36.7–40.2% | 35.2–35.5% / 42.4–51.9% |
  | frozen | 41.8–46.9% / 41.6% | 43.8–45.2% / 31.8–38.3% |
  | attempts per pass | 2.30–2.67 / 2.08–2.20 | 2.82–2.84 / 1.75–2.10 |
  | funded 1y survival; median return | 81% / 99%; +0.5% / +2.5% | 77% / 92%; −6.7% to −6.4% / +1.7% |

* **The rule in the bot** (`ftmo_bot/runner.py`: `_is_free`,
  `_slots_used`, `_free_symbols`; `ftmo_bot/fast4.py`: `plan`'s `free`).
  As `SlotAcct.in_slots` above: a position takes a slot while its stop
  is under its entry. The plan after the close and the entry check at
  the open both count that way, and one position per index stays. Two
  things the bot does that the study's model has no place for; neither
  was tested:
  1. The broker rounds a stop to its price step, and an entry filled in
     parts can average between two steps. The bot counts a stop within
     half a step under the entry as at the entry.
  2. The bot moves the stop when a polled bid is at +1R and the broker
     accepts the move. A refused move keeps the slot until the retry
     goes through. The study moves the stop at the touch.
* **Audit of the bot's code, not a test of the rule.**
  `scripts/ftmo_replay.py` ran the real bot with free slots over
  2012-06-28 → 2026-10-29: as one funded account and as a chain of
  challenge accounts, in both bar orders. Its oracle states the slot
  rule apart from the bot. 836 entries, 324 of them made beside two or
  more open positions, and 3,428 deals: **0 mismatches**
  (`reports/ftmo_bot_replay.md`, the section of 2026-11-10). The replay
  has no costs. It shows that the bot does what S2 describes, not that
  S2 earns more.
* **What will show whether it helps.** The free trial, and the 5-step
  shadow (`research/ftmo_shadow_5step`), which runs free slots from the
  2026-11-10 session. The tables above say what to expect: about 14
  trades a year instead of 10, less per trade, more breaches. Nothing
  seen in a few weeks of either can overturn or confirm tables built
  on 15 years.
