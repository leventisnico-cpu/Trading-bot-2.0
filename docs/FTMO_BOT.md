# FTMO bot — FAST-4 on MetaTrader 5

Built 2026-10-04 on the operator's order: "build the FTMO connection at
3% risk". It runs FAST-4 (`research/ftmo_fast_pass.md`) on an FTMO
2-Step account through the MetaTrader 5 terminal.

## Read this first

The research verdict for FAST-4 is **NO-GO** for a fast pass
(`research/ftmo_fast_pass.md`; re-run unchanged 2026-11-02 on data to
2026-10-29 with the same verdict, `reports/ftmo_fast_pass_rerun_2026-10-29.md`). The bot's risk controls change how attempts end,
not the speed (`research/ftmo_bot_policy.md`,
`reports/ftmo_bot_policy.md`). At 3% risk per trade, by the start date
of the attempt; each bot cell is a range between a lock that fills at
the day's high (optimistic) and one that waits for the next open
(pessimistic):

Since 2026-11-08 the bot's exits are the 5 steps (`exit_mode: scale_out`,
the operator's order; `research/ftmo_scale_out.md`, V1). Since
2026-11-09, also by the operator's order ("buffer on"), the cap keeps all
open stops 1.5% above the max-loss line: `cap_max_loss_buffer: 0.015`, W2
of `research/ftmo_scale_out_v2.md`. W2 did not pass its pre-registered
rule. The default columns are both together. The FAST-4 exit columns are
`exit_mode: fast4` with the old 0.2% buffer.

**Frozen accounts (measured 2026-11-09, `research/ftmo_frozen_accounts.py`).**
An attempt that neither passed nor breached was reported as "still
running". Most of those are frozen: flat, with no risk room left over
the max-loss line, so the bot can open nothing more and the attempt
cannot pass. The table counts them on their own row.

| measure | FAST-4 exits, 2011–18 starts | FAST-4 exits, 2019–26 starts | bare rule, 2019–26 starts | **5 steps + 1.5% buffer (default)**, 2011–18 starts | **5 steps + 1.5% buffer (default)**, 2019–26 starts |
|---|---|---|---|---|---|
| both phases passed, within the data | 24–29% | 68–70% | 23% | 38–43% | 37–40% |
| breached a rule (fee lost) | 41–43% | 1% | 77% | 15–16% | 2% |
| **frozen**: flat, no room left, cannot pass | 29–31% | 10% | none (no cap) | 42–47% | 42% |
| still trading when the data ends | 1% | 19–21% | 0% | 0% | 16–19% |
| both phases within 18 months | 7–9% | 14–17% | 18% | 31–38% | 20–24% |
| days to pass, median | 670–699 | 858–870 | 392 | 307–328 | 459–533 |
| funded account survives 1 year (a frozen one counts as surviving) | 85% | 99% | 36% | 81% | 99% |
| funded 1-year return, median of survivors | +3.9% | +6.6% | +10.1% | +0.5% | +2.5% |
| attempts per pass, a frozen attempt counted as lost (EUR 89 each) | 3.4–4.1 (EUR 303–363) | 1.15–1.17 (EUR 102–104) | 4.3 (EUR 381) | 2.3–2.7 (EUR 205–238) | 2.1–2.2 (EUR 185–196) |

What this means for the FAST-4 exits:

* **Good regime (2019–26 starts):** the bot rarely breaches (1%), because
  the cap keeps every open stop above FTMO's lines and the lock keeps a
  reached target. A further 10% of attempts freeze.
* **Hard regime (2011–18 starts):** about 42% of attempts breach (gaps
  through the stops) and another 30% freeze.
* **Speed:** slow either way. It takes about 2 to 2.4 years to pass both
  phases. Only one attempt in six or seven passes within 18 months, even
  in the good regime.
* **Cost:** the evaluation has no time limit, so a slow attempt keeps
  running at no extra cost. A breached or frozen one costs a new fee.
* **Funded:** the median return is +3.9% to +6.6% a year on the account
  size, of which the trader keeps 80%.

The bot executes the rule faithfully; it does not change these odds.

What it means for the default (the 5 steps with the 1.5% buffer):

* **Passes:** 31–38% of 2011–18 attempts and 20–24% of 2019–26 ones
  pass within 18 months.
* **Breaches and freezes:** 15–16% and 2% of attempts breach, and 42–47%
  and 42% freeze. Counting a frozen attempt as lost, it takes 2.1 to 2.7
  attempts per pass.
* **Losers:** every loser is a full −1R stop, often held for weeks.
* **Funded:** the median survivor makes +0.5% to +2.5% a year on the
  account, frozen accounts included. The buffer trims entries whenever
  the account is down about 3.7% or more.
