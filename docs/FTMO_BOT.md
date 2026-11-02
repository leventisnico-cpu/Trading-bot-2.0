# FTMO bot — FAST-4 on MetaTrader 5

Built 2026-10-04 on the operator's order: "build the FTMO connection at
3% risk". It runs FAST-4 (`research/ftmo_fast_pass.md`) on an FTMO
2-Step account through the MetaTrader 5 terminal.

## Read this first

The research verdict for FAST-4 is **NO-GO** for a fast pass
(`research/ftmo_fast_pass.md`; re-run 2026-11-02 on data to 2026-10-29
with the same verdict). The bot's risk controls change how attempts end,
not the speed (`research/ftmo_bot_policy.md`,
`reports/ftmo_bot_policy.md`). At 3% risk per trade, by the start date
of the attempt:

| measure | bot, 2011–18 starts | bot, 2019–26 starts | bare rule, 2019–26 starts |
|---|---|---|---|
| both phases passed, within the data | 29% | 70% | 23% |
| breached a rule (fee lost) | 41% | 1% | 77% |
| still running when the data ends | 30% | 29% | 0% |
| both phases within 18 months | 9% | 17% | 18% |
| days to pass, median | 670 | 858 | 392 |
| funded account survives 1 year | 85% | 99% | 36% |
| funded 1-year return, median of survivors | +3.9% | +6.6% | +10.1% |
| fees per funded account (EUR 89 per attempt) | 2.4 (EUR 214) | 1.02 (EUR 90) | 4.3 (EUR 381) |

What this means: the bot rarely loses an account in a good regime (the
cap keeps every open stop above FTMO's lines; the lock keeps a reached
target) and still loses 41% of attempts in a hard one (gaps through the
stops), but it is slow either way: about 2 years to pass both phases,
and only about one attempt in six passes within 18 months. The
evaluation has no time limit, so a slow attempt keeps running at no
extra cost; only a breach costs a new fee. Funded, the median return is
+3.9% to +6.6% a year on the account size, of which the trader keeps
80%. The bot executes the rule faithfully; it does not change these
odds.

**Why two positions could fail the account in one day, and the cap.**
FTMO's daily line is day-start *balance* minus 5%, and balance ignores
floating P&L, so open risk counts in full against every day's 5%. Two
positions at 3% each (6%) cross it if both stops are hit. That was the
main failure in the research. With `cap_combined_risk: true` (the
default) each entry is sized so that all open stops together stay above
both loss lines: the first position risks 3%, a second one gets what is
left (about 1.8%). On the 2025-2026 replay this widened the closest
approach to the daily line from 43 to 177 and delayed Phase 1 from 204
to 236 weekdays. What it cannot stop: a gap that opens beyond the stops.
The right-hand column above includes the cap; the left one does not.

## What it does

* Trades the four FTMO US index CFDs (`US100.cash`, `US500.cash`,
  `US30.cash`, `US2000.cash`; check the names in Market Watch).
* After the US close (16:05 New York) it rebuilds each index's
  09:30–16:00 session bars from 30-minute bars and computes FAST-4:
  buy when close > 200-day average and RSI(2) < 10; exit when close >
  5-day average or after 10 sessions.
* At the next US open (09:31–10:30 New York) it sends exits first, then
  entries: 3% of balance at risk, stop at entry − 3 × ATR(14) resting in
  MT5, at most two positions, notional at most 3× balance. Each plan is
  executed at most once: it is marked done and saved before any order
  is sent, so a crash or restart can miss a trade but never double it.
  A plan older than the previous session is thrown away.
* Exits are never blocked. A close that fails is retried every minute
  until it succeeds; positions the bot finds open but does not know are
  adopted, never forgotten. If MT5 cannot report positions, the bot does
  nothing that minute.
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
* **Keep-alive:** if 25 days pass without an opened position, it opens
  and closes the minimum lot on US500, in every phase (FTMO ends an
  account with no new trade for 30 days, funded accounts too).
