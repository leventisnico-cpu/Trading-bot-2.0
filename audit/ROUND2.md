# Adversarial Audit — Round 2

Environment: `python3 -m pytest tests -q` → **81 passed** (the post-fix suite is green;
every bug below survives it). Each finding has a runnable reproduction in
`audit/repro_r2_*.py`; every script **raises AssertionError while the bug exists**
(run: `cd /home/user/Trading-bot-2.0/audit && python3 repro_r2_NN_*.py`).
No file outside `audit/` was modified.

Focus: (a) regressions and holes in the 14 round-1 fixes (commit `85a0864`);
(b) what round 1 missed. Findings 4, 5, 6, 7, 3, 10 are direct fallout of round-1
fixes #1, #6, #7, #8, #14 respectively.

---

## CONFIRMED

### 1. A HARD_KILL whose liquidation fails is NEVER PERSISTED — the engine trades again tomorrow — **HIGH**
`runner.py`: on HARD_KILL, `state.halted = True` is set in memory, then the liquidation
runs through `execute_rebalance` — which raises `ExecutionError` on a venue outage or
non-terminal status. The exception propagates out of `run_cycle` **before**
`store.save(state)` (step 7): the durable state still says `halted=False`. The next
cycle loads an un-halted engine and keeps trading through a fired kill switch (and if
equity bounces above the drawdown line meanwhile, the kill is lost entirely).
"Manual reset only, no automatic recovery, ever (§7)" is defeated by an outage at the
worst moment. The ordinary-rebalance path catches `ExecutionError` (round-1 fix #12);
the far more critical liquidation path does not.
Repro: `repro_r2_01_halt_lost_on_liquidation_error.py`

```
ExecutionError propagated out of run_cycle: simulated venue outage mid-flight
persisted state after the kill: halted=False, halt_reason=''
AssertionError: BUG CONFIRMED: HARD_KILL fired (drawdown 50% > 35%) but the venue outage
during liquidation aborted run_cycle before store.save() — the durable state still says
halted=False ...
```

### 2. A data glitch in ANY risk asset liquidates the ENTIRE book — **HIGH**
`strategies.py::DualMomentum`: `_momentum` returns `None` for a symbol whose 253-bar
window has >5% NaN (or too little history); `target_weights` then returns `{}` ("stay
in cash rather than rank a partial menu"). But `{}` is not "stay put":
`compute_orders` treats every held symbol as target 0 shares and emits `is_full_exit`
SELLs of everything — and `validate_prices` cannot catch it (it checks only each
symbol's LAST value). 20 NaN closes in XEC.TO — a symbol not even held — sold the
whole XUU.TO position and paid real costs. §5.7's core principle ("a data gap must
never silently become target weight 0") is violated one layer above the data checks
round 1 audited.
Repro: `repro_r2_02_data_glitch_liquidates_book.py`

```
validate_prices: PASSED (the glitch is invisible to the data layer)
target_weights: {}
fills: [('SELL', 'XUU.TO', 'FILLED')]
positions after: {}, cash: 4995.50
AssertionError: BUG CONFIRMED: 20 NaN closes in XEC.TO (not even held) made DualMomentum
return {} and the engine SOLD THE ENTIRE XUU.TO position ...
```

### 3. Report headlines "NO REBALANCE TODAY — HOLDINGS UNCHANGED" on the day everything was sold — **MEDIUM** (round-1 #8 fix overcorrection)
Round-1 fix #8 keyed the header on `target_weights` being truthy. A strategy returning
`{}` (all-cash target — DualMomentum does this routinely when the defensive asset's
momentum is negative, and in finding #2's glitch case) still produces full-exit sells
that `run_cycle` executes; `build_report` then takes the empty-target branch and prints
`NO_REBALANCE_HEADER` directly above the order list showing the liquidation. The same
empty-target case also skips the §5.9 convergence bookkeeping (`last_completed_period`
never set, retries never counted).
Repro: `repro_r2_03_report_says_unchanged_after_selling_all.py`

```
orders this cycle:
  [ok] SELL 50 XUU.TO -> FILLED filled 50 @ 100.00
positions were sold: True; header: 'NO REBALANCE TODAY — HOLDINGS UNCHANGED'
AssertionError: BUG CONFIRMED ...
```

### 4. The new batch order cap TRUNCATES HARD_KILL liquidation — halted forever while still holding positions — **HIGH** (regression from round-1 #1 fix)
`execute_rebalance` now applies `truncate_to_cap` to every batch — including the
"liquidate everything" batch from a HARD_KILL (both `runner.py` and `backtest.py`).
With more positions than `max_orders_per_day`, the excess sells are dropped, the
engine sets `halted=True` and saves — and since halted means manual reset only, **no
future cycle can ever sell the remainder**. The kill switch that exists to take you
out of the market leaves you in it, permanently. (Pre-fix, the cap was a no-op, so
liquidations always went out in full.)
Repro: `repro_r2_04_cap_truncates_kill_liquidation.py`

```
halted: True (drawdown 70.0% exceeds max 35.0%)
positions after 'liquidate everything': {'XIC.TO': 20.0}
dropped: [('XIC.TO', 'max_orders_per_day cap (2) — buys dropped before sells')]
next cycle: HaltError: system is HALTED ... manual reset required
AssertionError: BUG CONFIRMED ... halted forever while still holding {'XIC.TO': 20.0}
```

### 5. Escalation resends bypass the order cap — cap N puts up to 2N orders on the wire — **MEDIUM** (hole in round-1 #1 fix)
The batch cap counts *intended* orders. Each unfilled limit order then escalates to a
NEW market order via `_submit_single`, whose single-order `filter_orders` call is
exactly the round-1 no-op. With cap=2, two expiring limit sells put FOUR orders on the
venue. (Reachable whenever limit orders are used — the §5.10 escalation feature exists
for them; today's `compute_orders` emits market orders only, so the paper pipeline
does not currently hit it, but `execute_rebalance` is the boundary that claims the cap.)
Repro: `repro_r2_05_escalation_busts_order_cap.py`

```
configured max_orders_per_day = 2
orders submitted to the broker: 4 ([('A','LMT'), ('A','MKT'), ('B','LMT'), ('B','MKT')])
AssertionError: BUG CONFIRMED: cap is 2 but 4 orders reached the venue ...
```

### 6. Negative cash is BACK — a partial fill on an approved full-exit sell pays the $1 minimum fee out of $0.88 of proceeds — **MEDIUM** (breaks round-1 #6 fix)
The new dust guard (`frac >= 1.0` in `filter_orders`) evaluates cost at the FULL order
size, and `PaperBroker`'s sell path still credits `filled * px - cost.total`
unconditionally. A 2-share $2.20 position passes the guard (all-in ≈45% of notional),
then fills 40%: 0.8 sh × $1.10 = $0.88 of proceeds vs a $1.00 commission floor → cash
goes negative through the exact hole fix #6 claimed closed.
Repro: `repro_r2_06_partial_fill_negative_cash.py`

```
all-in close cost at FULL size: 45.5% of notional (round-1 dust guard approves)
results: [('PARTIALLY_FILLED', 0.8)]
cash after the partial full-exit fill: -0.1206
AssertionError: BUG CONFIRMED: cash is -0.1206 ...
```

### 7. Buy resize is seeded with the FULL planned order's cost and only decrements — affordable buys dropped entirely — **MEDIUM** (regression in round-1 #7 fix)
`execution.py`: `resized = floor((available - cost.total) / px)` where `cost` is priced
at the PLANNED share count. When the planned order dwarfs available cash (exactly the
situation the per-buy account re-read exists for — e.g. this month's sells expired, so
the cash they were to free never arrived), the seed is negative and the buy is dropped
as "insufficient confirmed cash", even though a smaller buy passes every check. The
new while-loop only walks DOWN from the seed; nothing walks up.
Repro: `repro_r2_07_buy_resize_drops_affordable_buy.py`

```
available cash: 200.00; planned buy: 10000 sh @ 30.0
cost of the PLANNED order used as resize seed: 310.00 -> seed < 0
6 shares would cost 181.13 <= 200.00 (affordable, notional 180 > min_order_notional 100)
dropped: [('B', 'insufficient confirmed cash (200.00) after sells')]
AssertionError: BUG CONFIRMED ...
```

### 8. The backtest silently drops every contribution landing on a market holiday; live credits them all — **MEDIUM** (live/backtest parity, Phase 4 numbers)
`run_backtest` evaluates `contribution(today)` only for dates in the price index, so a
$100 Monday deposit on a market holiday never happens; `daily_run.contributions_due`
counts every CALENDAR Monday. The TSX closes on ~5 Mondays/year (Family Day, Victoria
Day, Civic Holiday, Labour Day, Thanksgiving) → the Phase 4 headline "$0 start,
$100/week" run under-funds the strategy by ~$500/yr (~10% of the deposit stream)
relative to the deployment it claims to model; final-wealth rows in
`docs/PHASE_4_RESULTS.md` are not comparable with what the paper engine will do.
(`phase4_backtest.flows_for` is consistent with `run_backtest`, so TWR itself is not
corrupted — the modeled deposit stream is simply wrong vs live.)
Repro: `repro_r2_08_backtest_drops_holiday_monday_deposits.py`

```
calendar Mondays in span: 7
backtest contributions_total: 600
daily_run.contributions_due over the same span: 700
AssertionError: BUG CONFIRMED ...
```

### 9. Same-day re-runs with net_flows ratchet peak_equity without bound → FALSE HARD_KILL on flat equity — **MEDIUM** (hole in round-1 #10 fix)
The fix taught `pre_trade` to skip `daily_return` when `last_equity_date == today`, but
the peak update in `runner.py` step 7 (`peak_equity = max(peak_equity + net_flows,
equity)`) has no same-day guard: each re-run with the same flows adds the same $100 to
the drawdown baseline again. Seven same-day cycles on flat $1,100 equity push peak to
$1,700 → drawdown 35.3% → liquidate + permanent halt on an account that never lost a
cent. `daily_run`'s `contributions_due` zeroes flows after a *saved* run, but any
re-run against already-updated state that re-supplies flows (workflow retry with an
external flow source, stale state re-commit) walks straight into it — `run_cycle`'s own
API contract silently double-counts.
Repro: `repro_r2_09_sameday_flows_false_hard_kill.py`

```
same-day call 1: peak_equity=1100  ... call 6: peak_equity=1600
same-day call 7: peak_equity=1700 halted=True
-> HARD KILL: drawdown 35.3% exceeds max 35.0% (equity was flat at 1,100)
AssertionError: BUG CONFIRMED ...
```

### 10. month_end_schedule's final-bar guard skips genuine month-ends that precede an exchange holiday — **LOW** (round-1 #14 fix overcorrection)
The new guard compares the last bar against `pd.bdate_range`, which knows weekends but
not exchange holidays. 2024-03-29 was Good Friday (markets closed), so 2024-03-28 was
the real last trading day of March 2024: with data through April that bar IS a decision
day (data-based rule); with data ending 2024-03-28 the SAME bar is NOT — the backtest
silently skips the final month's rebalance. Also diverges from
`daily_run.is_last_trading_day_of_month`, which fires on the holiday itself (with
day-old data).
Repro: `repro_r2_10_month_end_holiday_final_bar.py`

```
2024-03-28: flagged when it is the dataset's FINAL bar: False
            flagged when data continues into April:     True
AssertionError: BUG CONFIRMED ...
```

### 11. `allow_leverage=true` disables ALL gross-exposure validation — a negative cap turns longs into SHORTS despite `allow_short=false` — **LOW**
`validate_config`: `0 < max_gross_exposure <= 1 or allow_leverage` accepts 0 and
negative values once leverage is on. `clamp_weights` applies the no-short clamp
per-symbol FIRST, then scales by `cap/gross` — a negative cap makes the scale negative
and flips every long into a short AFTER the no-short clamp ran. Two invariants (§3.4
no shorts; validated config) fail together. (Also noted: `spread_bps=499` — a 4.99%
spread — passes validation while guaranteeing every non-exempt order fails the 2%
`max_cost_fraction`; see SUSPECTED.)
Repro: `repro_r2_11_leverage_config_allows_shorts.py`

```
validate_config ACCEPTED allow_leverage=true, max_gross_exposure=-1.0
clamp_weights output with allow_short=False: {'XUU.TO': -0.5, 'XEF.TO': -0.5}
AssertionError: BUG CONFIRMED ...
```

### 12. The paper bootstrap swallows the first weekly contribution; contributions_due's first-run branch is dead code — **LOW**
`daily_run.main()` bootstraps with `EngineState(last_equity_date=today.isoformat())`,
so `contributions_due`'s documented first-run branch (`if not state.last_equity_date:
return WEEKLY_CONTRIBUTION`) can never fire via `main()`, and the accrual loop starts
at `last_equity_date + 1` — a bootstrap ON a Monday credits $0 for that Monday. The
deployment's first $100 never arrives; the engine idles an extra week at $0.
Repro: `repro_r2_12_bootstrap_swallows_first_contribution.py`

```
bootstrap on Monday 2026-09-07: contribution due on the first run = 0.0
AssertionError: BUG CONFIRMED ...
```

### 13. The journal double-counts the same deposit on every refused/halted day — **LOW** (round-1 unproven suspicion, now proven)
`daily_run.main()` records `journal.record("contribution", amount=...)` BEFORE
`run_cycle`. On a refusal (halted engine, bad data) state never advances, so the next
scheduled run re-derives the same Mondays and journals the same deposit again. After N
refused days the §11 evidence record shows N deposits where the schedule owed one.
Repro: `repro_r2_13_journal_double_counts_contributions.py`

```
'contribution' events journaled: [100.0, 100.0] (total 200 vs owed 100)
AssertionError: BUG CONFIRMED ...
```

### 14. The interrupted-save wedge kills the daily job with a raw traceback — no REFUSED report, no journal entry — **LOW**
`StateStore.save()` has a real crash window between its two `os.replace` calls (main
renamed to `.bak`, new file not yet in place); the stricter round-1 `load()` rightly
refuses that layout. But `daily_run.main()` calls `store.load()` OUTSIDE its
`try/except HaltError`, so the `StateError` — which IS a `HaltError`, i.e. exactly what
the handler was built for — escapes `main()`: no "REFUSED TO TRADE" report is written
and no `refusal` journal entry is made. The refusal path needing the most urgent human
attention is the only one that reports nothing. (`save()` itself still works when main
is missing, so the engine cannot wedge *through* save — the wedge is load-side +
reporting.)
Repro: `repro_r2_14_wedge_crashes_without_report.py`

```
StateError ESCAPED main(): state file .../paper_state.json is missing but backup ...
reports written: []
'refusal' journal entries: []
AssertionError: BUG CONFIRMED ...
```

### 15. `skip_months > lookback_months` crashes DualMomentum with a raw IndexError — strategy params validated nowhere — **LOW**
`_momentum` windows `lookback*21 + 1` bars then indexes `window.iloc[-1 - skip*21]`;
nothing checks `skip <= lookback` (`[strategy]` is opaque to `validate_config`;
`__init__` validates only `top_n`). `IndexError` is not a `HaltError`, so live it
would escape `daily_run`'s refusal handling as a traceback. A config typo becomes a
crash instead of a startup `ConfigError`. (The corrected 12-1 window itself checks
out: `start = t-252`, `end = t-21` for 12-1; `skip=0` correctly ends at `t`.)
Repro: `repro_r2_15_skip_gt_lookback_crash.py`

```
raw IndexError: single positional indexer is out-of-bounds
AssertionError: BUG CONFIRMED ...
```

---

## Round-1 fixes verified as holding (attacked, not broken)

- **Batch cap ordering**: sells are still kept preferentially at the cap
  (`truncate_to_cap` sorts sells first); ordinary rebalances at/under the cap behave.
- **Per-buy account re-read**: `PaperBroker` settles fills synchronously, so sizing
  off the re-read cash is correct in the fake (the *seed* bug is finding #7).
- **Flow-adjusted `pre_trade`**: no double counting on the first-ever cycle
  (`last_equity=0` skips the daily-return check; `peak=0 + flows` is correct), nor in
  the backtest (flows enter the stored peak exactly once per bar).
- **`StateStore.save()`** works when the main file is missing and a backup exists —
  the engine cannot wedge itself through save (the load-side reporting gap is #14).
- **`full_exit = tgt_shares == 0`**: an ordinary rebalance down to a small-but-nonzero
  share count emits a plain partial sell, as intended.
- **Dust refusal boundary**: a full fill at `frac` just below 1.0 (e.g. 0.99 on a
  $1.01 position) still nets non-negative proceeds — only *partial* fills break it (#6).
- **Backtest leg ordering**: pending orders are neither leaked nor clobbered between
  the fill/risk/decision legs (STAND_DOWN can never overwrite a pending liquidation;
  HARD_KILL on a decision bar correctly suppresses the decision leg); `last_equity`
  update ordering vs the daily `pre_trade` is consistent with live.
- **`phase4_backtest.metrics`** flow alignment is internally consistent
  (`flows_for` and `run_backtest` use the same index/predicate — the shared *stream*
  is what's wrong vs live, finding #8).

## SUSPECTED — UNPROVEN

- **Config self-consistency**: `spread_bps` up to 499 (4.99%) passes validation while
  `max_cost_fraction=0.02` then refuses every non-exempt order — a config that
  silently never trades; no cross-field check relates costs to `max_cost_fraction`,
  `min_order_notional` to `no_trade_band`, or `min_equity_floor` to fee scale.
- **`deviations`/`converged` treat a NaN price as truthy** (`if px` on `float('nan')`):
  a NaN slips past as `dev=NaN`, and `NaN > tol` is False, so `converged()` returns
  True on garbage. Unreachable through the validated live path today; one refactor away
  from marking a broken book "AT TARGET".
- **Backtest lag ordering vs live kill switches**: the fill leg executes *yesterday's*
  decision before the bar's `pre_trade` runs, so on a crash bar the backtest trades
  first and stands down after; live gates before any order. One-bar divergence
  inherent to the t/t+1 model, unquantified.
- **State persistence via git commit** (the workflow commits `state/paper_state.json`):
  a failed commit resurrects yesterday's state on the next run → the same Monday is
  recounted → a phantom $100 is re-deposited into the paper account and the peak
  ratchets (the realistic road into confirmed #9). Ops-level; not reproducible in-repo.
- **`fee_drag_yr` denominator** averages the full equity curve including the
  zero/near-zero pre-funding prefix of the $0-start run, overstating drag for the
  headline row (and `years` there counts pre-funding bars too).
- **STAND_DOWN on the month's single decision day skips that month's rebalance
  entirely** — there is no catch-up day; live and backtest agree, but a one-day soft
  halt costs a whole month of signal.
- **`PaperBrokerKnobs.scripted_status` of `FILLED` is silently ignored** (only
  non-FILLED scripts short-circuit; a FILLED script falls through to organic execution
  and may come back PARTIALLY_FILLED via `fill_fraction`) — a test-fake semantics trap.
- **`RebalanceOutcome.escalations` increments even when the escalated order is dropped
  by the risk layer** (never submitted), overstating escalation counts in reports.

**Totals: 15 confirmed (3 high, 6 medium, 6 low), 8 unproven suspicions.**
