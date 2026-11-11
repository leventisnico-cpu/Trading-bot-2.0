# Cowork task: run the FTMO free trial with the FAST-4 bot

Written 2026-11-05 by the Claude Code cloud session that built this bot.
Facts below are as of that date; after it, the repo is the source of truth.
Nico's style: one-line status first, then at most one thing for him to do.

## Start here

1. Read sections 0 to 4 before doing anything.
2. If `C:\Users\leven\Trading-bot-2.0` does not exist yet, give Nico the
   clone line from step 2 in section 5 first. Then request folder access to
   `~/Trading-bot-2.0` (VM path `$HOME/mnt/Trading-bot-2.0`) and delete
   permission for it (git needs it).
3. In the VM: `git status -sb`, `git log --oneline -3`, and the end of
   `state/ftmo_bot.log` if it exists.
4. Take one screenshot to see whether a PowerShell window or MetaTrader 5 is
   open and what it shows.
5. Tell Nico, in one line each, which step of section 5 he is on and the one
   next command.

## 0. Scope: which bot this is

- This is the **FAST-4 bot** in `leventisnico-cpu/Trading-bot-2.0`, on
  branch `claude/mini-prop-os-trading-zmm4ym`. The Python package is
  `ftmo_bot/`, the scripts are in `deploy/ftmo/`, and the runbook is
  `docs/FTMO_BOT.md`.
- It is **not** the `FTMO-TRADING-BIT` research pipeline. That is a
  different repo, folder, set of rules and stage. Don't mix the two.
- The ftmo-pc-operator skill gives you the **mechanics** to use here:
  - folder access through the Linux VM;
  - no typing in PowerShell: give Nico one copy-paste line, with `cd`
    first;
  - MetaTrader 5 is screenshot-only;
  - how to handle Windows Defender;
  - `send_later` check-ins.
- Its project rules belong to FTMO-TRADING-BIT and do not govern this bot:
  SPEC.md gates, `config/strategy.yaml`, the ledger, the 2.5%/6% engine
  limits, and uv/ruff/mypy.
- This bot's own rules are in section 4. They are just as strict about
  money and credentials.
- On the PC the repo lives at `C:\Users\leven\Trading-bot-2.0`. Nico is in
  Laval, so New York time is his local time.

## 1. Goal, and why the free trial

- **Nico's goal:** pass FTMO's 2-Step challenge (Swing account, USD) with
  this bot, then trade the funded account. His orders:
  - 2026-10-04: "build the FTMO connection at 3% risk";
  - later: "The bot will only be trading on FTMO, make sure it is ready for
    the challenge and then to get funded".
- **Current step: FTMO's free 14-day trial on MetaTrader 5, with demo
  money.** It has the 2-Step rules at half target:
  - 5% profit target and 2 minimum trading days;
  - 5% daily loss and 10% maximum loss limits;
  - it ends if nothing is traded in its first 7 days.
- **Why:** everything that can be tested without FTMO's terminal has been
  tested. What is left only FTMO's own MT5 can show:
  - symbol names, contract sizes and minimum lots;
  - the order filling mode and the server clock;
  - real fills and stops resting in MT5;
  - the setup scripts on real Windows PowerShell 5.1.

  The trial is that test. It does not test profitability: FAST-4 signals
  about twice a month, so a quiet trial is normal.

## 2. What has been done

- **2026-10-04:** bot built. FAST-4 is defined in
  `research/ftmo_fast_pass.md`.
- **10-05 to 10-22, paper test:**
  - The bot's **shadow run** is `scripts/ftmo_shadow.py`. It runs the real
    bot code against a simulated broker, on Astral 30-minute bars. QQQ, SPY,
    DIA and IWM stand in for US100, US500, US30 and US2000. Its state is in
    `research/ftmo_shadow/`.
  - No tick errors and no guard trips.
  - One signal, on 10-14, filled on 10-15. Both exits ran on 10-21 and
    10-22. Net result: +0.22%.
- **Late October, hardened for the challenge:**
  - server clock fitting (New York + 7 h);
  - one state file per account;
  - FTMO trading-day counting (Prague dates of opened positions);
  - target lock, keep-alive and guard;
  - two code-review rounds.
