# FTMO bot: the 5 steps replayed over 2012–2026 and audited deal by deal

Run 2026-11-09 with `scripts/ftmo_replay.py` (sha256 `f7e1e64b…`), four
times:

    python -B scripts/ftmo_replay.py --data-dir <dir> --mode funded|challenge
        --order low_first|high_first --report <file>

Input: the studies' daily Astral exports of QQQ, SPY, DIA and IWM, sha256
`cfab2078…`, `66043ca3…`, `be0494ef…`, `44cc382e…` (3,925 common sessions,
2011-03-23 → 2026-10-29; the first 320 are the bot's history).

## What was done

* **The real bot.** The same `ftmo_bot.Runner` the MT5 bot runs, with the
  challenge config's defaults (5-step exits, 3% risk, two positions, the
  combined-risk cap with 0.2% over the daily line and 1.5% over the
  max-loss line), traded a simulated 15,000 account
  (`ftmo_bot/broker_sim.py`).
* **The market.** Each daily bar became 13 half-hour bars: a flat bar at
  the open, then a walk open → first extreme → second extreme → close
  that stops exactly on every open position's next target, so the polling
  bot sees what a resting order would see. `low_first` puts the low
  before the high (the worse order for a long position); `high_first`
  the reverse.
* **Two account modes.** `funded`: no profit target, one account for the
  whole history. `challenge`: the Phase 1 target (+10%); an account that
  reaches it or trips the max-loss guard is replaced by a fresh one the
  next session.
* **The checks, on every session.**
  * The plan after each close, against FAST-4 computed from the daily
    arrays of `research/ftmo_fast_pass.py`.
  * Every entry: the signal, the stop 3 × ATR under the fill, and the
    size (3% risk, both buffers of the cap, the notional cap).
  * Every 5-step trade, deal by deal, against an oracle written
    separately from the bot (`five_steps` in the script): each part
    close, each stop move, the trail, the stop-out.
  * Invariants: at most two positions, a stop never lowered, a volume
    never raised, the balance equal to the start plus the deals' P&L.
* **The check on the checker.** `tests/test_ftmo_replay.py` breaks the
  bot's 5 steps on purpose (a wrong share at +1R; a wrong trail
  distance) and requires the replay to report it.

## Result: 0 mismatches

| run | plans checked | entries checked | deals checked | part closes | stop moves | trades the 5 steps ended | reached +1R first | mean per trade, before costs | mismatches |
|---|---|---|---|---|---|---|---|---|---|
| funded, low first | 3,603 | 145 | 790 | 150 | 497 | 143 | 87 (60.8%) | +0.271R | **0** |
| funded, high first | 3,603 | 143 | 792 | 150 | 501 | 141 | 86 (61.0%) | +0.283R | **0** |
| challenge, low first | 3,600 | 55 | 304 | 51 | 206 | 47 | 26 (55.3%) | +0.229R | **0** |
| challenge, high first | 3,600 | 55 | 304 | 51 | 206 | 47 | 26 (55.3%) | +0.229R | **0** |
| all four | 14,406 | 398 | 2,190 | 402 | 1,410 | 378 | 225 (59.5%) | | **0** |

## Reading

1. **The bot does the 5 steps as written.** 2,190 deals in 398 trades
   match the oracle, in both bar orders and both account modes. There is
   no bug in the exits to fix.
2. **The bot's own trades reach +1R before −1R about 6 times in 10.**
   In the funded runs 39% of the trades lost at the first stop: about 1
   in 2.6, not 1 in 31. The measure of what 1 in 31 would take is
   `research/ftmo_win_rate_dial.md`.
3. **Costs are zero here.** No spread, no commission, no financing: the
   `mean per trade` column is before costs, on ETF proxies. The studies
   with costs give +0.13R to +0.15R per trade
   (`research/ftmo_scale_out_v2.md`). This replay audits what the bot
   does, not what it earns.
4. **The funded account** went from 15,000 to 31,737.86 (low first) or
   31,381.51 (high first) in 14.3 years, before costs. Its lowest equity
   of a session crossed the daily line twice (2015-08-21 and, low first
   only, 2019-10-02): a gap carried the price through the stops. FTMO
   would have ended the account there; the replay goes on.
5. **The challenge chain found frozen accounts.**
   * Accounts 1–4 reached the Phase 1 target (2013-04-10, 2013-09-16,
     2014-12-19, 2015-07-14).
   * Account 5 lost to the gap of 2015-08-24: its lowest equity crossed
     the max-loss line.
   * Account 6 opened 2015-08-25 and ended the data on 2026-10-29 at
     13,724.95, flat. Replayed alone from 2015-08-25 it takes four
     trades (two on 2015-11-10, then 2016-01-05 and 2016-04-25), risking
     3.0%, 1.8%, 3.0% and 0.9% of the balance. All four stop out. That
     leaves the balance at the max-loss line plus the 1.5% buffer
     (13,725), and the bot can open nothing more: for 10½ years it
     refuses every planned entry (487 in the chain) and only sends
     keep-alive round trips.
   * The studies counted such attempts as "still running". The count is
     in `research/ftmo_frozen_accounts.py` and the correction in
     `research/ftmo_scale_out_v2.md`. The bot now logs `FROZEN` and the
     preflight prints the room left.