* **No exit rule wins 30 trades in 31.** The 5 steps win 61–62% of
  trades (2012–2026). A trade loses when price falls 1R before it rises
  1R, and the entry decides that before step 3 can happen. What 30 in 31
  would take is measured in `research/ftmo_win_rate_dial.md`: a first
  target a tenth as far away as the stop.

**The bot's own 5 steps, audited over 2012–2026** (2026-11-09,
`scripts/ftmo_replay.py`, `reports/ftmo_bot_replay.md`):

* The same `Runner` the MT5 bot runs traded a simulated account through
  14 years of daily bars, in both bar orders, as a funded account and as
  a chain of challenge accounts.
* Every plan, entry size, part close, stop move, trail and stop-out was
  checked against an oracle written separately from the bot: 2,190 deals
  in 398 trades, **0 mismatches**. The exits have no bug to fix.
* 60% of the bot's own trades reached +1R before −1R (1 loss in 2.6).
* It runs with zero costs: it audits what the bot does, not what it
  earns.
* It found the frozen accounts above: one challenge account lost four
  trades in a row by April 2016 and then could open nothing for 10½
  years.

**Two fixes tested and rejected** (2026-11-09,
`research/ftmo_slots_sizing.md`, written down before the run):

* **More of the signals.** The account takes 153 of 990 FAST-4 signals:
  a position keeps one of the two slots until its last quarter is sold.
  Freeing the slot once the stop is at the entry takes 216. But the
  payoff per trade falls from +0.13–0.15R to +0.08R, breaches rise in
  every period, and fewer attempts pass within the data.
* **Safer sizing.** Letting an entry risk only a third of the room left
  over the max-loss line ends the freezes and cuts breaches. But far
  fewer attempts pass (18% against 38–42% for 2019–26 starts): the
  accounts it saves trade on too small to recover.
* **Both together** pass more often for 2019–26 starts and less often
  for 2011–18 starts.
* None passed its rule, so the bot is unchanged. The slots and the
  sizing are not what holds the system back; the entry's thin edge is
  (+0.13–0.15R per trade, about ten trades a year).

**The buffer: on (`cap_max_loss_buffer: 0.015`) against off (`0.002`)**
(W2, `research/ftmo_scale_out_v2.md`; on by the operator's order of
2026-11-09). 5 steps, 2011–18 / 2019–26 starts:

| measure | 5 steps, buffer off (`0.002`) | 5 steps, buffer on (`0.015`, default) |
|---|---|---|
| breached a rule | 37% / 12–13% | 15–16% / 2% |
| both phases within 18 months | 34–41% / 19–24% | 31–38% / 20–24% |
| **frozen**: flat, no room left, cannot pass | 17% / 30% | 42–47% / 42% |
| still trading when the data ends | 0% / 16–19% | 0% / 16–19% |
| both phases passed, within the data | 46–47% / 38–42% | 38–43% / 37–40% |
| attempts per pass, a frozen attempt counted as lost | 2.15–2.16 / 2.01–2.14 | 2.30–2.67 / 2.08–2.20 |
| funded account survives 1 year (a frozen one counts) | 68% / 95% | 81% / 99% |
| funded 1-year return, median of survivors | +3.8–4.0% / +2.8% | +0.5% / +2.5% |

**The buffer turns breaches into frozen accounts; it does not add
passes.**

* Off passes more often in every cell (46–47% against 38–43%; 38–42%
  against 37–40%) and needs fewer attempts per pass.
* W2 did not pass its pre-registered rule.
* It is on by the operator's order of 2026-11-09. He gave that order
  before the frozen accounts were measured, on a trade-off that did not
  count them. He has been told and advised to turn it off again
  (`cap_max_loss_buffer: 0.002`). Until he decides it stays on.
* A frozen account is not closed by FTMO. Lowering the buffer lets the
  bot trade what is left.

**Why two positions could fail the account in one day, and the cap.**
FTMO's daily line is day-start *balance* minus 5%, and balance ignores
floating P&L, so open risk counts in full against every day's 5%. Two
positions at 3% each (6%) cross it if both stops are hit. That was the
main failure in the research. With `cap_combined_risk: true` (the
default) each entry is sized so that all open stops together stay 0.2%
above the daily line and 1.5% above the max-loss line
(`cap_max_loss_buffer`): the first position risks 3%, a second one gets
what is left (about 1.8%), and once the account is down about 3.7% the
max-loss buffer trims new entries further. The preflight prints the cap
as `risk cap: ...`. On the 2025-2026 replay the 0.2% cap widened the closest
approach to the daily line from 43 to 177 and delayed Phase 1 from 204
to 236 weekdays. What it cannot stop: a gap that opens beyond the stops.
The two bot columns above include the cap; the bare-rule column does not.

## What it does