- **11-02:**
  - FTMO's rules re-read on ftmo.com (table in `docs/FTMO_BOT.md`), and the
    pass odds re-estimated.
  - A webinar's scale-out exits were tested on FAST-4 under FTMO's rules.
    No variant beats the current exits (`research/ftmo_scale_out.md`), so
    the exits are unchanged.
- **11-02 to 11-03, trial-ready on Windows:**
  - `deploy/ftmo/setup.ps1` and `run.ps1`, plus the trial config;
  - the account pin (`login:`), config type checks, credential hygiene;
  - five review rounds, 625 tests passing, CI green.
- **11-02 to 11-05, shadow trades:**
  - On 11-02 it bought US30 29.75 at 522.86 and US100 7.05 at 694.69. The
    combined-risk cap cut the second entry, as designed.
  - US30 exits at the 11-05 open.
  - Equity at the 11-04 close: 15,312.70 (+2.08%).
- **Astral paper deployment 1999** was only an outside cross-check. It is
  broken on Astral's side (paused, its stop feed is down), and a bug report
  was filed on 11-05. **The bot does not use Astral.** Ignore it.
- **Verdict on 11-05:** ready for the free trial.
- **11-08, Nico's order: the bot runs the 5-step exits.**
  - `exit_mode: scale_out`, the default; `ftmo_bot/scale_out.py`.
  - 1/2 is closed at +1R and the stop moves to the entry; 1/4 at +1.5R
    and the stop moves to +1R; the last 1/4 trails 1R under the highest
    close. There is no SMA5 or time exit.
  - **Measured, not promised:** 61–62% winners (2012–2026), not 30 of
    31. Faster passes within 18 months (19–41% of attempts against 7–17%),
    but 12–13% of 2019–26 attempts breached, against 1%.
  - Live shadow over 10-05 to 11-06 (`research/ftmo_shadow_5step/`): −6.8%
    equity, against −0.4% for the old exits on the same bars.
  - `exit_mode: fast4` brings the old exits back. That is Nico's call;
    never switch it on your own.
- **11-09, "Do what's necessary for the success of the bot":** two
  safety rules were pre-registered and tested
  (`research/ftmo_scale_out_v2.md`).
  - A 10-session time stop made things worse and was dropped.
  - A 1.5% max-loss buffer (`cap_max_loss_buffer: 0.015`) cut breaches.
    - 2011–18: from 37% to 15–16%. 2019–26: from 12–13% to 2%.
    - Passes within 18 months fell 0–3 points in three of four cells.
    - The median funded return fell to +0.5% (2011–18) and +2.5%
      (2019–26).
    - It did not pass its pre-registered rule.
    - Nico then ordered it **on**: "buffer on". It is the default and is
      in both configs. The funded account is to be decided again later.
    - The preflight prints `risk cap: all open stops together stay 0.2%
      above the daily line and 1.5% above the max-loss line`.
- **11-09, later: an audit of the bot's own code, and a correction.**
  - **Audit.** `scripts/ftmo_replay.py` ran the real bot over 2012–2026.
    Every part close, stop move, trail and stop-out matched an independent
    oracle: 0 mismatches (`reports/ftmo_bot_replay.md`). The 5 steps are
    implemented correctly. 60% of the bot's own trades reached +1R first.
  - **Frozen accounts.** Most "still running" attempts in the studies are
    frozen: flat, with no risk room left over the max-loss line, so the
    bot can open nothing more (`research/ftmo_frozen_accounts.py`).
  - **What that means for the buffer.** It turns breaches into frozen
    accounts and does not add passes. Nico was told and advised to turn
    it off again. **It stays on until he says otherwise.**
  - **In the bot.** It now logs `FROZEN` at warning level, and the
    preflight prints `room for the next entry: ...`.
  - **`run.ps1 -SelfTest`** was added: one tiny round trip through every
    order the 5 steps send (step 9).
  - **Two fixes tested and rejected** (`research/ftmo_slots_sizing.md`):
    freeing a slot once a position's stop is at its entry (216 of 990
    signals taken instead of 153, but less per trade and more breaches),
    and risking only a third of the room over the max-loss line (no
    freezes, far fewer passes). Neither passed its rule. The bot's rules
    did not change.
  - **The 1-in-31 claim.** It would need a first target a tenth of the
    stop's distance (`research/ftmo_win_rate_dial.md`). The 5 steps set
    the first target as far as the stop.
