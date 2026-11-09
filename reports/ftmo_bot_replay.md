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
