# FTMO bot — FAST-4 on MetaTrader 5

Built 2026-10-04 on the operator's order: "build the FTMO connection at
3% risk". It runs FAST-4 (`research/ftmo_fast_pass.md`) on an FTMO
2-Step account through the MetaTrader 5 terminal.

## Read this first

The research verdict for FAST-4 is **NO-GO** for a fast pass. On
2019–2026 data at 3% risk per trade:

| measure | result |
|---|---|
| win rate | 70% |
| both phases passed within 18 months | 18% of start dates |
| median time to pass, when it passes | about 13 months |
| funded account survives 12 months | 37% |
| main failure | two stops on the same day breach the 5% daily limit |

Each evaluation fee buys roughly a one-in-five chance. The bot does not
change those odds; it only executes the rule faithfully.

**Why two positions can fail the account in one day.** Two open
positions at 3% each put 6% at risk, more than FTMO's 5% daily limit. The
guard closes everything just before the daily line, but if both stops are
hit by one gap (overnight or at the open) the loss can pass the line
before the guard can act. That is the main failure in the research, and
it stays with `risk_per_trade: 0.03` and `max_positions: 2`. Setting
`max_positions: 1` removes it at the cost of fewer trades (not tested).

## What it does

* Trades the four FTMO US index CFDs (`US100.cash`, `US500.cash`,
  `US30.cash`, `US2000.cash`; check the names in Market Watch).
* After the US close (16:05 New York) it rebuilds each index's
  09:30–16:00 session bars from 30-minute bars and computes FAST-4:
  buy when close > 200-day average and RSI(2) < 10; exit when close >
  5-day average or after 10 sessions.
* At the next US open (09:31–10:30 New York) it sends exits first, then
  entries: 3% of balance at risk, stop at entry − 3 × ATR(14) resting in
  MT5, at most two positions, notional at most 5× balance. Each plan is
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
* **Target:** when the phase target is reached with at least 4 trading
  days, it closes everything and stops, so you can confirm the phase on
  FTMO's dashboard.
* **Keep-alive:** in an evaluation, if 25 days pass without a trade, it
  opens and closes the minimum lot on US500 (FTMO closes accounts
  inactive for 30 days).
* **Dry run by default.** Orders are only logged unless the config says
  `dry_run: false` **and** you start it with `--execute`.

It never sees your password. You log the terminal in; the bot attaches
to it.

## Setup (Windows PC or Windows VPS outside the US)

1. Buy the FTMO 2-Step challenge yourself (CAD 15,000 is the account the
   research modelled). Choose **MetaTrader 5** and the **Swing** account
   type (overnight and weekend holding).
2. Install FTMO's MT5 terminal and log in with the credentials FTMO
   emails you. You type them; they never go in this repo.
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

   Set `initial_balance` to the account size you bought (15000 for the
   CAD 15,000 account): FTMO's loss lines are percentages of it. Set
   `profit_target` to `0.10` for Phase 1. Set `mt5_path` if the
   terminal is not found automatically.
6. Preflight (read-only):

   ```powershell
   py -m ftmo_bot preflight --config state\ftmo_config.yaml
   ```

   Every symbol must print PASS with 205+ sessions. Compare the printed
   last close with the index on a chart: if the session date or close is
   off, the server-time offset (New York + 7 h, `broker_mt5.py`) does not
   match your server and must be fixed before anything else.

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
   "DRY-RUN buy" lines at the next open, lot sizes and stops.
8. Go live on the evaluation only after the dry-run week looks right:
   set `dry_run: false` in `state\ftmo_config.yaml`, then

   ```powershell
   py -m ftmo_bot run --config state\ftmo_config.yaml --execute
   ```

   Keep the PC (or VPS) and the terminal running on weekdays.
9. When the bot halts with "profit target reached", check FTMO's
   dashboard. For Phase 2 set `profit_target: 0.05` (and
   `initial_balance` to the new account's size), delete
   `state\ftmo_state.json`, and restart on the new account. On the funded
   account set `profit_target: null` (keep-alive is then off).

## Things that could not be verified from here

* The exact FTMO symbol names, contract sizes and filling mode (the
  adapter picks FOK, IOC or RETURN from the symbol's settings).
* FTMO's server clock (assumed New York + 7 hours all year).
* That FTMO counts a keep-alive open/close as trading activity.
* FTMO's current rules: re-read them on ftmo.com before buying.

The preflight and the dry-run week exist to catch the first two.