- **11-10, Nico's order: "free slots on".**
  - `free_slots: true`, the default; in both configs. A config without
    the key gets it too, so `git pull` and a restart of `run.ps1 -Live`
    switch it on.
  - **The rule.** A position takes one of the two slots only while its
    stop is under its entry. Once step 3 has moved the stop to the
    entry, the next signal can be taken. One position per index stays.
    So up to **four** positions can be open, at most two of them with a
    stop under their entry. That is not a fault.
  - **Measured, not promised** (`research/ftmo_slots_sizing.md`, S2 with
    the buffer): 216 of 990 signals taken instead of 153, about 14
    trades a year instead of 10. Each is worth less (+0.08R against
    +0.13R to +0.15R), and more attempts breach (19–21% and 7–8%
    against 15–16% and 2%). It did not pass its pre-registered rule. It
    is on by Nico's order.
  - The preflight, `plan` and the log print `slots: 2 positions at
    risk; a position whose stop is at or over its entry takes no slot`.
    With positions open, the preflight and `plan` add what they take,
    for example `taken now: 1 of 2; no slot taken by US500`.
  - `free_slots: false` in `state\ftmo_config.yaml` turns it off. That
    is Nico's call; never switch it on your own.
  - The audit was run again with the new rule
    (`reports/ftmo_bot_replay.md`, the section of 2026-11-10): 836
    entries, 324 of them beside two or more open positions, 3,428
    deals, 0 mismatches. The bot never held more than two positions
    with a stop under their entry.
- **11-11: a new trial account, and the bot's first live start.**
  - Nico could not log in to MT5 (the password was lost). He then
    logged in to a new free-trial account from his FTMO client area:
    USD 100,000, server `FTMO-Demo`; MT5's mailbox shows "You have
    registered a new account".
  - The installed config still had `login: null`. `-Live` refuses to
    start without a login, so unless the config was reinstalled since,
    the bot had not run live before.
  - **Two MetaTraders are installed on the laptop.** MetaQuotes' own
    (`C:\Program Files\MetaTrader 5`, a `MetaQuotes-Demo` account) and
    FTMO's (`C:\Program Files\FTMO Global Markets MT5 Terminal`). The
    title bar tells them apart: FTMO's reads `<login> - FTMO-Demo`.
  - The preflight passed on FTMO's terminal. `-Live` then failed with
    `MT5 initialize failed: (-6, 'Terminal: Authorization failed')`:
    without `mt5_path` the bot had attached to the MetaQuotes one.
  - Fixed by closing the MetaQuotes window, setting `login:` and
    `mt5_path:` in `state\ftmo_config.yaml`, and switching Algo
    Trading on. The bot started at 11:52 New York:
    `FTMO bot running (LIVE ORDERS)`, `algo trading ON`.
  - The line that pins the bot to the running FTMO terminal and starts
    it (paste as one line):
    `cd C:\Users\leven\Trading-bot-2.0; $p = (Get-Process terminal64 | Where-Object { $_.MainWindowTitle -like '*FTMO*' } | Select-Object -First 1).Path; if ($p) { (Get-Content state\ftmo_config.yaml) -replace '^mt5_path:.*', ('mt5_path: ' + $p.Replace('\','/')) | Set-Content state\ftmo_config.yaml; powershell -ExecutionPolicy Bypass -File deploy\ftmo\run.ps1 -Live }`
  - Not done yet: `run.ps1 -SelfTest` on this account (10:00–10:45 New
    York, with the `-Live` window stopped).
- **11-11: more markets tested and rejected** (`research/ftmo_breadth.md`).
  - The bot's rule on the four US indices plus gold, plus Germany, the
    UK, Japan and Australia, or plus all five. US-listed funds stood in
    for FTMO's CFDs.
  - Gold: fewer breaches, but fewer passes. The four countries: far
    more breaches, far fewer passes, and the account loses money. No
    list passed its rule.
  - The bot's markets did not change. Do not add a symbol to
    `state\ftmo_config.yaml`.

## 3. The bot on one screen

- **Markets:** `US100.cash`, `US500.cash`, `US30.cash` and `US2000.cash`.
  Long only.