* Trades the four FTMO US index CFDs (`US100.cash`, `US500.cash`,
  `US30.cash`, `US2000.cash`; check the names in Market Watch).
* After the US close (16:05 New York) it rebuilds each index's
  09:30–16:00 session bars from 30-minute bars and computes FAST-4:
  buy when close > 200-day average and RSI(2) < 10.
* **Exits: the 5 steps** (`exit_mode: scale_out`, the operator's order
  of 2026-11-08; `ftmo_bot/scale_out.py`). 1R is the first stop's
  distance, 3 × ATR(14):
  1. and 2. 3% of balance at risk to the first stop (the deck's 30% of
     the account × a 10% stop is the same 3%);
  3. at entry + 1R: close 1/2, stop to the entry;
  4. at entry + 1.5R: close 1/4, stop to entry + 1R;
  5. the last 1/4 is never sold by hand: after each session its stop
     rises to 1R under the highest close since entry.

  No SMA5 or time exit. The part closes and stop moves run weekdays
  09:31–17:00 New York, polled every minute; the stop rests in MT5 around
  the clock. A position keeps the exit rule it was opened with, so
  `exit_mode: fast4` (close > 5-day average or 10 sessions, the rule
  until 2026-11-08) can be switched back at any time.
* **What the 5 steps measured** (`research/ftmo_scale_out.md`, V1,
  2012–2026; and the two shadow runs):
  * 61–62% of trades win. A trade loses when price falls 1R before it
    rises 1R; that is decided by the entry before step 3 can happen, so
    no exit rule turns it into 30 wins in 31.
  * Both phases passed within 18 months in 34–41% (2011–18) and 19–24%
    (2019–26) of attempts, against 7–9% and 14–17% with the FAST-4 exits.
    But 12–13% of 2019–26 attempts breached a rule, against 1%. Losers
    are full −1R stops, often held for weeks.
  * In 2011–18 the 5 steps also breached less (37% of attempts against
    41–43%). In 2019–26, 46–49% of attempts were still running when the
    data ended, against 29–31%.
  * **Two safety rules, tested 2026-11-09 (`research/ftmo_scale_out_v2.md`):**
    * A 10-session time stop made things worse.
    * A 1.5% max-loss buffer cut breaches to 15–16% and 2%, but the
      attempts it saved from a breach froze instead. It did not pass its
      rule. It is **on** by the operator's order of 2026-11-09 (see
      "The buffer" above).
    * 2% risk instead of 3% cut 2011–18 breaches (to 21–28%) but raised
      2019–26 ones (to 14–20%), and slowed passes (16–20% within 18
      months).
  * Live shadow, 2026-10-05 to 11-06 (`research/ftmo_shadow_5step/`): two
    full −1R stops (QQQ −449.80, SPY −270.02) and DIA open; −4.8%
    balance, −6.8% equity, low −7.5%. The FAST-4 exits on the same bars:
    −0.4%. Neither trade reached +1R (they peaked at +0.44R and +0.53R),
    so the shadow has not yet run a part close or a stop move: those
    paths are covered by unit tests only (`tests/test_ftmo_scale_out.py`).
  * If the bot is not running at the close, the trail is raised by the
    first plan it makes afterwards, at any hour. A refused part close or
    stop move is retried after 5 minutes. For a refused close, see the
    next bullets.
* At the next US open (09:31–10:30 New York) it sends exits first, then
  entries: 3% of balance at risk, stop at entry − 3 × ATR(14) resting in
  MT5, at most two positions, notional at most 3× balance. Each plan is
  executed at most once: it is marked done and saved before any order
  is sent, so a crash or restart can miss a trade but never double it.
  A plan older than the previous session is thrown away.
* Exits are never blocked. A close that fails is retried until it
  succeeds:
  * every minute while a target lock, a guard block or a halt is in
    force, and a close queued then stays at every minute until it closes;
  * otherwise (a planned exit, a 5-step stop level) at once, then after
    1, 2, 4 and 8 minutes, then every 15. A closed market refuses every
    attempt, and FTMO counts server requests (at most 2,000 a day).

  Positions the bot finds open but does not know are adopted, never
  forgotten. If MT5 cannot report positions, the bot does nothing that
  minute.
* **Guard:** if equity comes within 0.2% of the account of FTMO's daily
  line (day-start balance − 5%) or the max-loss line (90% of initial),
  it closes everything and blocks entries until the next FTMO day (for
  good after the max-loss line).
* **Target lock:** the moment equity is 0.3% of the account above the
  phase target (room for closing costs), it closes everything and stops
  taking FAST-4 entries, so a reached target cannot be given back. If
  FTMO's 4 minimum trading days are not met yet, it opens and closes the
  minimum lot on US500 once per FTMO day until they are. Then it halts
  with "profit target reached", so you can confirm the phase on FTMO's
  dashboard. If equity falls back under the target before that, the lock
  is released and normal trading resumes.