## The four runs

### funded, low first: 2012-06-28 → 2026-10-29

* 3605 sessions, 50470 bot ticks, 1 accounts in a chain, 3603 plans checked.
* 145 entries checked (signal, stop, size); 33 planned entries the bot refused or skipped; 144 keep-alive round trips.
* 145 trades: 143 ended by the 5 steps' stops, 1 cut short by the account's own flatten (guard, target), 1 open at the end.
* 790 deals checked against the oracle: 150 part closes and 497 stop moves among them.
* Of the 143 trades the 5 steps ended: 87 reached +1R first (60.8%), 65 went on to +1.5R, 30 had their stop trailed; 56 lost at the first stop (39.2%, 1 in 2.6).
* Before costs: mean +0.271R per trade, average win +1.10R, average loss -1.02R; average first risk 2.11% of the balance.
* Sessions whose lowest equity crossed an FTMO line (a gap through the stops; FTMO would have ended the account, the replay goes on): 2015-08-21 (daily), 2019-10-02 (daily).
* **Mismatches: 0.**

| account | opened | closed | ended by | balance | trading days |
|---|---|---|---|---|---|
| 1 | 2012-06-28 | 2026-10-29 | end of the data | 31,737.86 | 271 |
### funded, high first: 2012-06-28 → 2026-10-29

* 3605 sessions, 50470 bot ticks, 1 accounts in a chain, 3603 plans checked.
* 143 entries checked (signal, stop, size); 32 planned entries the bot refused or skipped; 146 keep-alive round trips.
* 143 trades: 141 ended by the 5 steps' stops, 1 cut short by the account's own flatten (guard, target), 1 open at the end.
* 792 deals checked against the oracle: 150 part closes and 501 stop moves among them.
* Of the 141 trades the 5 steps ended: 86 reached +1R first (61.0%), 66 went on to +1.5R, 31 had their stop trailed; 55 lost at the first stop (39.0%, 1 in 2.6).
* Before costs: mean +0.283R per trade, average win +1.12R, average loss -1.02R; average first risk 2.09% of the balance.
* Sessions whose lowest equity crossed an FTMO line (a gap through the stops; FTMO would have ended the account, the replay goes on): 2015-08-21 (daily).
* **Mismatches: 0.**

| account | opened | closed | ended by | balance | trading days |
|---|---|---|---|---|---|
| 1 | 2012-06-28 | 2026-10-29 | end of the data | 31,381.51 | 272 |
### challenge, low first: 2012-06-28 → 2026-10-29

* 3605 sessions, 50470 bot ticks, 6 accounts in a chain, 3600 plans checked.
* 55 entries checked (signal, stop, size); 487 planned entries the bot refused or skipped; 185 keep-alive round trips.
* 55 trades: 47 ended by the 5 steps' stops, 8 cut short by the account's own flatten (guard, target), 0 open at the end.
* 304 deals checked against the oracle: 51 part closes and 206 stop moves among them.
* Of the 47 trades the 5 steps ended: 26 reached +1R first (55.3%), 23 went on to +1.5R, 11 had their stop trailed; 21 lost at the first stop (44.7%, 1 in 2.2).
* Before costs: mean +0.229R per trade, average win +1.29R, average loss -1.08R; average first risk 2.17% of the balance.
* Sessions whose lowest equity crossed an FTMO line (a gap through the stops; FTMO would have ended the account, the replay goes on): 2015-08-24 (max-loss).
* **Mismatches: 0.**

| account | opened | closed | ended by | balance | trading days |
|---|---|---|---|---|---|
| 1 | 2012-06-28 | 2013-04-10 | profit target reached; review the phase on FTMO | 16,564.12 | 13 |
| 2 | 2013-04-11 | 2013-09-16 | profit target reached; review the phase on FTMO | 16,634.63 | 9 |
| 3 | 2013-09-17 | 2014-12-19 | profit target reached; review the phase on FTMO | 16,564.03 | 30 |
| 4 | 2014-12-22 | 2015-07-14 | profit target reached; review the phase on FTMO | 16,656.81 | 12 |
| 5 | 2015-07-15 | 2015-08-24 | equity 13,216.93 within 30.00 of the max-loss line 13,500.00 | 13,216.93 | 5 |
| 6 | 2015-08-25 | 2026-10-29 | end of the data | 13,724.95 | 164 |
### challenge, high first: 2012-06-28 → 2026-10-29

* 3605 sessions, 50470 bot ticks, 6 accounts in a chain, 3600 plans checked.
* 55 entries checked (signal, stop, size); 487 planned entries the bot refused or skipped; 185 keep-alive round trips.
* 55 trades: 47 ended by the 5 steps' stops, 8 cut short by the account's own flatten (guard, target), 0 open at the end.
* 304 deals checked against the oracle: 51 part closes and 206 stop moves among them.
* Of the 47 trades the 5 steps ended: 26 reached +1R first (55.3%), 23 went on to +1.5R, 11 had their stop trailed; 21 lost at the first stop (44.7%, 1 in 2.2).
* Before costs: mean +0.229R per trade, average win +1.29R, average loss -1.08R; average first risk 2.17% of the balance.
* Sessions whose lowest equity crossed an FTMO line (a gap through the stops; FTMO would have ended the account, the replay goes on): 2015-08-24 (max-loss).
* **Mismatches: 0.**