- **Planning:** after the US close (16:05 New York) it rebuilds each
  index's 09:30–16:00 session from 30-minute bars and plans the next open.
  - Entry: close above the 200-day average and RSI(2) below 10.
  - Exits, the 5 steps (`exit_mode: scale_out`), with 1R = the first
    stop's distance (3 × ATR):
    - at +1R it closes 1/2 and moves the stop to the entry;
    - at +1.5R it closes 1/4 and moves the stop to +1R;
    - after each close, the last 1/4's stop rises to 1R under the highest
      close since entry.

    These run weekdays 09:31–17:00 New York, checked every minute; the
    stop rests in MT5 around the clock. A trade can last weeks.
  - Old exits (`exit_mode: fast4`): close above the 5-day average, or
    after 10 sessions. They still apply to any position opened under them.
- **At the next open** (09:31–10:30 New York) it sends planned FAST-4 exits
  first, then entries:
  - 3% of balance at risk;
  - a stop at entry minus 3 × ATR(14), resting in MT5;
  - at most 2 positions with a stop under their entry, one per index
    (free slots: up to 4 open); notional at most 3× balance each.

  Each plan runs at most once: it is saved as done before any order goes
  out.
- **Combined-risk cap:** all open stops together stay above FTMO's daily
  and maximum loss limits. A second entry gets the room that is left
  (about 1.8%).
- **Guard:** if equity comes within 0.2% of either limit, it closes
  everything.
- **Target lock:** at the target + 0.3%, it closes everything. It then
  makes minimum-lot round trips until the minimum trading days are met, and
  halts with "profit target reached".
- **Keep-alive:** a minimum-lot US500 round trip in its first session, and
  again after N days with no trade (5 on the trial, 25 on the challenge).
  These run only 10:00–10:45 New York.
- **Realistic odds** ("Read this first" in `docs/FTMO_BOT.md`):
  - FAST-4 is NO-GO for a *fast* pass.
  - **With the 5 steps, the 1.5% buffer and free slots (the default
    since 11-10):**
    - attempts started 2011–18: about 35% passed both phases (34% within
      18 months); 19–21% breached; 44–45% froze;
    - attempts started 2019–26: 42–52% passed (30–39% within 18 months);
      7–8% breached; 32–38% froze; 9–11% were still trading when the
      data ended.
    - Counting a frozen attempt as lost: 1.8 to 2.8 attempts per pass.
    - 59% of trades reach +1R before their stop (2012–2026). Never 30
      of 31.
    - Funded, 77% and 92% of accounts survived a year; the median
      survivor made −6.7% to −6.4% (2011–18 starts) and +1.7% (2019–26).
  - **With free slots off (the default from 11-09 to 11-10):**
    - attempts started 2011–18: 38–43% passed both phases (31–38% within
      18 months); 15–16% breached; 42–47% froze;
    - attempts started 2019–26: 37–40% passed (20–24% within 18 months);
      2% breached; 42% froze; 16–19% were still trading when the data
      ended.
    - Counting a frozen attempt as lost: 2.1 to 2.7 attempts per pass.
    - 61–62% of trades win (2012–2026). Never 30 of 31.
    - Funded, the median survivor made +0.5% to +2.5% a year.
    - Without the buffer: 46–47% and 38–42% passed, 37% and 12–13%
      breached, 17% and 30% froze; 2.0 to 2.2 attempts per pass.
  - **With the old FAST-4 exits (`exit_mode: fast4`):**
    - attempts started 2019–26 passed both phases 68–70% of the time within
      the data, with 1% breached. But that takes about 2 to 2.4 years, and
      only 14–17% pass within 18 months.
    - In the harder 2011–18 market, 41–43% of attempts breached and
      29–31% froze (10% froze in 2019–26).
  - The evaluation has no time limit, so slow is fine. A breached or
    frozen attempt costs a new fee.
  - The 5-step shadow has not yet run a part close or a stop move: both of
    its trades stopped out before +1R. Those paths are tested in code only,
    so watch the first one on the trial closely (section 6).

## 4. Hard rules

- **Credentials:** never type, store, paste or commit a password. Nico logs
  MT5 and GitHub in himself. The `login:` setting is the account number,
  not a password.