* **Trading days** are counted the way FTMO counts them: a Prague
  calendar day on which a position was opened. Closes count for nothing.
* **Keep-alive:** in the first session on a new account, and whenever
  25 days pass without an opened position, it opens and closes the
  minimum lot on US500, in every phase (FTMO ends an account with no new
  trade for 30 days, counted from when the account was opened, funded
  accounts too). These round trips open only 10:00–10:45 New York, more
  than two hours before any close (FTMO forbids opening a trade within
  two hours of a close of two hours or more).
* **One account per state file.** When the terminal is logged into a
  different account, the bot parks the old account's state under its
  login and resumes the new one's, or starts fresh for a new phase.
  Switching back and forth (the free trial, a phase review) loses
  nothing. Nothing to delete by hand. The state files are git-ignored.
  **Stop `run` before you log the terminal into another account:** a
  running bot that sees the login change does nothing and logs an error
  every minute until it is restarted.
* **One bot process at a time.** `run` and `flat` hold a lock on the
  state file; a second copy refuses to start, so two windows can never
  send the same plan twice.
* **Server clock:** MT5 stamps bars in the server's local time. FTMO's
  server runs New York + 7 hours (GMT+2, GMT+3 in summer); the example
  config pins that rule, and the bot checks it against a fresh tick every
  minute and before every bar read. It refuses to plan on a reading that
  does not fit, and stale ticks (market closed, holidays) never count.
  Starting the bot on a weekend is fine: the clock is verified when the
  index CFDs reopen on Sunday evening. If today's session still cannot
  be read at the open, the exits planned the evening before run anyway,
  and the entries wait until 10:30 New York for the clock, then are
  skipped for the day.
* **Two opt-ins, one account.** Orders are only logged unless the config
  says `dry_run: false` **and** you start it with `--execute`
  (`run.ps1 -Live`), and they go only to the account the config names
  in `login` (the bot refuses to start otherwise). The challenge config
  starts in dry-run; the free-trial config sends orders (demo money).
* `python -m ftmo_bot flat` closes every bot position and drops the
  pending plan: FTMO pays out only on a flat account. Stop `run` first.
  In dry-run it only reports what it would close and changes nothing.

It never sees your password. You log the terminal in; the bot attaches
to it.

## FTMO's rules the bot implements (checked 2026-11-02)

Read on ftmo.com (trading objectives, FAQ, the terms dated 2026-10-12).
Re-read them before buying; FTMO changes them.