| account | opened | closed | ended by | balance | trading days |
|---|---|---|---|---|---|
| 1 | 2012-06-28 | 2013-04-10 | profit target reached; review the phase on FTMO | 16,564.12 | 13 |
| 2 | 2013-04-11 | 2013-09-16 | profit target reached; review the phase on FTMO | 16,634.63 | 9 |
| 3 | 2013-09-17 | 2014-12-19 | profit target reached; review the phase on FTMO | 16,564.03 | 30 |
| 4 | 2014-12-22 | 2015-07-14 | profit target reached; review the phase on FTMO | 16,656.81 | 12 |
| 5 | 2015-07-15 | 2015-08-24 | equity 13,216.93 within 30.00 of the max-loss line 13,500.00 | 13,216.93 | 5 |
| 6 | 2015-08-25 | 2026-10-29 | end of the data | 13,724.95 | 164 |

# 2026-11-10: the audit again, with free slots

Appended 2026-11-10. The report above is as it was written on 2026-11-09.

On 2026-11-10 the operator ordered free slots on (`free_slots: true`;
`research/ftmo_slots_sizing.md`, "Operator's order"). The audit was run
again on the bot with that rule, and once more with the old rule for
comparison: eight runs.

    python -B scripts/ftmo_replay.py --data-dir <dir> --mode funded|challenge
        --order low_first|high_first --slots free|all --report <file> --json <file>

`scripts/ftmo_replay.py` sha256 `3646c08f…`; the same four input files
as above. The bot was this commit's code, less two changes the code
review then asked for in `ftmo_bot/runner.py`: with free slots off the
plan no longer reads the open positions, and a price step that cannot
be read keeps a slot taken instead of raising. Neither can show in the
replay: the simulated broker has no price step and its reads do not
fail.

## What changed in the audit

* **The slot rule in the oracle.** `takes_slot` in the script states it
  apart from the bot: a position takes one of the two slots unless its
  stop is at or over its entry. Checked with it:
  * after every tick, at most two open positions take a slot and no
    index has two positions;
  * every plan holds the best FAST-4 signals for the slots not taken,
    and nothing else;
  * every entry had a slot when it was sent;
  * no planned entry is refused for want of a slot.
* **Frozen accounts are replaced.** In the runs above a frozen account
  stayed in the chain to the end of the data (account 6, 10½ years).
  Now the next session starts a fresh account once the bot has said
  FROZEN and the account is flat with no room over the max-loss line
  and its buffer. That is what the operator would do, and it lets the
  chain cover the whole history. Checked both ways: a frozen account
  that skips an entry says FROZEN, and the bot never says it with room
  left.
* **`--slots all`** runs the rule as it was (every open position takes
  a slot), so both rules pass through the same audit.
* **The check on the checker.** Five more tests in
  `tests/test_ftmo_replay.py` break the bot on purpose and require the
  replay to report it: a plan that ignores free slots; an entry check
  that counts every position; a slot freed before the stop is at the
  entry; a bot that never says FROZEN; a bot that says it with room
  left.
* **Not exercised here.** On MT5 the bot counts a stop within half a
  price step under the entry as at the entry (the broker rounds stops).
  The simulated broker has no price step, so the replay only ever sees
  the plain rule. That slack, and a price step that cannot be read, are
  covered by `tests/test_ftmo_free_slots.py` alone.

## Result: 0 mismatches

Free slots (`--slots free`, what the bot runs):

| run | accounts | plans checked | entries checked | entries beside two or more open | most open at once | deals checked | part closes | stop moves | trades the 5 steps ended | reached +1R first | mean per trade, before costs | mismatches |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| funded, low first | 1 | 3,603 | 208 | 96 | 4 | 1,019 | 205 | 608 | 206 | 119 (57.8%) | +0.188R | **0** |
| funded, high first | 1 | 3,603 | 208 | 94 | 4 | 1,019 | 205 | 608 | 206 | 119 (57.8%) | +0.188R | **0** |
| challenge, low first | 25 | 3,589 | 210 | 68 | 4 | 695 | 165 | 370 | 160 | 69 (43.1%) | -0.202R | **0** |
| challenge, high first | 25 | 3,589 | 210 | 66 | 4 | 695 | 165 | 370 | 160 | 69 (43.1%) | -0.201R | **0** |
| all four | | 14,384 | 836 | 324 | | 3,428 | 740 | 1,956 | 732 | 376 (51.4%) | | **0** |

Every open position takes a slot (`--slots all`, the rule until
2026-11-10):

