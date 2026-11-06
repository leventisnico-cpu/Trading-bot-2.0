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

## 3. The bot on one screen

- **Markets:** `US100.cash`, `US500.cash`, `US30.cash` and `US2000.cash`.
  Long only.
- **Planning:** after the US close (16:05 New York) it rebuilds each
  index's 09:30–16:00 session from 30-minute bars and plans the next open.
  - Entry: close above the 200-day average and RSI(2) below 10.
  - Exit: close above the 5-day average, or after 10 sessions.
- **At the next open** (09:31–10:30 New York) it sends exits first, then
  entries:
  - 3% of balance at risk;
  - a stop at entry minus 3 × ATR(14), resting in MT5;
  - at most 2 positions, notional at most 3× balance.

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
  - With the bot's controls, attempts started 2019–26 passed both phases
    68–70% of the time within the data, with 1% breached. But it takes
    about 2 to 2.4 years, and only 14–17% pass within 18 months.
  - In the harder 2011–18 market, 41–43% of attempts breached.
  - The evaluation has no time limit, so slow is fine. Only a breach costs
    a new fee.

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
  SMA200 / RSI(2) / SMA5, 10 sessions, 2 positions, cap on. They are the
  researched rule. Never change one to make something pass.
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
9. **Start the bot:**
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
  FTMO's `terminal64.exe`.

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
- **Report these to Nico at once:**
  - any `ERROR` line, `order refused`, `GUARD:` or `halted:`;
  - `missed the open window` or `cannot read today's session`;
  - the bot window closed, MT5 disconnected, or Algo Trading off.
- **Check-ins:** on trading days, schedule `send_later` around 10:50 (after
  the round-trip window) and 16:15 (after the plan). Send one line each, and
  stay silent when nothing changed.

**Before Nico buys the challenge,** the trial must show (runbook step 10):

- the keep-alive round trip filled and FTMO counted the trading day;
- any FAST-4 entry filled with a stop about 3 ATR away and a size risking
  about 3% (cut entries count, as intended);
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