* **One account per state file.** When the terminal is logged into a
  different account (the next phase), the bot starts fresh and keeps the
  old state under the old login's name. Nothing to delete by hand.
* **Server clock:** MT5 stamps bars in the server's local time. The bot
  fits the rule (New York + 7 h, EET, CET or UTC) to a fresh tick at
  start-up, checks it before every bar read, and refuses to plan while a
  reading fits no rule, so a wrong session boundary never becomes a plan.
* **Dry run by default.** Orders are only logged unless the config says
  `dry_run: false` **and** you start it with `--execute`.
* `python -m ftmo_bot flat` closes every bot position and drops the
  pending plan: FTMO pays out only on a flat account.

It never sees your password. You log the terminal in; the bot attaches
to it.

## FTMO's rules the bot implements (checked 2026-11-02)

Read on ftmo.com (trading objectives, FAQ, the terms dated 2026-10-12).
Re-read them before buying; FTMO changes them.

| FTMO rule (2-Step, Swing) | what the bot does |
|---|---|
| Maximum Daily Loss: equity may not fall below the balance at 00:00 Prague time minus 5% of the initial balance; floating P&L counts | the FTMO day rolls at Prague midnight on the PC's clock; the guard flattens 0.2% above the line; every open stop together stays above it (`cap_combined_risk`) |
| Maximum Loss: equity may not fall below 90% of the initial balance, static | the same guard on the 90% line; entries stop for good after it |
| Profit target 10% (Phase 1), 5% (Verification), none on the funded account | `profit_target`; the target lock above |
| 4 minimum trading days per phase, a trading day being a Prague calendar day on which a position is opened; none on the funded account | Prague dates of opened positions only; the lock adds missing days with minimum-lot round trips |
| No time limit | none assumed |
| Inactivity: no new trade for 30 consecutive days ends the account, in every phase | keep-alive after 25 days, in every phase |
| Swing account: overnight and weekend holding allowed in every phase, no news restriction; leverage 1:15 on indices, 1:9 on US2000 | FAST-4 holds up to 10 sessions, so buy **Swing** (a Standard funded account ends on the first weekend hold, and Standard cannot be changed to Swing later); notional capped at 3× balance per position |
| Forbidden: opening a trade within 2 hours of a market close of 2 hours or more, opposite positions across accounts, more than 2,000 server requests a day, letting a third party trade the account | entries only 09:31–10:30 New York; long only; a handful of orders a week; you run the bot yourself |
| Server clock GMT+2 in winter and GMT+3 in summer, changing with the US clocks (New York + 7 h); the daily reset is Prague midnight | fitted and checked at run time; the preflight prints it |
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
dry-run week on FTMO's own MT5 terminal.

### Result (2026-10-16, last session of the two-week test)

**Verdict: the bot is ready for the next step, the preflight and
dry-run week on FTMO's MT5 terminal (setup steps 6–7). It is not proven
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
2. Run the preflight and a dry-run week on FTMO's MT5 terminal: first a
   free trial or demo account if FTMO offers one, otherwise the paid
   account in dry-run. Live orders only after that week looks right.
3. The odds above have not changed. Each evaluation fee buys about a
   one-in-five chance of passing within 18 months.

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

1. **Free trial first.** FTMO offers a free 14-day trial on MT5 with
   the 2-Step rules at half target (5%, 2 trading days, the same loss
   lines; it ends if nothing is traded in the first 7 days). Do steps
   3–6 on it, then run the bot **with real orders on the trial** (step
   8): it is free, and real fills, stops and order routing are what
   paper cannot test. Use `profit_target: 0.05`, `min_trading_days: 2`
   and `keepalive_days: 5`, so the bot opens a trade inside the first
   week even without a FAST-4 signal. If FTMO asks for payment for the
   trial, use any MT5 demo account instead (the bot only needs a
   logged-in terminal; put that broker's index symbol names in
   `symbols`). The trial's login differs from the challenge's, so the
   bot keeps a separate state for it automatically.