| run | accounts | plans checked | entries checked | entries beside two or more open | most open at once | deals checked | part closes | stop moves | trades the 5 steps ended | reached +1R first | mean per trade, before costs | mismatches |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| funded, low first | 1 | 3,603 | 145 | 0 | 2 | 790 | 150 | 497 | 143 | 87 (60.8%) | +0.271R | **0** |
| funded, high first | 1 | 3,603 | 143 | 0 | 2 | 792 | 150 | 501 | 141 | 86 (61.0%) | +0.283R | **0** |
| challenge, low first | 21 | 3,589 | 166 | 0 | 2 | 783 | 149 | 499 | 135 | 75 (55.6%) | +0.087R | **0** |
| challenge, high first | 19 | 3,589 | 162 | 0 | 2 | 764 | 151 | 480 | 133 | 74 (55.6%) | +0.100R | **0** |
| all four | | 14,384 | 616 | 0 | | 3,129 | 600 | 1,977 | 552 | 322 (58.3%) | | **0** |

## Reading

1. **The bot applies free slots as written.** 836 entries,
   324 of them made beside two or more open positions, and
   3,428 deals match the oracle. There were never more than two
   positions with a stop under their entry, and never two on one index.
2. **The old rule still passes the same audit**, frozen-account
   replacement included: 616 entries, 3,129 deals, 0 mismatches.
3. **One funded account over the whole history, before costs** (low
   first; high first in brackets):

   | | every position takes a slot | free slots |
   |---|---|---|
   | entries | 145 (143) | 208 (208) |
   | reached +1R before the stop | 60.8% (61.0%) | 57.8% (57.8%) |
   | mean per trade | +0.271R (+0.283R) | +0.188R (+0.188R) |
   | average first risk, of the balance | 2.11% (2.09%) | 1.88% (1.88%) |
   | balance at the end, from 15,000 | 31,737.86 (31,381.51) | 29,634.64 (29,649.04) |
   | sessions under an FTMO line | 2015-08-21 daily, 2019-10-02 daily | 2015-08-24 daily |

   More trades, less on each, as the study measured
   (`research/ftmo_slots_sizing.md`: 216 trades at +0.079R against 153
   at +0.13R to +0.15R, after costs).
4. **The challenge chain** (Phase 1 target +10%; low first; one path,
   not a rate):
   * free slots: 25 accounts: 15 reached the Phase 1 target, 8 froze, 1 breached, 1 still running at the end;
   * every position takes a slot: 21 accounts: 15 reached the Phase 1 target, 4 froze, 1 breached, 1 still running at the end.

   A chain is one sequence of start dates, each set by how the account
   before it ended. The study's tables count every start date.
5. **"Reached +1R first" in challenge mode is not a win rate.** The
   target lock closes winning trades before their stop (48 of
   the 210 trades with free slots, 29 of 166 without), so the trades
   the 5 steps ended are mostly the losers.
6. **Costs are zero here**, as above. This audits what the bot does,
   not what it earns.

## The eight runs

### funded, low first, slots free: 2012-06-28 → 2026-10-29

* 3605 sessions, 50470 bot ticks, 1 accounts in a chain, 3603 plans checked.
* Slots: a position whose stop is at or over its entry takes none (free slots). 96 entries were made with two or more positions already open; most open at once: 4.
* 208 entries checked (signal, slot, stop, size); 37 planned entries the bot refused or skipped; 128 keep-alive round trips.
* 208 trades: 206 ended by the 5 steps' stops, 2 cut short by the account's own flatten (guard, target), 0 open at the end.
* 1019 deals checked against the oracle: 205 part closes and 608 stop moves among them.
* Of the 206 trades the 5 steps ended: 119 reached +1R first (57.8%), 91 went on to +1.5R, 39 had their stop trailed; 87 lost at the first stop (42.2%, 1 in 2.4).
* Before costs: mean +0.188R per trade, average win +1.08R, average loss -1.04R; average first risk 1.88% of the balance.
* Sessions whose lowest equity crossed an FTMO line (a gap through the stops; FTMO would have ended the account, the replay goes on): 2015-08-24 (daily).
* **Mismatches: 0.**

| account | opened | closed | ended by | balance | trading days |
|---|---|---|---|---|---|
| 1 | 2012-06-28 | 2026-10-29 | end of the data | 29,634.64 | 312 |

### funded, high first, slots free: 2012-06-28 → 2026-10-29

* 3605 sessions, 50470 bot ticks, 1 accounts in a chain, 3603 plans checked.
* Slots: a position whose stop is at or over its entry takes none (free slots). 94 entries were made with two or more positions already open; most open at once: 4.
* 208 entries checked (signal, slot, stop, size); 37 planned entries the bot refused or skipped; 128 keep-alive round trips.
* 208 trades: 206 ended by the 5 steps' stops, 2 cut short by the account's own flatten (guard, target), 0 open at the end.
* 1019 deals checked against the oracle: 205 part closes and 608 stop moves among them.
* Of the 206 trades the 5 steps ended: 119 reached +1R first (57.8%), 91 went on to +1.5R, 39 had their stop trailed; 87 lost at the first stop (42.2%, 1 in 2.4).
* Before costs: mean +0.188R per trade, average win +1.08R, average loss -1.04R; average first risk 1.88% of the balance.
* Sessions whose lowest equity crossed an FTMO line (a gap through the stops; FTMO would have ended the account, the replay goes on): 2015-08-24 (daily).
* **Mismatches: 0.**