- **Nico's decisions only:**
  - signing up, paying, buying the challenge, moving money;
  - clearing a halt, and payouts;
  - pressing buttons in MT5.
- **Orders need two opt-ins and one account:**
  - `dry_run: false` in `state\ftmo_config.yaml`;
  - starting with `run.ps1 -Live` (or `-Flat`);
  - orders go only to the account named in `login:`.

  Never weaken any of these.
- **Trial vs. challenge:** the trial config already says `dry_run: false`
  (demo money). The paid challenge's config starts at `dry_run: true`.
  Going live there is Nico's call, made in that session, after the trial
  meets the criteria in section 6.
- **Don't change strategy parameters:** 3% risk, 3 × ATR stop,
  SMA200 / RSI(2), the 5 steps (`exit_mode: scale_out`), 2 slots with
  free slots on (`max_positions: 2`, `free_slots: true`), cap on with
  the 1.5% max-loss buffer (`cap_max_loss_buffer: 0.015`). They
  are the researched rule plus Nico's orders. Never change one to make
  something pass.
- **Never commit `state\` or `.env`.** Both are git-ignored and hold the
  account number and the bot's state.
- **One bot process at a time.** Stop `run` with Ctrl+C before logging the
  terminal into another account.
- **Not part of this task:**
  - Nico's IBKR TFSA (stocks and ETFs only; he trades SMH there by hand);
  - the AIR3 / SMH watch;
  - Astral.
- **Don't merge PR #4.**

## 5. The steps (runbook steps 1–10, `docs/FTMO_BOT.md` "Setup")

Give Nico one line at a time. Wait for the result (screenshot the PowerShell
window) before giving the next.

1. **Python:** 3.12, 64-bit, from python.org, with "Add python.exe to PATH"
   ticked.
   - 3.11 to 3.14 also work; 3.15 and the Microsoft Store Python do not.
   - setup.ps1 may not find a Python installed by uv. If it says it found
     none, install 3.12 from python.org.
2. **Get the bot.** GitHub may ask Nico to sign in.
   - If the folder is missing:
     `cd C:\Users\leven; git clone -b claude/mini-prop-os-trading-zmm4ym https://github.com/leventisnico-cpu/Trading-bot-2.0.git`
   - If it exists:
     `cd C:\Users\leven\Trading-bot-2.0; git pull`
   - The 5-step exits arrived with the 11-08 pull. A
     `state\ftmo_config.yaml` installed before then has no `exit_mode:`
     line and gets the 5 steps by default. The preflight prints
     `exits for new positions: 5-step scale-out ...`.
   - Free slots arrived with the 11-10 pull. A config installed before
     then has no `free_slots:` line and gets them by default. The
     preflight prints `slots: 2 positions at risk; a position whose stop
     is at or over its entry takes no slot`. A running `-Live` window
     keeps the old rule until it is stopped (Ctrl+C) and started again.
3. **Setup:**
   `cd C:\Users\leven\Trading-bot-2.0; powershell -ExecutionPolicy Bypass -File deploy\ftmo\setup.ps1`
   It must end with `Setup done`. It installs the trial config as
   `state\ftmo_config.yaml` and keeps it on later runs.
4. **Keep the PC awake on weekdays:**
   - Power: never sleep when plugged in.
   - Windows Update active hours: cover 09:30–16:00.
5. **Nico signs up** for the trial on ftmo.com: MetaTrader 5, USD, and the
   Swing account type if it is offered. FTMO emails the login and server.
6. **Nico sets up MT5:** installs FTMO's MetaTrader 5 and logs in (ticking
   "Save password"). Then:
   - Tools → Options → Expert Advisors → tick "Allow algorithmic trading";
   - press the Algo Trading button so it is green;
   - Market Watch (Ctrl+M) → Symbols: show the four `.cash` symbols.

   Confirm with a screenshot.
7. **Preflight** (reads only, sends nothing):
   `cd C:\Users\leven\Trading-bot-2.0; powershell -ExecutionPolicy Bypass -File deploy\ftmo\run.ps1 -Preflight`
   Check it line by line against section 6.
8. **Set the login** through the mount. In `state/ftmo_config.yaml`,
   replace the line `login: null` with `login: <trial number>`. The
   preflight's `WARN: login not set` line prints the number. Verify with
   `grep -n '^login:' state/ftmo_config.yaml`.
