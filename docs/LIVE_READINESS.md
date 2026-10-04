# Live readiness — AIR3 on SMH in the IBKR TFSA

Status on 2026-10-04: **not live.** The rule runs on two paper rails and
one decision is still the operator's. Funds reach the TFSA on Monday
2026-10-05; nothing in this repo or on Astral trades real money until the
operator signs off per the orders below.

## The three rails

| rail | what runs | state | who can switch it on |
|---|---|---|---|
| Astral paper | saved strategy 6422 "AIR3 SMH ride (5% band)", deployment 1924, $870, fractional shares | **running** since 2026-10-04 04:08 UTC; first signal evaluated at the Monday close | — |
| IBKR paper via this repo | `mini_prop_os` with `deploy/config.tfsa-paper-air3.yaml` (SMH, daily bars, one share, port 4002) | **ready**; needs IB Gateway on the operator's machine | operator (see Monday checklist) |
| IBKR live | either rail pointed at the live account | **blocked** twice: `main.py` exits 4 because `air3_trend` is `DEPLOYABLE: no`, and no live port may appear in a config until the live-readiness order is signed | operator, by order |

## Monday checklist (operator actions, in order)

1. **Confirm the funding.** SMH trades in USD. Hold USD cash in the TFSA
   (convert once) rather than letting each order convert CAD, which pays
   the FX spread on every trade.
2. **Check trading permissions in IBKR Account Settings:** US stocks/ETFs
   enabled; *Fractional Share Trading* enabled if IBKR offers it on this
   account. Without fractional shares one SMH share (about $630) is 72% of
   $870, and the bot cannot buy at all once SMH trades above the account's
   cash.
3. **IB Gateway, paper login** (`kwvvvq586`): Configure → API → Settings →
   *Enable ActiveX and Socket Clients* on, *Read-Only API* off, socket port
   **4002**, trusted IP `127.0.0.1`. The operator types the password; the
   repo never sees it.
4. **Install and preflight the AIR3 config:**
   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy\windows\setup.ps1
   .\deploy\windows\run.ps1 -Preflight -Config deploy\config.tfsa-paper-air3.yaml
   ```
   Every line must read PASS. Save the output as
   `reports/preflight_air3_first.md`.
5. **Run it on paper:**
   ```powershell
   .\deploy\windows\run.ps1 -Config deploy\config.tfsa-paper-air3.yaml
   ```
   Expected: connect, qualify SMH, load about 500 daily bars, warm up on
   200, then sit idle until the 16:00 ET bar completes. If Monday closes in
   regime the first intent is a BUY of one share, which rests at IBKR until
   Tuesday's 09:30 ET open, the same timing the Astral deployment uses.
6. **Telegram:** put `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in the
   git-ignored `.env` (and as Claude Code environment secrets if the
   routines should send through the same bot). Never in a config file.
7. **Compare the two paper rails** after the first fill: Astral's fill
   price and quantity versus `state/executions.jsonl`. They should differ
   only by fractional-versus-whole-share sizing.
8. **Decide the gate question below.** Nothing goes live before that.

## The gate question (operator decision)

`scripts/expectancy.py` is the repo's law for live trading: a strategy is
deployable only if its final equity beats buy-and-hold of the same lot in
at least 2 of 3 walk-forward folds and on the full sample. AIR3 was run
through it on SMH (`reports/minipropos_expectancy_smh.md`):

| window | AIR3 final | B&H final | AIR3 maxDD | B&H maxDD | beats B&H |
|---|---|---|---|---|---|
| fold 1 (2007-04 to 2013-10) | 10,020 | 10,026 | 0.6% | 1.3% | no |
| fold 2 (2013-10 to 2020-04) | 10,216 | 10,354 | 2.1% | 2.4% | no |
| fold 3 (2020-04 to 2026-10) | 14,734 | 15,733 | 10.9% | 10.2% | no |
| full sample | 15,453 | 16,132 | 10.4% | 10.0% | no |

Result: 0 of 3 folds, full sample no, **NOT DEPLOYABLE**, and the module
is honestly marked `DEPLOYABLE: no`. This is not a bug. AIR3 was chosen
for its drawdown, and a rule that is in cash through every bear market
loses to holding on final equity by construction. Two caveats on the
table above:

- The gate holds a constant 10-share lot against $10,000 of cash, so
  percentages are diluted; the Astral backtests size 95% of equity and
  show the real shape (full sample +1,144% vs +2,212% buy-and-hold, max
  drawdown −27.6% vs −44.9%, drawdown lower in all three folds).
- In the gate's fold 3 the drawdown advantage disappears: both the rule
  and buy-and-hold have their worst loss in the June-to-July 2026 dip,
  which AIR3 held through because the price never reached 0.95 × SMA200.

The operator has three ways forward. Pick one by order; the repo will
not pick for you.

**A. Keep the gate as the law.** AIR3 never runs live through this bot.
Live exposure, if any, goes through Astral with the IBKR account
connected (option B below) or is manual.

**B. Execute the signals by hand.** Checked 2026-10-04: Astral's broker
portal lists Kraken, Webull, Moomoo, E*TRADE, Public, Coinbase,
Tastytrade and Alpaca Paper, not Interactive Brokers, so the Astral
deployment cannot be pointed at the TFSA. What Astral can do is keep
producing the signal. The daily watch routine reports each order the
paper deployment schedules (after the 16:00 ET close) and the operator
places the same order in IBKR before the next open. One share, a handful
of orders a year, and the gate is untouched because the gate governs the
bot, not the human. This is the only way the TFSA trades AIR3 live
without changing the repo's rules.

**C. Amend the gate (an order, not a code change I make alone).** Proposed
wording, to be measured before adoption: *DEPLOYABLE if, in at least 2 of
3 folds and on the full sample, final equity is at least 60% of
buy-and-hold's and max drawdown is at most 75% of buy-and-hold's.* On the
SMH numbers above AIR3 would pass folds 1 and 2 on drawdown and fail fold
3, so even this gate would not pass it today. The operator should know
that before choosing C.

**Recommendation:** stay on both paper rails until the first full
signal has been observed (entry on Monday's close if in regime, the
fill, and at least two weeks of daily evaluations), then decide A/B/C
with a real fill in hand. If the operator wants the TFSA in the trade
sooner, B is available from the first signal: one share, placed by hand
before the open, after the daily watch reports the order. Monday's
funding does not need to be at risk on Monday.

## Hard rules that do not change with the decision

- The TFSA trades stocks and ETFs only. No futures, no shorts, no margin.
- Paper ports are 4002 and 7497. A live port (4001, 4003, 7496) in any
  config is a bug until the live-readiness order is signed.
- Credentials are typed by the operator, never stored in the repo, never
  pasted to the assistant.
- Every Astral deploy, undeploy, cancel or manual order needs the
  operator's explicit approval of that exact preview.