| account | opened | closed | ended by | balance | trading days |
|---|---|---|---|---|---|
| 1 | 2012-06-28 | 2026-10-29 | end of the data | 29,649.04 | 312 |

### challenge, low first, slots free: 2012-06-28 → 2026-10-29

* 3605 sessions, 50470 bot ticks, 25 accounts in a chain, 3589 plans checked.
* Slots: a position whose stop is at or over its entry takes none (free slots). 68 entries were made with two or more positions already open; most open at once: 4.
* 210 entries checked (signal, slot, stop, size); 31 planned entries the bot refused or skipped; 145 keep-alive round trips.
* 210 trades: 160 ended by the 5 steps' stops, 48 cut short by the account's own flatten (guard, target), 2 open at the end.
* 695 deals checked against the oracle: 165 part closes and 370 stop moves among them.
* Of the 160 trades the 5 steps ended: 69 reached +1R first (43.1%), 41 went on to +1.5R, 11 had their stop trailed; 91 lost at the first stop (56.9%, 1 in 1.8).
* Before costs: mean -0.202R per trade, average win +0.90R, average loss -1.04R; average first risk 2.30% of the balance.
* Sessions whose lowest equity crossed an FTMO line (a gap through the stops; FTMO would have ended the account, the replay goes on): 2015-08-24 (max-loss).
* **Mismatches: 0.**

| account | opened | closed | ended by | balance | trading days |
|---|---|---|---|---|---|
| 1 | 2012-06-28 | 2012-09-07 | profit target reached; review the phase on FTMO | 16,564.10 | 5 |
| 2 | 2012-09-10 | 2012-12-28 | frozen: no room left over the max-loss line and its buffer | 13,712.87 | 8 |
| 3 | 2012-12-31 | 2013-09-18 | profit target reached; review the phase on FTMO | 16,603.91 | 14 |
| 4 | 2013-09-19 | 2013-12-26 | profit target reached; review the phase on FTMO | 16,580.69 | 10 |
| 5 | 2013-12-27 | 2014-08-04 | frozen: no room left over the max-loss line and its buffer | 13,715.76 | 16 |
| 6 | 2014-08-05 | 2015-08-24 | equity 13,189.20 within 30.00 of the max-loss line 13,500.00 | 13,189.20 | 25 |
| 7 | 2015-08-25 | 2016-08-01 | frozen: no room left over the max-loss line and its buffer | 13,725.03 | 15 |
| 8 | 2016-08-02 | 2017-02-13 | profit target reached; review the phase on FTMO | 16,596.50 | 11 |
| 9 | 2017-02-14 | 2017-07-17 | profit target reached; review the phase on FTMO | 16,571.24 | 8 |
| 10 | 2017-07-18 | 2017-11-16 | profit target reached; review the phase on FTMO | 16,598.11 | 8 |
| 11 | 2017-11-17 | 2018-03-08 | profit target reached; review the phase on FTMO | 16,583.65 | 9 |
| 12 | 2018-03-09 | 2018-08-29 | profit target reached; review the phase on FTMO | 16,555.39 | 11 |
| 13 | 2018-08-30 | 2018-10-11 | frozen: no room left over the max-loss line and its buffer | 13,725.06 | 6 |
| 14 | 2018-10-12 | 2019-08-05 | frozen: no room left over the max-loss line and its buffer | 13,594.46 | 17 |
| 15 | 2019-08-06 | 2020-01-10 | profit target reached; review the phase on FTMO | 16,551.15 | 9 |
| 16 | 2020-01-13 | 2020-08-12 | frozen: no room left over the max-loss line and its buffer | 13,714.30 | 13 |
| 17 | 2020-08-13 | 2022-01-21 | frozen: no room left over the max-loss line and its buffer | 13,725.16 | 36 |
| 18 | 2022-01-24 | 2023-07-12 | profit target reached; review the phase on FTMO | 16,551.01 | 25 |
| 19 | 2023-07-13 | 2023-10-04 | frozen: no room left over the max-loss line and its buffer | 13,725.06 | 7 |
| 20 | 2023-10-05 | 2024-01-22 | profit target reached; review the phase on FTMO | 16,637.10 | 5 |
| 21 | 2024-01-23 | 2024-07-16 | profit target reached; review the phase on FTMO | 16,606.02 | 11 |
| 22 | 2024-07-17 | 2024-11-06 | profit target reached; review the phase on FTMO | 16,663.87 | 13 |
| 23 | 2024-11-07 | 2025-08-13 | profit target reached; review the phase on FTMO | 16,568.11 | 15 |
| 24 | 2025-08-14 | 2025-10-24 | profit target reached; review the phase on FTMO | 16,576.97 | 5 |
| 25 | 2025-10-27 | 2026-10-29 | end of the data | 14,355.04 | 20 |

