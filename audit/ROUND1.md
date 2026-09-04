# Adversarial Audit — Round 1

Environment: `python3 -m pytest tests -q` → **66 passed** (the shipped suite is green;
every bug below survives the suite). Each finding has a runnable reproduction in
`audit/repro_NN_*.py`; every script **raises AssertionError while the bug exists**
(run: `cd /home/user/Trading-bot-2.0/audit && python3 repro_NN_*.py`).
No file outside `audit/` was modified.

---

## CONFIRMED

### 1. `max_orders_per_day` is a no-op in the real execution path — **HIGH**
`engine/execution.py::_submit_single` calls `risk.filter_orders([order], prices)` **one
order at a time**, so `truncate_to_cap(kept, cap)` always sees a list of length 1 and can
never truncate. The cap — a §7 "order-level backstop" — is enforced nowhere on the path
`compute_orders → execute_rebalance → broker` used by both `run_cycle` and `run_backtest`.
The regression test (`test_fm03_sells_first_and_buys_dropped_at_cap`) calls
`truncate_to_cap` directly and never exercises the real path.
Repro: `repro_01_order_cap_noop.py`

```
configured max_orders_per_day = 10
orders submitted to broker: 15 (cap is 10)
dropped for cap: []
AssertionError: BUG CONFIRMED: 15 orders reached the broker, cap 10 never enforced in execute_rebalance
```

### 2. `is_last_trading_day_of_month` is True almost every day — paper/live trades at month START — **HIGH**
`scripts/daily_run.py::is_last_trading_day_of_month` computes
`trading_days.max().date() <= today` over the *fetched* index — which only extends to
today. So the "last trading day of the month seen so far" is always ≤ today, and the
function returns True on **every** day of a month that has at least one bar. The paper
engine therefore rebalances on the FIRST trading day of each month (the
`last_completed_period` guard then suppresses the rest), while the backtest
(`month_end_schedule`) decides on the LAST trading day — a systematic ~1-month timing
skew between live and backtest signals (invariant 3 broken).
Repro: `repro_02_decision_day_every_day.py`

```
2026-08-03 (Monday): decision_day = True     <- FIRST trading day of August
2026-08-04 (Tuesday): decision_day = True
2026-08-12 (Wednesday): decision_day = True
2026-08-31 (Monday): decision_day = True
AssertionError: BUG CONFIRMED: the first trading day of the month is classified as the LAST ...
```

### 3. Backtest evaluates kill switches only on decision days; live evaluates them daily — **HIGH**
In `engine/backtest.py`, `risk.pre_trade` (drawdown hard-kill, equity floor, daily-loss
stand-down) runs only inside `if is_decision_day(i)`. In live, `run_cycle` runs it every
day. A >35% intra-month drawdown that recovers by month-end: live hard-kills, liquidates
at the bottom, and halts permanently; the backtest sails through un-halted. Identical
prices, identical config, opposite terminal outcomes — the backtest structurally cannot
show the (large, negative) effect of the kill mechanism it claims parity with.
Repro: `repro_03_backtest_skips_risk_checks.py`

```
max_drawdown_pct = 0.35
backtest: halted=False, halts=[], final equity=9,992.07
live:     halted=True, reason='drawdown 44.5% exceeds max 35.0%', cash=5,540.19, positions={}
AssertionError: BUG CONFIRMED: identical prices + config -> live hard-kills and liquidates at
the bottom, backtest sails through un-halted
```

