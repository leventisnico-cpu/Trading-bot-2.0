# Live readiness — AIR3 on SMH in the IBKR TFSA

Status on 2026-10-04: **not live.** The rule runs on two paper rails and
one decision is still the operator's. Funds reach the TFSA on Monday
2026-10-05; nothing in this repo or on Astral trades real money until the
operator signs off per the orders below.

## The three rails

| rail | what runs | state | who can switch it on |
|---|---|---|---|
| Astral paper | saved strategy 6422 "AIR3 SMH ride (5% band)", deployment 1924, $870, fractional shares | **stopped 2026-10-04 ~23:10 UTC** (flat, no orders) on the operator's choice: Astral allows one strategy per paper account and the operator gave it to the FTMO bot's FAST-4 test (deployment 1949, `docs/FTMO_BOT.md`). AIR3's SMH levels now come from the daily check (rules computed from Astral daily bars) | — |
| IBKR paper via this repo | `mini_prop_os` with `deploy/config.tfsa-paper-air3.yaml` (SMH, daily bars, one share, port 4002) | **ready**; needs IB Gateway on the operator's machine | operator (see Monday checklist) |
| IBKR live | the bot pointed at the live account | **blocked** twice: `main.py` exits 4 because `air3_trend` is `DEPLOYABLE: no` (it fails the gate on SMH), and no live port may appear in a config until the live-readiness order is signed | operator, by order (route 1 or 2 below) |

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
8. **Pick route 1 or route 2 below.** Nothing goes live before that.

## The gate question (operator decision)

**Brokerage answer (2026-10-04):** trade through Interactive Brokers,
using this repo's bot. The TFSA is tax-free, IB Gateway connects to the
bot directly, and Astral cannot reach IBKR at all. Its broker list has no
Interactive Brokers. Moomoo only makes sense if money is moved there.

**The law was amended (order C, 2026-10-04).** `scripts/expectancy.py`
now passes a window if the strategy either (1) ends with more equity
than buy-and-hold, or (2) earns more per dollar of maximum drawdown
than buy-and-hold while keeping at least half of its gain. Both sides
start 95% invested, and the strategy re-sizes each entry to 95% of its
current equity, the way Astral sizes it. Deployable still means 2 of 3
folds plus the full sample.

AIR3 under the amended law (`reports/minipropos_expectancy_smh.md`,
`reports/minipropos_expectancy_spy.md`), $10,000 start:

| symbol | window | AIR3 gain/DD | B&H gain/DD | AIR3 keeps of B&H gain | AIR3 maxDD | B&H maxDD | passes |
|---|---|---|---|---|---|---|---|
| SMH | fold 1 (2007–2013) | 0.53 | 0.21 | more than B&H | 26.8% | 61.4% | YES (1) |
| SMH | fold 2 (2013–2020) | 1.14 | 1.39 | 46% | 27.7% | 33.2% | no |
| SMH | fold 3 (2020–2026) | 3.06 | 3.48 | 37% | 24.2% | 44.4% | no |
| SMH | full sample | 3.71 | 3.72 | 53% | 30.1% | 61.4% | no |
| SPY | fold 1 (1999–2008) | 3.08 | 0.44 | more than B&H | 12.4% | 45.5% | YES (1) |
| SPY | fold 2 (2008–2017) | 3.81 | 2.19 | 96% | 14.4% | 48.8% | YES (2) |
| SPY | fold 3 (2017–2026) | 4.02 | 4.94 | 40% | 19.0% | 32.5% | no |
| SPY | full sample | 6.95 | 6.13 | 76% | 18.9% | 53.1% | YES (2) |

**AIR3 passes the law on SPY and fails it on SMH.** SMH's run since
2013 has been so strong that being in cash for any of it costs more
than half the gain. The module stays marked `DEPLOYABLE: no`, because
the bot is configured for SMH. The law was not loosened a third time to
force a pass. A gate that moves until the answer is yes protects
nothing.

**Two ways for AIR3 to trade live through the bot. Both are the
operator's decision:**

1. **AIR3 on SPY, gate-approved.** Order it, and the assistant adds a
   symbol-scoped approval (AIR3 deployable on SPY only) and a SPY AIR3
   config. The Astral paper deployment would be re-pointed to SPY for
   the rehearsal (preview first, then your approval). SPY closed at
   about $770 on 2026-08-28, so $870 buys one share (about 88% of
   equity).