### challenge, high first, slots free: 2012-06-28 → 2026-10-29

* 3605 sessions, 50470 bot ticks, 25 accounts in a chain, 3589 plans checked.
* Slots: a position whose stop is at or over its entry takes none (free slots). 66 entries were made with two or more positions already open; most open at once: 4.
* 210 entries checked (signal, slot, stop, size); 31 planned entries the bot refused or skipped; 145 keep-alive round trips.
* 210 trades: 160 ended by the 5 steps' stops, 48 cut short by the account's own flatten (guard, target), 2 open at the end.
* 695 deals checked against the oracle: 165 part closes and 370 stop moves among them.
* Of the 160 trades the 5 steps ended: 69 reached +1R first (43.1%), 41 went on to +1.5R, 11 had their stop trailed; 91 lost at the first stop (56.9%, 1 in 1.8).
* Before costs: mean -0.201R per trade, average win +0.90R, average loss -1.04R; average first risk 2.30% of the balance.
* Sessions whose lowest equity crossed an FTMO line (a gap through the stops; FTMO would have ended the account, the replay goes on): 2015-08-24 (max-loss).
* **Mismatches: 0.**

| account | opened | closed | ended by | balance | trading days |
|---|---|---|---|---|---|
| 1 | 2012-06-28 | 2012-09-07 | profit target reached; review the phase on FTMO | 16,564.10 | 5 |
| 2 | 2012-09-10 | 2012-12-28 | frozen: no room left over the max-loss line and its buffer | 13,712.87 | 8 |
| 3 | 2012-12-31 | 2013-09-18 | profit target reached; review the phase on FTMO | 16,603.91 | 14 |
| 4 | 2013-09-19 | 2013-12-26 | profit target reached; review the phase on FTMO | 16,580.69 | 10 |
| 5 | 2013-12-27 | 2014-08-04 | frozen: no room left over the max-loss line and its buffer | 13,715.76 | 16 |
| 6 | 2014-08-05 | 2015-08-24 | equity 13,189.20 within 30.00 of the max-loss line 13,500.00 | 13,189.20 | 25 |
| 7 | 2015-08-25 | 2016-08-01 | frozen: no room left over the max-loss line and its buffer | 13,725.03 | 15 |
| 8 | 2016-08-02 | 2017-02-13 | profit target reached; review the phase on FTMO | 16,596.50 | 11 |
| 9 | 2017-02-14 | 2017-07-17 | profit target reached; review the phase on FTMO | 16,571.24 | 8 |
| 10 | 2017-07-18 | 2017-11-16 | profit target reached; review the phase on FTMO | 16,598.11 | 8 |
| 11 | 2017-11-17 | 2018-03-08 | profit target reached; review the phase on FTMO | 16,583.65 | 9 |
| 12 | 2018-03-09 | 2018-08-29 | profit target reached; review the phase on FTMO | 16,555.39 | 11 |
| 13 | 2018-08-30 | 2018-10-11 | frozen: no room left over the max-loss line and its buffer | 13,725.06 | 6 |
| 14 | 2018-10-12 | 2019-08-05 | frozen: no room left over the max-loss line and its buffer | 13,594.46 | 17 |
| 15 | 2019-08-06 | 2020-01-10 | profit target reached; review the phase on FTMO | 16,551.15 | 9 |
| 16 | 2020-01-13 | 2020-08-12 | frozen: no room left over the max-loss line and its buffer | 13,714.30 | 13 |
| 17 | 2020-08-13 | 2022-01-21 | frozen: no room left over the max-loss line and its buffer | 13,725.16 | 36 |
| 18 | 2022-01-24 | 2023-07-12 | profit target reached; review the phase on FTMO | 16,551.01 | 25 |
| 19 | 2023-07-13 | 2023-10-04 | frozen: no room left over the max-loss line and its buffer | 13,725.06 | 7 |
| 20 | 2023-10-05 | 2024-01-22 | profit target reached; review the phase on FTMO | 16,637.10 | 5 |
| 21 | 2024-01-23 | 2024-07-16 | profit target reached; review the phase on FTMO | 16,606.02 | 11 |
| 22 | 2024-07-17 | 2024-11-06 | profit target reached; review the phase on FTMO | 16,663.87 | 13 |
| 23 | 2024-11-07 | 2025-08-13 | profit target reached; review the phase on FTMO | 16,577.02 | 15 |
| 24 | 2025-08-14 | 2025-10-24 | profit target reached; review the phase on FTMO | 16,576.97 | 5 |
| 25 | 2025-10-27 | 2026-10-29 | end of the data | 14,355.04 | 20 |

### funded, low first, slots all: 2012-06-28 → 2026-10-29