2. **Buy the FTMO 2-Step challenge yourself:** **MetaTrader 5**, the
   **Swing** account type, **USD**. The research was done at 3% risk per
   trade; the account size only sets the fee (the $10k account is EUR 89,
   the $25k one EUR 250) and the minimum-lot rounding. The fee comes
   back with the first payout. FTMO emails the login; you type it into
   the terminal, it never goes in this repo.
3. In MT5: Tools → Options → Expert Advisors → tick **Allow algorithmic
   trading**, then press the **Algo Trading** button so it is green.
   Add the four symbols to Market Watch.
4. Install Python 3.11+ and the dependencies:

   ```powershell
   py -m pip install -r deploy\ftmo\requirements.txt
   ```

5. Copy the config and leave it in dry-run:

   ```powershell
   copy deploy\ftmo\config.example.yaml state\ftmo_config.yaml
   ```

   Set `initial_balance` to the account size you bought (10000 for the
   $10k account): FTMO's loss lines are percentages of it, and the bot
   warns at start-up if the account balance disagrees. Set
   `profit_target` to `0.10` for Phase 1. Set `mt5_path` if the
   terminal is not found automatically.
6. Preflight (read-only):

   ```powershell
   py -m ftmo_bot preflight --config state\ftmo_config.yaml
   ```

   Every symbol must print PASS with 205+ sessions (if not, raise
   Tools → Options → Charts → Max bars in chart and restart the
   terminal). The `server clock:` line should read `UTC+2` (`UTC+3` in
   summer) with `rule NY+7`. If it says `unverified`, run it again while
   the index CFDs are trading; if it says the reading fits no known
   rule, stop and report it. Compare the printed last session date and
   close with the index on a chart before going further.

   Any time, to see what the bot will do at the next open (read-only):

   ```powershell
   py -m ftmo_bot plan --config state\ftmo_config.yaml
   ```

   It prints the exits and entries from the last completed session, with
   the approximate entry price and stop.
7. **Dry-run for at least one full week:**

   ```powershell
   py -m ftmo_bot run --config state\ftmo_config.yaml
   ```

   Read `state\ftmo_bot.log` each day: the plan after 16:05 New York, the
   "DRY-RUN buy" lines at the next open, lot sizes and stops. A second
   entry while one position is open is cut by `cap_combined_risk` (the
   log says "cut from X to Y lots"): that is intended, so both stops
   together stay above FTMO's loss lines. Set it to `false` only if you
   accept that two stops in one day can fail the account.
8. Go live on the evaluation only after the dry-run week looks right:
   set `dry_run: false` in `state\ftmo_config.yaml`, then

   ```powershell
   py -m ftmo_bot run --config state\ftmo_config.yaml --execute
   ```

   Keep the PC (or VPS) and the terminal running on weekdays.
9. When the bot halts with "profit target reached", check FTMO's
   dashboard: the phase shows as passed once FTMO's own check runs
   (within a day). FTMO then emails the Verification account's login.
   Log the terminal into it, set `profit_target: 0.05`, and start step 8
   again: the bot sees the new login, starts fresh, and keeps the old
   state file under the old login's name.
10. On the funded account set `profit_target: null`. Keep-alive stays
    on. To request a payout (from day 14, only on a flat account):

    ```powershell
    py -m ftmo_bot flat --config state\ftmo_config.yaml --execute
    ```

    then request it on FTMO's dashboard, and start step 8 again once it
    is processed. The payout itself is your decision, never the bot's.

## Things that could not be verified from here

* The exact FTMO symbol names, contract sizes, minimum lots and filling
  mode (the adapter picks FOK, IOC or RETURN from the symbol's
  settings). The preflight prints them.
* The server clock on FTMO's own server (the bot fits it at run time;
  the preflight shows the reading).
* That a minimum-lot round trip counts as an opened position for FTMO's
  trading days and inactivity rule. By FTMO's definition it does.
* FTMO's current rules: re-read them on ftmo.com before buying.

The free trial and the dry-run week exist to catch the first two.