### 4. A torn state file CAN read back as `halted=False` — **HIGH**
`engine/state.py` claims "a torn file can never read as halted=False". But when the main
file is truncated **before** the bytes of the halted flag (keys are sorted:
`cash`, `halt_reason`, `halted`, …), `_merge_halt_flags`'s substring scan finds no
`"halted": true`, and `load()` silently returns the one-save-old backup — which says
`halted=False`. A hard-killed engine resumes trading after a partial write/disk
truncation. (FM#5 variant: the shipped test tears the file *after* the flag bytes.)
Repro: `repro_04_torn_state_not_halted.py`

```
torn main file contents: {"body": "{\"cash\": 0.0, \" ...
load() after tear -> halted=False, reason=''
AssertionError: BUG CONFIRMED: torn main file + valid stale backup loads as halted=False ...
```

### 5. On fill days, a held symbol with a NaN close is marked at $0 — **MEDIUM (data-integrity)**
`run_backtest`'s top-of-loop mark correctly carries the last known price for a NaN close,
but the fill leg then overwrites `equity = account.equity`, computed by `PaperBroker`
against `fill_prices` that **exclude** NaN symbols (`positions.get(sym, 0.0)` marks them
$0). One missing close on an untouched position craters the equity curve by the entire
position value for that bar — corrupting max-drawdown, vol, Sharpe (via
`phase4_backtest.metrics`) and `state.last_equity`.
Repro: `repro_05_nan_mark_equity_crater.py`

```
2026-02-02    10000.0
2026-02-03     5500.0   <- ZAG.TO close NaN on the fill day; nothing traded in it
2026-02-04    10000.0
equity change on the NaN day: -4,500.00 (nothing was sold; prices flat)
AssertionError: BUG CONFIRMED ...
```

### 6. Cash goes negative through fees on sells — **MEDIUM**
`PaperBroker._execute_one` affordability-checks BUYS only; a SELL credits
`proceeds - costs` unconditionally. Full exits are (deliberately) exempt from both
`min_order_notional` and `max_cost_fraction`, so a full-exit sell whose $1.00 minimum
commission exceeds its proceeds passes the risk layer, fills, and leaves the account
with negative cash — implicit leverage in a system that claims "no leverage,
structurally" (invariant 4).
Repro: `repro_06_negative_cash_fees.py`

```
order results: [('FILLED', 1.0)]
cash after full exit: -0.5004
AssertionError: BUG CONFIRMED: cash is -0.5004 — the risk layer approved the order (full-exit
exemption) and the broker paid a $1 min fee out of $0.50 proceeds
```

### 7. `available` not debited for PARTIALLY_FILLED buys — buys sized off cash that does NOT exist — **MEDIUM**
`execute_rebalance` decrements `available` only for `is_success` (FILLED) results. A
PARTIALLY_FILLED buy consumed real cash at the broker, but the tracker still shows the
old number, so the next buy is submitted at full size against phantom cash — the exact
condition §5.2 claims is impossible ("cash that demonstrably exists"). The oversized
order is REJECTED wholesale by the broker; the resize-down logic (which exists!) never
runs, and an affordable smaller buy is lost.
Repro: `repro_07_partial_fill_stale_available.py`

```
A: PARTIALLY_FILLED, filled 5.4     (~$542 of real cash consumed)
B: REJECTED, filled 0.0             (submitted for 5 shares vs $458 actual cash)
broker cash now: 458.62
AssertionError: BUG CONFIRMED ... the resize-to-cash logic never ran
```

### 8. The daily report headlines "PARTIAL REBALANCE — PORTFOLIO NOT AT TARGET" on every ordinary day — **MEDIUM**
On non-decision days `run_cycle` calls `build_report` with `target_weights={}`;
`converged(positions, {}, …)` scores every held position as a deviation from a zero
target, so a fully converged portfolio is flagged NOT-AT-TARGET every single day between
rebalances. §11's alarm header cries wolf ~21 days a month, training the operator to
ignore the one header that must never be ignorable (§7's own alarm-fatigue argument).
Repro: `repro_08_report_cries_wolf.py`

```
---- report on an ordinary, fully-converged, no-trade day ----
PARTIAL REBALANCE — PORTFOLIO NOT AT TARGET
AssertionError: BUG CONFIRMED ...
```

### 9. `rebalance_retries` never resets on period rollover — permanent soft-brick — **MEDIUM**
`run_cycle` resets `rebalance_retries` only upon convergence. If one bad month exhausts
`max_rebalance_retries` without converging (e.g. a venue outage week), every FUTURE
month's rebalance is also refused ("retry cap reached for 2026-08" — a fresh period, on
a healthy broker). The engine sits in cash forever until a human edits the state file,
and the warning text falsely scopes the problem to the current period.
Repro: `repro_09_retries_never_reset.py`

```
traded: False
['note: LOUD WARNING: rebalance retry cap (5) reached for 2026-08 without convergence — ...']
positions after cycle: {}
AssertionError: BUG CONFIRMED: a NEW month's rebalance on a healthy broker was refused ...
```

### 10. Contributions are counted as return — the daily-loss check is blind on deposit days — **MEDIUM (FM#1 variant)**
`daily_run.py` credits the weekly $100 into the broker BEFORE `run_cycle`, and
`risk.pre_trade` computes `daily_return = equity / prior.last_equity - 1` with no flow
adjustment. On the small accounts this engine targets ($100/wk from $0), the deposit is
a huge fraction of equity: a −15% market day (vs the 8% stand-down limit) measures −5%
and trades straight through. The same contamination inflates `peak_equity`
(drawdown baseline) with deposits. The FM#1 test only covers "same-day equity on both
sides", not flow contamination.
Repro: `repro_10_contribution_masks_loss.py`

```
max_daily_loss_pct = 0.08
true market return: -15.0% | measured daily_return: -5.0%
decision: OK
AssertionError: BUG CONFIRMED ... the engine traded straight through its own daily-loss limit
```

### 11. `run_cycle` crashes with ValueError on a $0-equity decision day — **LOW/MEDIUM**
`run_backtest` guards its decision leg with `and equity > 0`; `run_cycle` does not.
`compute_orders` raises `ValueError("equity must be > 0")`, and `daily_run.py` catches
only `HaltError` — the scheduled job dies with a traceback, writes no report, saves no
state. This is the documented deployment shape ("$0 start"): a bootstrap on a month-end
before the first Monday contribution hits it. (Live/backtest parity gap in the guard
itself.)
Repro: `repro_11_zero_equity_decision_crash.py`

```
ValueError: equity must be > 0, got 0.0
AssertionError: BUG CONFIRMED: run_cycle crashed on a $0-equity decision day ...
```

### 12. The journal records NOTHING about fills when a rebalance aborts mid-flight — **MEDIUM**
`execute_rebalance` writes its `order_result` / `order_dropped` journal lines only after
the whole loop completes. A venue outage (or any `ExecutionError`, e.g. a non-terminal
status) after the first order means trades that REALLY EXECUTED leave zero trace in the
"append-only evidence" (§11) — in the repro the journal file is never even created. The
exception also propagates through `run_cycle` uncaught, so state isn't saved either.
Repro: `repro_12_journal_loses_fills.py`

```
mid-flight outage: simulated venue outage mid-flight
broker reality: cash=4995.50, positions={'B': 50.0} (the sell of A REALLY filled)
journal events recorded: 0
AssertionError: BUG CONFIRMED ... the evidence log has no record that the trade happened
```

### 13. An order that closes the ENTIRE position is not flagged `is_full_exit` — the min-size filter eats it forever — **MEDIUM (FM#4 variant)**
`compute_orders` sets `is_full_exit` only when `tgt_w == 0.0` exactly. A
small-but-nonzero target weight that floors to 0 shares emits a plain SELL of every
share, which `min_order_notional` (or the no-trade band) then drops. Every future
rebalance regenerates and re-drops the same order: the position can never close — the
exact ratchet §5.4 claims is impossible. The FM#4 test only checks `tgt_w == 0.0`.
Repro: `repro_13_unflagged_full_exit.py`

```
orders: [('SELL', 3.0, False)]        <- sells all 3 held shares, is_full_exit=False
kept: []
dropped: [('A', 'below min_order_notional 100.00 (notional 90.00); full exits are exempt')]
AssertionError: BUG CONFIRMED ...
```

### 14. `month_end_schedule` flags the final bar of any dataset as a decision day — **LOW**
`is_last != is_last.shift(-1)` is always True at the last row (period vs NaN), so the
backtest runs a full decision leg (pre_trade, strategy, order computation, possible
refusal/halt bookkeeping) on a mid-month bar whenever the data ends mid-month.
Repro: `repro_14_month_end_last_bar.py`

```
decision days: [datetime.date(2026, 1, 30), datetime.date(2026, 2, 11)]
AssertionError: BUG CONFIRMED: 2026-02-11 (a mid-month Wednesday ...) is treated as a
last-trading-day-of-month decision day
```

---

## SUSPECTED — UNPROVEN

- **Risk-veto "structure" is forgeable**: `ApprovedOrders(orders, token=RiskEngine._approval_token)` — the token is a readable class attribute; any module can stamp its own approvals (Python can't make invariant 6 structural, but the docstring overclaims).
- **DualMomentum "12-1" spans 13 months**: `start = iloc[-1-skip-look]` measures a 12-month return *ending* 1 month ago (t−13→t−1), not the academic 12-1 (t−12→t−1); results are not comparable with the literature the parameters were "fixed by".
- **`_momentum` uses `dropna()` + positional indexing**: sparse NaN history silently stretches the lookback window in calendar time (21 "trading days" of skip can span months).
- **NaN target weight crashes instead of refusing**: `clamp_weights` propagates NaN (`max(0.0, nan) = nan`) into `compute_orders`' `math.floor(nan)` → ValueError, not a DataError refusal.
- **`daily_run` journals the same "contribution" repeatedly** on consecutive refused/halted days (state never saved → `contributions_due` recounts the same Mondays; the journal's deposit evidence double-counts).
- **`DataError` uncaught in `daily_run.main`** (only `HaltError` is caught): any stale/missing symbol kills the scheduled job with a traceback and no report file.
- **`PaperBroker` deletes a position only when shares `== 0.0` exactly** (float equality); fractional-fill dust can linger as phantom positions.
- **`peak_equity` includes deposits**: heavy contribution periods raise the drawdown baseline with money that was never "gained", making the 35% hard-kill fire earlier than the strategy's true drawdown (mirror image of confirmed #10).
- **Buy resize uses the ORIGINAL order's cost** (`available - cost.total` for the full share count), so a resize that is affordable at the smaller commission can be dropped as unaffordable.
- **Negative contributions silently ignored** (`if c > 0` in `run_backtest`): a withdrawal schedule is dropped without error, and `contributions_total`/TWR flows would silently disagree with the caller's intent.

**Totals: 14 confirmed (4 high, 8 medium, 2 low), 10 unproven suspicions.**
