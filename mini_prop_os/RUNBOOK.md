# Mini-Prop OS operator runbook

The bot runs on **your** machine (or a VPS you control), next to IB
Gateway or TWS logged into **your** IBKR account. Nothing here runs
server-side at IBKR, and nobody else can start it for you — treat the
machine that runs it like a trading terminal.

## First night: paper trading against the live market

1. **Install IB Gateway** (lighter than TWS; either works) and log in
   with your **paper** credentials. In Configuration → API → Settings:
   - check *Enable ActiveX and Socket Clients*
   - **uncheck** *Read-Only API*
   - socket port **4002** (Gateway paper) or **7497** (TWS paper)
   - add `127.0.0.1` to trusted IPs
2. **Get the code and dependencies:**
   ```bash
   git clone https://github.com/leventisnico-cpu/Trading-bot-2.0
   cd Trading-bot-2.0
   pip install ib_insync PyYAML
   ```
   If you use Gateway, edit `mini_prop_os/config.yaml`: `port: 4002`.
3. **Preflight (read-only, places no orders):**
   ```bash
   python -m mini_prop_os --preflight
   ```
   Every line must be PASS: connection, contract qualification (front
   month + multiplier verified against CME), market data entitlement,
   account equity, no persisted halt. A market-data FAIL usually means
   the account lacks a CME futures data subscription (add "CME Real-Time
   NP,L1" in Account Management; paper shares the live account's
   subscriptions).
4. **Run:**
   ```bash
   python -m mini_prop_os
   ```
   Expected startup: connect → resolve front-month MES → warm up on ~2
   days of 1-minute bars → "Mini-Prop OS running". It then trades the
   adaptive strategy autonomously within the risk caps.
5. **Watch** (first sessions, do watch):
   - console / `state/mini_prop_os.log` — regimes, intents, risk rejects
   - `state/executions.jsonl` — every order state change and fill
   - Gateway's own trade blotter — the independent source of truth
6. **Stop:** Ctrl-C (or `kill -TERM <pid>`). Working orders are
   cancelled; set `execution.flatten_on_shutdown: true` if you want the
   position closed on every stop.

## If the kill switch fires

A daily-loss breach cancels all orders, flattens the book, and writes
`state/kill_switch.json`. The process — and any restart, including a
supervisor or reboot — **refuses to trade** while that file exists.

1. Read the marker and `state/executions.jsonl`; check the account in
   Gateway/TWS matches (flat, no working orders).
2. Understand *why* the limit was hit before you clear anything.
3. Clear, attributed to you:
   ```bash
   python -m mini_prop_os --reset-kill-switch nico
   ```

## Going live (real money) — deliberate, not default

- Log Gateway/TWS into the **live** account; set `port: 4001` (Gateway)
  or `7496` (TWS). The bot logs a loud warning on live ports.
- Re-run `--preflight` against the live setup.
- Size honestly: 1 MES ≈ $30k+ index exposure on ~$2k margin;
  `risk.max_daily_loss: 1000` means a worst normal day costs about that.
  Set caps to numbers you are genuinely willing to lose.
- The repo's Phase 4 verdict still applies: the strategy has **not**
  demonstrated edge. Paper results and validation scorecards measure the
  machinery and exposure control, not profitability. Run paper for at
  least a few weeks of varied conditions first, and compare the paper
  fills in `executions.jsonl` against the simulator's assumptions.

## Known limitations (deliberate scope)

- **One instance, one contract.** Don't run two copies against one
  account (`client_id` clashes aside, the risk view would be split).
- **Learned thresholds are in-memory.** The adaptive strategy's
  per-regime entry thresholds reset on restart (bounded and safe, but
  re-learned each session).
- **Front month is resolved at connect.** Across a futures roll (MES
  rolls quarterly, ~1 week before expiry), restart the bot so it picks
  up the new front month; it will not auto-roll an open position.
- **Daily-loss baseline is marked at connect** and per session; the
  paper/live account's overnight moves before connect are not counted.
  If account equity cannot be read at connect, trading stays disabled
  (no baseline = no breaker = no trading) and setup retries every 30s.
- **Startup reconciliation.** An existing position in the account is
  imported into the ledger at cold start (caps and flattening then cover
  it), and working orders the bot doesn't recognize are cancelled. A
  ledger/broker mismatch appearing later — e.g. fills during a
  disconnect — halts trading with a persisted kill-switch marker for
  operator review; it will not trade against a book it can't explain.
- **No taxes, no currency effects, no overnight-margin modelling.**