| FTMO rule (2-Step, Swing) | what the bot does |
|---|---|
| Maximum Daily Loss: equity may not fall below the balance at 00:00 Prague time minus 5% of the initial balance; floating P&L counts | the FTMO day rolls at Prague midnight on the PC's clock; the guard flattens 0.2% above the line; every open stop together stays above it (`cap_combined_risk`) |
| Maximum Loss: equity may not fall below 90% of the initial balance, static | the same guard on the 90% line; entries stop for good after it; all open stops together stay 1.5% above it (`cap_max_loss_buffer`) |
| Profit target 10% (Phase 1), 5% (Verification), none on the funded account | `profit_target`; the target lock above |
| 4 minimum trading days per phase, a trading day being a Prague calendar day on which a position is opened; none on the funded account | Prague dates of opened positions only; the lock adds missing days with minimum-lot round trips |
| No time limit | none assumed |
| Inactivity: no new trade for 30 consecutive days ends the account, in every phase | keep-alive after 25 days, in every phase, even with both slots held (the 5 steps hold for weeks) |
| Swing account: overnight and weekend holding allowed in every phase, no news restriction; leverage 1:15 on indices, 1:9 on US2000 | the 5 steps hold for weeks (FAST-4's exits: up to 10 sessions), so buy **Swing** (a Standard funded account ends on the first weekend hold, and Standard cannot be changed to Swing later); notional capped at 3× balance per position |
| Forbidden: opening a trade within 2 hours of a market close of 2 hours or more, opposite positions across accounts, more than 2,000 server requests a day, letting a third party trade the account | entries only 09:31–10:30 and round trips only 10:00–10:45 New York (more than 2 hours before a 13:00 early close); long only; a handful of orders a week; you run the bot yourself |
| Server clock GMT+2 in winter and GMT+3 in summer, changing with the US clocks (New York + 7 h); the daily reset is Prague midnight | `server_clock: NY+7`, checked against a live tick before every bar read; the preflight prints it |
| Funded account: payouts from day 14, only with no open positions; 80% split, scaling every 4 months | `python -m ftmo_bot flat` before you request one |
| Profit in a currency other than the account's costs 0.7% | choose a **USD** account; the indices settle in USD |

Sources: ftmo.com/en/trading-objectives, /en/2-step-challenge,
/en/faq/ftmo-swing-account-type, /en/faq/do-i-have-to-close-my-positions-overnight-or-before-the-weekend,
/en/forbidden-trading-practices, /en/faq/how-many-accounts-can-i-have,
/en/reward-growth-and-scaling-plan, /en/faq/how-do-i-withdraw-my-profits,
/en/ftmo-free-trial, /en/trading-updates (2026-10-29 and 2026-10-15),
cdn.ftmo.com terms and conditions (2026-10-12).

## Paper validation (2026-10-04 to 2026-10-18)

Two runs check the bot before any money goes to FTMO:

1. **Astral paper deployment 1999** (saved strategy 6489, "FAST-4 FTMO
   shadow (index ETFs)"): the same rule on QQQ/SPY/DIA/IWM, $15,000 of
   paper capital. It replaced deployment 1949, whose data feed failed on
   2026-10-05 19:36 UTC (source_failed, flat, no orders). 1949 was
   undeployed and the same strategy redeployed on 2026-10-06 14:19 UTC.
   It was healthy and ready to trade at 14:21 UTC. Astral bug report
   fc0b281e. Monday 2026-10-05's close was not evaluated on Astral; the
   shadow run covers it. It fills real paper orders at Astral, but sizes 49% of
   equity per position (Astral cannot size by risk), so its P&L is not
   the FTMO bot's. Its 2019-2026 backtest: 221 trades, 70.6% win rate,
   profit factor 1.77, which agrees with the research.
2. **The bot itself, shadow-run** (`scripts/ftmo_shadow.py`, state and
   journal in `research/ftmo_shadow/`): the unchanged `ftmo_bot.Runner`
   trades a simulated CAD 15,000 FTMO account (`ftmo_bot/broker_sim.py`)
   on live Astral 30-minute bars, every 30 minutes of each session, with
   3% risk, the guard, the loss lines, the target and the keep-alive.
   The daily check after the close updates it and compares its plan
   with Astral's signals.

Before the live run, the same harness replayed 2025-02-10 to 2026-10-02
(`reports/ftmo_shadow_replay.md`): 0 errors in 236 trading weekdays,
all 21 entries matching an independent signal computation, Phase 1
reached on 2026-01-05, no limit breached (closest approach to the daily
line 177, positions marked at each 30-minute bar's low). The shadow
polls every 30 minutes, so its entries fill at 10:05 instead of ~09:31,
and ETF proxies stand in for the CFDs.

The replay also caught a bug before any money was at risk: the bot
fetched 5,000 half-hour bars, which is 380 sessions of US cash hours but
only ~108 sessions of a CFD trading 23 hours a day, so on FTMO it would
never have had a 200-session average and never traded. It now fetches
15,000 bars (~320 sessions) and refuses to plan, loudly, with fewer
than 205.

What paper cannot test: FTMO's symbol names, contract sizes, server
clock and order filling. Those are covered only by the preflight and the
free trial (real orders, demo money) on FTMO's own MT5 terminal.

### Result (2026-10-16, last session of the two-week test)

**Verdict: the bot is ready for the next step, the preflight and a
first run on FTMO's MT5 terminal (now the free trial: Setup below). It is not proven
for live money yet. FAST-4 itself is still NO-GO for a fast pass.**

**The bot (shadow run, 2026-10-05 to 2026-10-16, ten sessions):**
* No tick errors, no guard trips, and no flags in any session.
* One FAST-4 signal, on the 2026-10-14 close:
  - QQQ RSI(2) 3.2 and SPY RSI(2) 7.4, both above their 200-day average;
  - IWM was below its 200-day average, so the trend filter blocked it.
* Both entries filled at 10:05 ET on 2026-10-15:
  - QQQ 15.91 at 716.93, stop 688.66 (3 × ATR);
  - SPY 14.03 at 765.40, stop 746.15.
* The combined-risk cap cut SPY from 23.37 lots, so both stops together
  risk $720, or 4.8% of the account.
* Every day's plan matched an independent RSI(2)/SMA200 computation.
  That includes 2026-10-09, when Astral entered on bad data and the bot
  correctly did nothing.
* At the 2026-10-16 close:
  - equity 14,863.32 (−0.91%), lowest 14,781.21 (−1.46%);
  - the daily floor (14,250) and the max-loss floor (13,500) were never
    approached;
  - both positions are still open, on day 2 of 10.
* No exit had run yet. Both ran the next week (see "Round trip" below).

**Astral deployment 1999 is not usable as an execution reference:**
* data feed failure on 2026-10-05 (redeployed);
* false entries and failed stop protection on 10-09;
* repeated price-feed failures and re-activation loops;
* on 10-14, a duplicated QQQ entry six minutes before the close and no
  SPY entry;
* position marks that do not update.

Bug reports fc0b281e and d573b589 were filed. A third, for 10-14, was
prepared but not sent. Details are in `research/air3_daily_log.md`.

**What this test did not cover:**
* exits (signal exits are covered since; see "Round trip" below) and
  the 10-session time stop;
* the profit target and keep-alive in a real account;
* FTMO's symbols, contract sizes and filling;
* the MT5 server clock;
* real order routing.

**Next steps:**
1. Done 2026-10-22: the shadow kept running until the QQQ and SPY
   trades closed, so the exit path has been seen once.
2. Run the preflight and then the free trial with real orders (demo
   money) on FTMO's MT5 terminal (Setup, steps 6–10; another broker's
   MT5 demo if FTMO charges for the trial). Then the paid challenge, in
   dry-run for at least one session first (steps 11–14).
3. The odds above have not changed. (Revised 2026-11-02 with the bot's
   risk controls: see "Read this first" at the top.)

### Round trip (2026-10-21 and 10-22): both exits ran

The shadow kept running after the two-week test until both trades
closed. Both exits were planned the evening before, and both plans
matched the independent computation.

* **SPY:** closed at 768.53 on 10-20, above its SMA5 (767.92). The bot
  sold at 10:05 ET on 10-21: 14.03 lots at 770.67, **+$73.91**.
* **QQQ:** closed at 725.42 on 10-21, above its SMA5 (719.77). The bot
  sold at 10:05 ET on 10-22: 15.91 lots at 714.33, **−$41.41**.
  - QQQ opened 1.6% below the close that signalled the exit. The trade
    was worth +$135.06 at that close and filled at a loss.
  - That is FAST-4's next-open exit working as designed, not a fault.
    The research models the same fill.
* **Net:** balance **15,032.51 (+0.22%)** after 14 sessions (10-05 to
  10-22).
  - One win and one loss. Two trades say nothing about the 70% win rate.
  - The lowest equity of the whole run was 14,781.21 (−1.46%), on 10-16.
* The day-start balance and the daily floor moved up with the realized
  profit, as FTMO computes them: 15,073.91 and 14,323.91 on 10-22.
* No tick errors, guard trips or flags in any session.
* The closes above are the ones the bot acted on. Astral has since
  revised them (SPY 769.01, QQQ 725.21); both are still above their
  SMA5s, so both exits stand.
* Astral 1999 gives no comparison for the exits. It sold its QQQ on
  10-19 on a phantom bar and has been flat since.

**Now covered:**
* the SMA5 exit;
* next-open exit fills;
* realized P&L flowing into the day-start balance and the daily floor.

**Still not covered:**
* the 10-session time stop;
* a stop-loss fill;
* the profit target and the keep-alive;
* FTMO's symbols, contract sizes, filling, server clock and order
  routing.

The daily shadow run continues, flat until the next FAST-4 signal, so a
time stop or a stop-loss exit can be seen as well.

## Setup (Windows PC or Windows VPS outside the US)

The bot runs on Windows next to FTMO's MetaTrader 5 terminal and
attaches to it. It never asks for or stores a password: you log the
terminal in yourself. Two scripts do the work, both run from the repo
folder in PowerShell:

* `deploy\ftmo\setup.ps1`: one-time setup (Python environment, packages,
  the config at `state\ftmo_config.yaml`);
* `deploy\ftmo\run.ps1`: `-Preflight` (checks, sends nothing), `-Plan`
  (what it does at the next open), `-DryRun` (orders only logged),
  `-Live` (real orders), `-Flat` (close every bot position).

### Once per PC

1. Install **Python 3.12, 64-bit**, from python.org and tick **Add
   python.exe to PATH** in the installer. 3.11 to 3.14 also work; 3.15
   (python.org's newest) does not yet, because the MetaTrader5 package has
   no build for it.
2. Install Git (git-scm.com), open PowerShell and get the bot (sign in to
   GitHub if asked):

   ```powershell
   git clone -b claude/mini-prop-os-trading-zmm4ym https://github.com/leventisnico-cpu/Trading-bot-2.0.git
   cd Trading-bot-2.0
   ```

   (Until PR #4 is merged the bot lives on that branch. Without Git: on
   GitHub pick the branch, Code → Download ZIP, unzip, and open
   PowerShell in the folder.)
3. Run the setup:

   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy\ftmo\setup.ps1
   ```

   It finds Python, creates `.venv`, installs MetaTrader5, PyYAML and
   tzdata, installs the free-trial config as `state\ftmo_config.yaml`,
   checks that the bot loads, and ends with `Setup done`. Run again, it
   keeps your config.
4. Keep the PC awake on weekdays: Settings → System → Power → Screen
   and sleep → Never (when plugged in). Set Windows Update's active
   hours to cover the US session (09:30–16:00 New York). After a restart
   the bot resumes from its state file once you start it again.
5. To update the bot later: stop it (Ctrl+C), then `git pull` and step 3
   again (your config is kept), and start it.

### The free trial (first)

FTMO's free 14-day trial has the 2-Step rules at half target: 5% profit
target, 2 trading days, the same 5% daily and 10% maximum loss lines; it
ends if nothing is traded in its first 7 days. The bot runs on it with
**real orders** (demo money): real fills, stops, lot sizes and the
server clock are what paper cannot test.

6. Sign up for the free trial yourself on ftmo.com: **MetaTrader 5**,
   **USD**, the **Swing** type if offered (the challenge's), any size.
   FTMO emails the MT5 login and server.
7. Install FTMO's MetaTrader 5 (link in FTMO's client area) and log in
   to the trial (you type the password; tick "Save password" so it
   reconnects after a restart). Then:
   * Tools → Options → Expert Advisors → tick **Allow algorithmic
     trading**, and press the **Algo Trading** button so it is green;
   * Market Watch (Ctrl+M) → right-click → Symbols: show `US30.cash`,
     `US100.cash`, `US500.cash` and `US2000.cash`.
8. Preflight (reads only, sends nothing):

   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy\ftmo\run.ps1 -Preflight
   ```

   Check, line by line:
   * `FAIL cannot reach the MT5 terminal`: open MT5 and log in first;
     with several MT5 terminals installed, set `mt5_path` in
     `state\ftmo_config.yaml` to FTMO's `terminal64.exe`;
   * `account`: the trial's login, USD, `algo trading ON`;
   * `rules:`: the initial balance is the account size (`from the
     account` on a new account), the max-loss line 10% under it and the
     profit target 5% over it, as on FTMO's dashboard;
   * `WARN: login not set` with the login to set: that is step 9;
   * every symbol prints PASS with 205+ sessions. If one does not, open
     its M30 chart, press Home to load older bars (or raise Tools →
     Options → Charts → Max bars in chart and restart the terminal),
     and run the preflight again. Compare one printed last close with
     the chart;
   * `server clock:` reads `UTC+2` (`UTC+3` in summer) with
     `rule NY+7 [pinned]`. If it says `unverified`, run it again while
     the index CFDs are trading; if it mentions the PC clock, sync the
     PC's clock (Settings → Time & language → Date & time → Sync now);
     if the reading fits no known rule, stop and report it.

   Any time, `run.ps1 -Plan` prints what the bot will do at the next
   open (read-only).
9. Name the account the bot may trade: open `state\ftmo_config.yaml`
   in Notepad, replace the line `login: null` with the trial's login
   number (in FTMO's email; the preflight's WARN line shows it), for
   example `login: 1234567`, and save. It is the account number, not the
   password. Orders go only to that account: `-Live` refuses to start
   without it, or with the terminal on another account.

   **Self-test first** (once per trial account, on a weekday between
   10:00 and 10:45 New York time, with no `-Live` window running):

   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy\ftmo\run.ps1 -SelfTest
   ```

   It sends one tiny position through every order the 5 steps use:
   * it buys twice the minimum lot of `US500.cash` with a stop 5% under
     the price;
   * it closes half;
   * it moves the stop up;
   * it closes the rest.

   A quiet trial may never reach a target, and then these orders would
   stay unproven. Each prints `PASS` or `FAIL`, and the run ends with
   `self-test passed: this account takes every order the 5 steps send`.
   The round trip costs the spread on 0.02 lots and counts as the trial's
   first trading day. Its size is fixed: the combined-risk cap does not
   size it, but the bot's entry checks (halt, block, the guard at the
   loss lines) do apply. On a `FAIL`, send me the line and
   `state\ftmo_bot.log`. If an order fails midway, the bot closes what
   it opened; what it cannot close it queues, and `-Live` closes it.

   Then start the bot:

   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy\ftmo\run.ps1 -Live
   ```

   It prints the `rules:` line again as it starts. Leave the window
   open (Ctrl+C stops it; starting again resumes). In
   its first session (10:00–10:45 New York, weekdays) it opens and
   closes the minimum lot of `US500.cash` so the trial gets a trading
   day, and again whenever 5 days pass without a trade. FAST-4 itself
   trades only on a signal, about twice a month, so a quiet trial is
   normal. Read `state\ftmo_bot.log` each day: the plan after 16:05 New
   York, then the orders at the next open with lots and stops.
10. Before buying the challenge, the trial must show:
    * the self-test passed (four `PASS` lines);
    * the round trip filled and FTMO's dashboard counted the trading day;
    * any FAST-4 entry filled with a stop-loss at about 3 ATR and a lot
      size risking about 3%. A second entry is cut so both stops stay
      above FTMO's lines ("cut from X to Y lots" in the log, as intended);
    * no ERROR lines in the log, and no `FROZEN` warning. The preflight
      prints `room for the next entry: ...`; `WARN: FROZEN` there means
      the account can open nothing more.

**No free trial?** If FTMO asks for payment for the trial, use any
broker's free MT5 demo: in `state\ftmo_config.yaml` put that broker's
names for the four indices under `symbols` and set `server_clock: null`.
The trial's rule lines do not apply there; the orders get tested.

### The challenge

11. Buy the FTMO 2-Step challenge yourself: **MetaTrader 5**, the
    **Swing** account type (the bot holds over weekends; Standard cannot
    be changed to Swing later), **USD**. The research was done at 3% risk
    per trade; the account size only sets the fee (the $10k account is
    EUR 89, the $25k one EUR 250) and the minimum-lot rounding. The fee
    comes back with the first payout.
12. Stop the trial bot (Ctrl+C), switch to the challenge config and log
    the terminal into the challenge account:

    ```powershell
    powershell -ExecutionPolicy Bypass -File deploy\ftmo\setup.ps1 -Account challenge -Force
    ```

    It sets the 10% target, 4 minimum trading days, `dry_run: true` and
    an empty `login:`. The bot sees the new login and starts a fresh
    state; the trial's is kept under its login.
13. Preflight again (step 8): `rules:` must show the challenge's size,
    the 10% target and `of 4` trading days. Then dry-run, orders only
    logged ("DRY-RUN buy ..."): at least one session after a clean
    trial, a full week without one:

    ```powershell
    powershell -ExecutionPolicy Bypass -File deploy\ftmo\run.ps1 -DryRun
    ```

14. Go live: open `state\ftmo_config.yaml` in Notepad, set
    `dry_run: false` and `login:` to the challenge account's number,
    save, and start `run.ps1 -Live`. Keep the PC and the terminal running
    on weekdays.
15. When the bot halts with "profit target reached", check FTMO's
    dashboard: the phase shows as passed once FTMO's own check runs
    (within a day). FTMO then emails the Verification account's login.
    Log the terminal into it, set `profit_target: 0.05` and `login:` to
    the Verification account's number in `state\ftmo_config.yaml`, and
    start `run.ps1 -Live` again: the bot sees the new login, starts
    fresh, and keeps the old state file under the old login's name.
16. On the funded account set `profit_target: null` and `login:` to the
    funded account's number. Keep-alive stays
    on. To request a payout (from day 14, only on a flat account), stop
    the `-Live` window first (Ctrl+C; `-Flat` refuses while it runs),
    then:

    ```powershell
    powershell -ExecutionPolicy Bypass -File deploy\ftmo\run.ps1 -Flat
    ```

    It prints `flat` when nothing is left open. Request the payout on
    FTMO's dashboard, and start `run.ps1 -Live` again once it is
    processed. The payout itself is your decision, never the bot's.
17. **A halt you disagree with.** The bot halts after the target or the
    max-loss line, and stays halted across restarts. If FTMO's dashboard
    says the phase is not passed (for example, a trading day FTMO did not
    count), stop the bot and open `state\ftmo_state.json` in Notepad:
    set `"halted": null` and `"target_locked": null`, and remove any
    date from `"trading_days"` that FTMO does not show. Save, and start
    `run.ps1 -Live` again. Never clear a max-loss halt: that account has
    failed.

## Things that could not be verified from here

* The exact FTMO symbol names, contract sizes, minimum lots and filling
  mode (the adapter picks FOK, IOC or RETURN from the symbol's
  settings). The preflight prints them.
* The server clock on FTMO's own server (the bot fits it at run time;
  the preflight shows the reading).
* That a minimum-lot round trip counts as an opened position for FTMO's
  trading days and inactivity rule. By FTMO's definition it does.
* FTMO's current rules: re-read them on ftmo.com before buying.
* `setup.ps1` and `run.ps1` on Windows itself: they were parsed and run
  under PowerShell 7 (Linux) with stand-ins for Python, pip and the bot,
  in a one-off harness that is not kept in the repo (34 cases: both
  configs, an existing config kept, the `py` launcher and plain
  `python`, 32-bit, 3.10, 3.15 and Microsoft Store Pythons
  refused, an existing `.venv` checked, a `py` install prompt that must
  not hang it, a folder name with brackets, a pip failure, every
  `run.ps1` switch), not under Windows PowerShell 5.1 with the real
  MetaTrader5 package. The first setup on the PC is that test.

The free trial exists to catch the first two.