2. **AIR3 on SMH, against the gate's verdict.** The bot's live-start
   refusal cannot be loosened by the assistant: the repo's review rule
   (`.claude/agents/code-reviewer.md`, hard rule 1) treats any weakening
   of `refuse_live_reason` or `main.py`'s exit code 4 as a blocker. A
   waiver path was built and then withdrawn on 2026-10-04 for that
   reason. To take this route the operator amends that rule in their own
   commit, saying SMH may run live with a signed waiver. Only after that
   can a waiver be built, and it would need to refuse future or
   placeholder signatures, cite a real gate report, and put the waiver
   folder under owner-only review. No such code exists today. The
   other route is to place the signals by hand, as option B above
   describes.

Either way the last rail is unchanged. The live port (4001) goes into a
copy of the config under `state/`, which is git-ignored, by the
operator, after the paper rehearsal. The checked-in configs stay paper.

**Sizing on the live bot:** with $870 the bot buys one whole share
(about 72% of equity) because the config's lot is fixed at 1. The gate
measures 95% sizing. Fractional shares in IBKR, if enabled on the TFSA,
would close that gap. Until then the live position is a little smaller
than the backtests.

**Recommendation:** keep both paper rails running through the first
signal and fill. Then pick route 1 or route 2. Route 1 keeps every rule
of the repo intact. Route 2 keeps the asset you chose and studied, and
needs your own change to the review rule first.

## Operator decision (2026-10-04): AIR3 on SMH

The operator chose **SMH** (route 2). Until the operator commits the
review-rule amendment below, the bot cannot start AIR3 on a live port,
so the TFSA runs **route B: signals executed by hand**.

* **Signal source:** the daily check after the 16:00 ET close, which
  computes AIR3 on SMH from Astral daily bars and reports any order for
  the next open. (Astral paper deployment 1924 was the source until
  2026-10-04, when the operator moved the paper account to the FTMO
  bot test.)
* **Where SMH stood on 2026-10-02:** close 630.60; buy level 1.05 ×
  SMA200 = 524.47; sell level 0.95 × SMA200 = 474.52; SMA50 569.85 above
  SMA200 499.50. AIR3 is in its buy regime, so unless SMH closes below
  524.47 on Monday 2026-10-05 the first order is a BUY at Tuesday's
  open.
* **Operator's order in IBKR (TFSA):** buy SMH at Tuesday's open (a
  market-on-open or a limit near the open), as many whole shares as the
  USD cash allows (about one share at ~$630 with ~$870 USD). Hold until
  the watch reports a SELL (a close below 0.95 × SMA200), then sell at
  the next open. No stop, no adding, no shorting. A handful of orders a
  year.
* **To let the bot trade it by itself instead:** the operator commits
  this change to hard rule 1 in `.claude/agents/code-reviewer.md` (the
  assistant does not make it):

  > Exception: a live start for `air3_trend` on SMH is allowed when
  > `deploy/waivers/operator_waivers.yaml` holds a waiver signed by the
  > operator; the waiver check must reject future dates, placeholders
  > and the assistant as signer, and `deploy/waivers/` must be
  > owner-reviewed (CODEOWNERS).

  After that commit the assistant builds the hardened waiver, the
  reviewer re-checks it, and the operator signs the waiver and switches
  the port to 4001 in a private `state/` copy of the config.

## Hard rules that do not change with the decision

- The TFSA trades stocks and ETFs only. No futures, no shorts, no margin.
- Paper ports are 4002 and 7497. A live port (4001, 4003, 7496) in any
  config is a bug until the live-readiness order is signed.
- Credentials are typed by the operator, never stored in the repo, never
  pasted to the assistant.
- **Astral paper and signals-only:** standing authority from the
  operator (2026-10-04, "Stop asking for permission just get it done").
  The assistant deploys, undeploys, cancels and places paper orders on
  its own judgement and reports what it did.
- **Real money** (Astral `user_approved` or `full_broker`, any live
  broker order, IBKR live ports): still needs the operator's explicit
  approval of that exact preview.