9. **Self-test, then start the bot.**
   - On a weekday between 10:00 and 10:45 New York time, once per trial
     account, with no `-Live` window running:
     `cd C:\Users\leven\Trading-bot-2.0; powershell -ExecutionPolicy Bypass -File deploy\ftmo\run.ps1 -SelfTest`
   - It buys 0.02 lots of `US500.cash` with a stop, closes half, moves the
     stop, and closes the rest. Expect four `PASS` lines and
     `self-test passed: this account takes every order the 5 steps send`.
   - On a `FAIL` line, stop and report it with the log. Outside the
     window it prints `FAIL not sent` and sends nothing. If an order
     fails midway, the bot closes what it opened; what it cannot close
     it queues, and `-Live` closes it. Check MT5 shows no position
     before going on.
   - Then start the bot:
   `cd C:\Users\leven\Trading-bot-2.0; powershell -ExecutionPolicy Bypass -File deploy\ftmo\run.ps1 -Live`
   - It prints the `rules:` line, then keeps running. Leave the window
     open.
   - Ctrl+C stops it; starting it again resumes.
   - Start it on a weekday before 10:45 so the first round trip happens
     that day.
10. **Any time:** `run.ps1 -Plan` prints what the bot will do at the next
    open. It reads only.

## 6. What to check

**Preflight, line by line:**

- **`account <login> on <server>, USD ...`:** must say `algo trading ON`.
- **`server clock:`:** should read UTC+2 (UTC+3 in summer) with
  `rule NY+7 [pinned]`.
  - `unverified`: run it again while the index CFDs are trading.
  - It mentions the PC clock: sync the Windows clock.
  - It fits no known rule: stop and tell Nico.
- **`rules:`:** `initial balance <account size> (from the account)`, the
  max-loss line at 90% of it, the profit target at 105% of it, and
  `trading days 0 of 2`.
- **`WARN: login not set`:** that is step 8.
- **The four symbol lines:** each must be `PASS <name> (<symbol>.cash)`
  with 205 or more sessions.
  - A `FAIL` on sessions: open that symbol's M30 chart and press Home to
    load older bars, or raise Tools → Options → Charts → "Max bars in
    chart" and restart MT5. Then run the preflight again.
  - Compare one printed last close with the chart.
- **`FAIL cannot reach the MT5 terminal`:** MT5 is not open or not logged
  in. With several terminals installed, set `mt5_path:` in the config to
  FTMO's `terminal64.exe`. `Authorization failed` after a preflight that
  passed means the bot attached to the other MetaTrader (the 11-11
  entry in section 2 has the fix).

**Every day.** Read `state/ftmo_bot.log` through the mount. It is
git-ignored but on disk.

- **At start:** `FTMO bot running (...)`.
- **First session, 10:00–10:45:**
  - `keepalive buy US500.cash: Fill(ok=True ...)`;
  - then `close US500.cash ... (keepalive): ...`;
  - then FTMO's dashboard should show 1 trading day. Nico logs in;
    screenshot it.
- **After 16:05:** `plan for the next open: exits [...], entries [...]`.
- **An entry at the next open:**
  `buy US100.cash <lots> lots stop <price>: Fill(ok=True ...)`. A second
  entry may log `entry X cut from A to B lots: open stops ...`. That is the
  cap working as intended.
- **The 5 steps on an open trade:**
  - `US100: bid ... reached +1.0R (entry ..., R ...): step 3`;
  - then `TP1: close <half> of <lots> lots of US100.cash: Fill(ok=True ...)`;
  - then `stop of US100.cash (ticket N) <old> -> <entry>: Fill(ok=True ...)`.
  - Step 4 logs `+1.5R`, `TP2` and a stop at entry + 1R.
  - Step 5 logs a stop move after 16:05 when the trade made a new high
    close.
  - Check each in MT5: the volume falls by half, then by a quarter, and
    the S/L column moves up.
- **Report these to Nico at once:**
  - any `ERROR` line, `order refused`, `GUARD:` or `halted:`;
  - a `TP1`/`TP2` close or a stop move with `Fill(ok=False`, or
    `closing the rest`;
  - `FROZEN` in the log or in the preflight: the account has no risk room
    left and the bot can open nothing more;
  - `missed the open window` or `cannot read today's session`;
  - the bot window closed, MT5 disconnected, or Algo Trading off.