* 3605 sessions, 50470 bot ticks, 1 accounts in a chain, 3603 plans checked.
* Slots: every open position takes one of the two (free slots off). Most open at once: 2.
* 145 entries checked (signal, slot, stop, size); 33 planned entries the bot refused or skipped; 144 keep-alive round trips.
* 145 trades: 143 ended by the 5 steps' stops, 1 cut short by the account's own flatten (guard, target), 1 open at the end.
* 790 deals checked against the oracle: 150 part closes and 497 stop moves among them.
* Of the 143 trades the 5 steps ended: 87 reached +1R first (60.8%), 65 went on to +1.5R, 30 had their stop trailed; 56 lost at the first stop (39.2%, 1 in 2.6).
* Before costs: mean +0.271R per trade, average win +1.10R, average loss -1.02R; average first risk 2.11% of the balance.
* Sessions whose lowest equity crossed an FTMO line (a gap through the stops; FTMO would have ended the account, the replay goes on): 2015-08-21 (daily), 2019-10-02 (daily).
* **Mismatches: 0.**

| account | opened | closed | ended by | balance | trading days |
|---|---|---|---|---|---|
| 1 | 2012-06-28 | 2026-10-29 | end of the data | 31,737.86 | 271 |

### funded, high first, slots all: 2012-06-28 → 2026-10-29

* 3605 sessions, 50470 bot ticks, 1 accounts in a chain, 3603 plans checked.
* Slots: every open position takes one of the two (free slots off). Most open at once: 2.
* 143 entries checked (signal, slot, stop, size); 32 planned entries the bot refused or skipped; 146 keep-alive round trips.
* 143 trades: 141 ended by the 5 steps' stops, 1 cut short by the account's own flatten (guard, target), 1 open at the end.
* 792 deals checked against the oracle: 150 part closes and 501 stop moves among them.
* Of the 141 trades the 5 steps ended: 86 reached +1R first (61.0%), 66 went on to +1.5R, 31 had their stop trailed; 55 lost at the first stop (39.0%, 1 in 2.6).
* Before costs: mean +0.283R per trade, average win +1.12R, average loss -1.02R; average first risk 2.09% of the balance.
* Sessions whose lowest equity crossed an FTMO line (a gap through the stops; FTMO would have ended the account, the replay goes on): 2015-08-21 (daily).
* **Mismatches: 0.**

| account | opened | closed | ended by | balance | trading days |
|---|---|---|---|---|---|
| 1 | 2012-06-28 | 2026-10-29 | end of the data | 31,381.51 | 272 |

### challenge, low first, slots all: 2012-06-28 → 2026-10-29

* 3605 sessions, 50470 bot ticks, 21 accounts in a chain, 3589 plans checked.
* Slots: every open position takes one of the two (free slots off). Most open at once: 2.
* 166 entries checked (signal, slot, stop, size); 11 planned entries the bot refused or skipped; 155 keep-alive round trips.
* 166 trades: 135 ended by the 5 steps' stops, 29 cut short by the account's own flatten (guard, target), 2 open at the end.
* 783 deals checked against the oracle: 149 part closes and 499 stop moves among them.
* Of the 135 trades the 5 steps ended: 75 reached +1R first (55.6%), 50 went on to +1.5R, 22 had their stop trailed; 60 lost at the first stop (44.4%, 1 in 2.2).
* Before costs: mean +0.087R per trade, average win +0.99R, average loss -1.04R; average first risk 2.45% of the balance.
* Sessions whose lowest equity crossed an FTMO line (a gap through the stops; FTMO would have ended the account, the replay goes on): 2015-08-24 (max-loss).
* **Mismatches: 0.**

| account | opened | closed | ended by | balance | trading days |
|---|---|---|---|---|---|
| 1 | 2012-06-28 | 2013-04-10 | profit target reached; review the phase on FTMO | 16,564.12 | 13 |
| 2 | 2013-04-11 | 2013-09-16 | profit target reached; review the phase on FTMO | 16,634.63 | 9 |
| 3 | 2013-09-17 | 2014-12-19 | profit target reached; review the phase on FTMO | 16,564.03 | 30 |
| 4 | 2014-12-22 | 2015-07-14 | profit target reached; review the phase on FTMO | 16,656.81 | 12 |
| 5 | 2015-07-15 | 2015-08-24 | equity 13,216.93 within 30.00 of the max-loss line 13,500.00 | 13,216.93 | 5 |
| 6 | 2015-08-25 | 2016-08-01 | frozen: no room left over the max-loss line and its buffer | 13,725.03 | 15 |
| 7 | 2016-08-02 | 2017-06-02 | profit target reached; review the phase on FTMO | 16,731.87 | 16 |
| 8 | 2017-06-05 | 2017-10-12 | profit target reached; review the phase on FTMO | 16,560.82 | 8 |
| 9 | 2017-10-13 | 2018-01-11 | profit target reached; review the phase on FTMO | 16,585.09 | 7 |
| 10 | 2018-01-12 | 2018-09-26 | profit target reached; review the phase on FTMO | 16,564.76 | 15 |
| 11 | 2018-09-27 | 2018-11-14 | frozen: no room left over the max-loss line and its buffer | 13,725.02 | 5 |
| 12 | 2018-11-15 | 2019-09-05 | profit target reached; review the phase on FTMO | 16,591.98 | 16 |
| 13 | 2019-09-06 | 2020-08-12 | frozen: no room left over the max-loss line and its buffer | 13,701.89 | 19 |
| 14 | 2020-08-13 | 2021-04-29 | profit target reached; review the phase on FTMO | 16,552.00 | 14 |
| 15 | 2021-04-30 | 2023-04-13 | frozen: no room left over the max-loss line and its buffer | 13,725.13 | 34 |
| 16 | 2023-04-14 | 2023-06-27 | profit target reached; review the phase on FTMO | 16,587.54 | 7 |
| 17 | 2023-06-28 | 2024-03-08 | profit target reached; review the phase on FTMO | 16,581.53 | 15 |
| 18 | 2024-03-11 | 2024-09-13 | profit target reached; review the phase on FTMO | 16,575.31 | 11 |
| 19 | 2024-09-16 | 2024-12-02 | profit target reached; review the phase on FTMO | 16,583.50 | 4 |
| 20 | 2024-12-03 | 2026-02-09 | profit target reached; review the phase on FTMO | 16,583.25 | 24 |
| 21 | 2026-02-10 | 2026-10-29 | end of the data | 15,077.00 | 14 |