- **Check-ins:** on trading days, schedule `send_later` around 10:50 (after
  the round-trip window) and 16:15 (after the plan). Send one line each, and
  stay silent when nothing changed.

**Before Nico buys the challenge,** the trial must show (runbook step 10):

- the keep-alive round trip filled and FTMO counted the trading day;
- any FAST-4 entry filled with a stop about 3 ATR away and a size risking
  about 3% (cut entries count, as intended);
- if a trade reached +1R: half of it closed and its stop moved to the
  entry, both visible in MT5;
- no `ERROR` lines.

If FTMO asks for payment for the trial, use any broker's free MT5 demo
instead. Put that broker's index symbol names under `symbols:` and set
`server_clock: null`. The orders get tested; the FTMO rule lines don't apply.

## 7. Troubleshooting

- **`REFUSED: orders go only to the account named in the config`:** do step
  8.
- **`FAIL the terminal is on account X ... is for account Y`:** the wrong
  account is logged in, or the wrong number is in `login:`.
- **`another ftmo_bot process holds this state file`:** a bot window is
  still open. Stop it first.
- **`FAIL config ...: not valid YAML at line N`:** fix that line in
  `state\ftmo_config.yaml`. The message never prints the line's content, by
  design.
- **`the MetaTrader5 package is missing`:** run setup.ps1 again, and always
  start the bot with run.ps1.
- **Setup refuses the Python version:** install 3.12 64-bit from
  python.org.
- **A `.ps1` file vanished** (`git status` shows ` D deploy/ftmo/...`):
  that's Windows Defender.
  - Check Protection history. If it shows a generic or heuristic detection
    of our own file, run this in an admin PowerShell:
    `Add-MpPreference -ExclusionPath "$env:USERPROFILE\Trading-bot-2.0"`,
    then `git checkout -- deploy/ftmo`.
  - If it names a malware family, stop and tell Nico.
- **The PC slept or restarted:** start `run.ps1 -Live` again. It resumes
  from its state file. A missed open means a missed trade, never a doubled
  one.

## 8. Code, git and hand-offs

- **Daily log commits:** the cloud Claude Code session that owns this repo
  pushes them to the same branch (`research/air3_daily_log.md`,
  `research/ftmo_shadow/`). They never touch `ftmo_bot/` or `deploy/`. Run
  `git pull` before any change.
- **If the bot or a script needs a fix:**
  - reproduce the problem and change the code;
  - `python -m pytest tests -q` must be green;
  - `.ps1` files stay pure ASCII and must work in Windows PowerShell 5.1;
  - commit on the branch, never `state\` or `.env`;
  - push (the repo must be in your session's sources).

  Or give the exact error output to Nico for the cloud session.
- **State between sessions:** keep a project doc,
  `claude/fast4-trial-state.md`. Record:
  - the trial's start date, and the step reached;
  - whether the bot is running, and the last log check;
  - what the dashboard shows, and open questions.

  Leave the account number out of it.

## 9. Reference

- **Repo:** github.com/leventisnico-cpu/Trading-bot-2.0, branch
  `claude/mini-prop-os-trading-zmm4ym` (draft PR #4; don't merge).
- **Runbook:** `docs/FTMO_BOT.md`. Setup steps 1–10 are the trial; steps
  11–17 are the paid challenge, the funded account, and halts.
- **Code:**
  - `ftmo_bot/`: `runner.py` (the loop), `fast4.py` (signals),
    `rules.py` (FTMO's limits), `broker_mt5.py` (MT5 adapter),
    `config.py`;
  - `deploy/ftmo/`: `setup.ps1`, `run.ps1`, `config.trial.yaml`, and
    `config.example.yaml` (the challenge config);
  - tests: `tests/test_ftmo_*.py`.
- **Research:**
  - `research/ftmo_fast_pass.md` (the rule; NO-GO for a fast pass);
  - `research/ftmo_bot_policy.md`, `research/ftmo_scale_out.md`;
  - `reports/ftmo_fast_pass_rerun_2026-10-29.md`.