### challenge, high first, slots all: 2012-06-28 → 2026-10-29

* 3605 sessions, 50470 bot ticks, 19 accounts in a chain, 3589 plans checked.
* Slots: every open position takes one of the two (free slots off). Most open at once: 2.
* 162 entries checked (signal, slot, stop, size); 10 planned entries the bot refused or skipped; 156 keep-alive round trips.
* 162 trades: 133 ended by the 5 steps' stops, 27 cut short by the account's own flatten (guard, target), 2 open at the end.
* 764 deals checked against the oracle: 151 part closes and 480 stop moves among them.
* Of the 133 trades the 5 steps ended: 74 reached +1R first (55.6%), 52 went on to +1.5R, 22 had their stop trailed; 59 lost at the first stop (44.4%, 1 in 2.3).
* Before costs: mean +0.100R per trade, average win +1.01R, average loss -1.04R; average first risk 2.45% of the balance.
* Sessions whose lowest equity crossed an FTMO line (a gap through the stops; FTMO would have ended the account, the replay goes on): 2015-08-24 (max-loss).
* **Mismatches: 0.**

| account | opened | closed | ended by | balance | trading days |
|---|---|---|---|---|---|
| 1 | 2012-06-28 | 2013-04-10 | profit target reached; review the phase on FTMO | 16,564.12 | 13 |
| 2 | 2013-04-11 | 2013-09-16 | profit target reached; review the phase on FTMO | 16,634.63 | 9 |
| 3 | 2013-09-17 | 2014-12-19 | profit target reached; review the phase on FTMO | 16,564.03 | 30 |
| 4 | 2014-12-22 | 2015-07-14 | profit target reached; review the phase on FTMO | 16,656.81 | 12 |
| 5 | 2015-07-15 | 2015-08-24 | equity 13,216.93 within 30.00 of the max-loss line 13,500.00 | 13,216.93 | 5 |
| 6 | 2015-08-25 | 2016-08-01 | frozen: no room left over the max-loss line and its buffer | 13,725.03 | 15 |
| 7 | 2016-08-02 | 2017-06-02 | profit target reached; review the phase on FTMO | 16,731.87 | 16 |
| 8 | 2017-06-05 | 2017-10-12 | profit target reached; review the phase on FTMO | 16,560.82 | 8 |
| 9 | 2017-10-13 | 2018-01-11 | profit target reached; review the phase on FTMO | 16,585.09 | 7 |
| 10 | 2018-01-12 | 2020-01-10 | profit target reached; review the phase on FTMO | 16,550.69 | 41 |
| 11 | 2020-01-13 | 2020-08-12 | frozen: no room left over the max-loss line and its buffer | 13,714.30 | 13 |
| 12 | 2020-08-13 | 2021-04-29 | profit target reached; review the phase on FTMO | 16,552.00 | 14 |
| 13 | 2021-04-30 | 2023-04-13 | frozen: no room left over the max-loss line and its buffer | 13,725.13 | 34 |
| 14 | 2023-04-14 | 2023-06-27 | profit target reached; review the phase on FTMO | 16,587.54 | 7 |
| 15 | 2023-06-28 | 2024-03-08 | profit target reached; review the phase on FTMO | 16,581.53 | 15 |
| 16 | 2024-03-11 | 2024-09-13 | profit target reached; review the phase on FTMO | 16,575.31 | 11 |
| 17 | 2024-09-16 | 2024-12-02 | profit target reached; review the phase on FTMO | 16,583.50 | 4 |
| 18 | 2024-12-03 | 2026-02-09 | profit target reached; review the phase on FTMO | 16,606.30 | 24 |
| 19 | 2026-02-10 | 2026-10-29 | end of the data | 15,077.00 | 14 |


## Repeated on the committed code (2026-11-11)

All eight runs were made again on commit `47019ed` itself: the bot and
`scripts/ftmo_replay.py` byte for byte as committed, with the two review
changes in. Every report and every figure came out identical to the runs
above, file for file. **0 mismatches.**
