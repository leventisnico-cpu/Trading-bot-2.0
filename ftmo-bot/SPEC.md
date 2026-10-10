# FTMO Trading System — Claude Code Build Spec

Oct 5, 2026 · @Nico Leventis

## Read me first

This spec builds a rules-first FTMO challenge bot: a session breakout strategy wrapped in a drawdown engine that cannot be overridden by the strategy. The drawdown engine is the product; the strategy is replaceable.

**On profitability.** No one can guarantee a trading system is profitable, and anyone who does is selling something. What can be guaranteed is process: the system will not be paid for (challenge fee) until it clears every gate in the Go/no-go section on real tick data, out-of-sample, and 60 days of forward demo. If it fails a gate, the answer is "don't pay", not "tweak until green".

**Why not Astral.** Astral is long-only, US equities/crypto, and deploys to US brokers. FTMO is forex/indices/metals CFDs on MT5 and needs shorts. Different data, different execution, no bridge. This spec is Python + MT5 end to end.

**Why not copy Jane Street / Citadel / Renaissance.** Their edge is latency, co-location, and balance sheet. None of it survives retail spreads or a 5% daily loss cap. What *is* copyable from professional desks: fixed fractional risk, one-trade-one-thesis per session, hard kill switches, and refusing to trade when the data says no.

**Realistic outcome.** A well-built system of this type passes the 2-step challenge roughly 50–70% of the time per attempt, and a funded $100K account pays low-four figures per month in a good month. Treat it as a cash-flow side project, not the wealth engine.

## Strategy spec

One strategy, parameterised, applied to four instruments. The risk engine (next section) sits above it and wins every conflict.

**Instruments and sessions (all times CE(S)T, matching FTMO's daily reset)**

| Instrument | Session traded | Why |
|---|---|---|
| EURUSD | London open 09:00–12:00 | Tightest spread, cleanest range breakouts |
| GBPUSD | London open 09:00–12:00 | Higher ATR, same session logic |
| NAS100 | NY cash open 15:30–18:00 | Strongest intraday trend persistence |
| XAUUSD | London–NY overlap 14:00–17:00 | Liquidity peak, momentum follows through |

**Setup: Asian-range breakout with trend filter**

1. Define the Asian range: high/low from 00:00 to 08:00 CE(S)T (for NAS100: 09:00–15:15 pre-cash range).
2. Trend filter: 4H 50 EMA slope over last 6 bars. Longs only when slope > 0, shorts only when slope < 0. Flat slope (|slope| < 0.1 × ATR(14)) → no trade.
3. Entry: first 15m candle that closes beyond the range in the filtered direction. Enter at next candle open. Max 1 entry per instrument per session.
4. Stop: opposite side of the range, capped at 1.5 × ATR(14, 15m). If the natural stop is wider than the cap → skip the trade (don't shrink the stop, skip).
5. Target: 2.0 R fixed. Move stop to breakeven at 1.0 R. No trailing beyond that in v1.
6. Time exit: flatten any open position 15 minutes before session end. Nothing held overnight. Nothing held into 00:00 CE(S)T.
7. News filter: no entries 30 min before or after high-impact events for the instrument's currencies (use a free economic calendar feed, e.g. Forex Factory JSON).

**Risk sizing**

- Risk per trade: 0.75% of initial challenge balance (not current balance — keeps sizing stable).
- Position size = (balance × 0.0075) / (stop distance in price × contract value).
- Max 2 instruments open at once. Correlation guard: never long EURUSD and GBPUSD simultaneously in opposite directions; treat them as one slot.
- Daily soft stop: 2 consecutive losses → done for the day.

**What is explicitly out of scope for v1**

- Scalping, martingale, grid, hedging, averaging down. All of these are the fastest known routes to a daily-loss breach.
- Machine-learned signals. Not enough clean data at this timeframe to avoid overfitting; revisit only after a funded account exists.
- Optimising parameters per instrument. One parameter set across all four, or it's curve-fit.

## FTMO rules engine

The engine enforces limits tighter than FTMO's, measured the way FTMO measures them. Target the 2-Step Standard challenge; its static max-loss floor is the most forgiving geometry for this strategy. Confirm current figures on [ftmo.com](https://ftmo.com) before paying — rules drift.

| Rule | FTMO 2-Step (per tradingfunder, propfirmmap) | Engine hard limit |
|---|---|---|
| Profit target | 10% Challenge, 5% Verification | n/a — not enforced, just tracked |
| Max daily loss | 5% of initial balance, equity-based incl. floating PnL, swaps, commissions | 2.5% → flatten all, block new entries |
| Daily reset | 00:00 CE(S)T | Engine clock is Europe/Prague, DST-aware |
| Max overall loss | 10% of initial balance, static | 6% → flatten all, halt bot, require manual restart |
| Min trading days | 4 | Tracked; no action |
| Time limit | None | None |
| EA / automation | Allowed | — |
| Tick-by-tick SL/TP modification | Known failure pattern | SL/TP set once at entry, one breakeven move, nothing else |

**Implementation requirements**

- Equity, not balance. Daily loss = (equity at 00:00 CE(S)T) − (current equity, including unrealised PnL and accrued swap/commission). Poll equity every 5 seconds from the MT5 account info; never compute it from fills alone.
- Daily loss baseline snapshot is taken at exactly 00:00 CE(S)T from MT5 account equity and persisted to disk, so a bot restart mid-day does not reset the baseline.
- Pre-trade check: projected equity if the new position hits its stop must stay above both the daily limit and the overall limit, with spread + commission included. Otherwise reject the order.
- Kill switch runs in a separate process from the strategy, with its own MT5 connection. If the strategy process dies, the guard still flattens. If the guard dies, the strategy must refuse to open new positions (heartbeat file, 10-second staleness).
- Weekend/holiday guard: no positions open past Friday 21:00 CE(S)T; refuse entries on CE(S)T public holidays only if FTMO's market is closed (check MT5 symbol session info).
- 1-Step variant (3% daily, EOD-trailing 10%, Best Day cap) is a config profile, not a code branch. Don't target it in v1; the 3% daily loss leaves no room for the 2.5% engine limit plus slippage.

## Repo layout

Python 3.11, `uv` for deps, Windows VPS for live (MT5 Python API is Windows-only; backtesting runs anywhere).

```
ftmo-bot/
├── pyproject.toml
├── config/
│   ├── strategy.yaml        # one param set, all instruments
│   ├── ftmo_2step.yaml      # limits, reset tz, engine thresholds
│   └── ftmo_1step.yaml      # same schema, not used in v1
├── data/
│   ├── raw/                 # Dukascopy tick .bi5 → parquet
│   └── bars/                # 15m, 4H OHLCV parquet per symbol
├── src/ftmo_bot/
│   ├── data/
│   │   ├── dukascopy.py     # download + decode ticks
│   │   ├── resample.py      # ticks → bars, CE(S)T session tagging
│   │   └── calendar.py      # news events feed + holiday table
│   ├── strategy/
│   │   ├── base.py          # Strategy ABC: on_bar() → Signal | None
│   │   └── asian_breakout.py
│   ├── risk/
│   │   ├── sizing.py        # fixed-fractional, contract specs
│   │   ├── ftmo_rules.py    # pure functions: daily/overall loss, projections
│   │   └── guard.py         # live kill-switch process
│   ├── backtest/
│   │   ├── engine.py        # event-driven, tick-fill, spread+commission model
│   │   ├── ftmo_sim.py      # replays FTMO rules over a backtest → pass/fail
│   │   ├── montecarlo.py    # bootstrap trades → pass probability
│   │   └── report.py        # HTML report, equity curve, gate checklist
│   ├── execution/
│   │   ├── mt5_client.py    # thin wrapper over MetaTrader5 package
│   │   ├── order_router.py  # signal → order, idempotent by (symbol, session)
│   │   └── state.py         # persisted daily baseline, open positions, heartbeat
│   └── cli.py               # ftmo-bot {download,backtest,montecarlo,paper,live}
├── tests/                   # pytest; rules engine must hit 100% branch coverage
└── scripts/
    └── run_live.ps1         # starts guard, then strategy, on the VPS
```

**Module contracts that must not drift**

- `strategy/*` never imports `execution/*` or `risk/guard.py`. It emits `Signal(symbol, side, entry, stop, target, session_id)` and nothing else.
- `risk/ftmo_rules.py` is pure (no I/O, no MT5). Same code path in backtest and live. This is the single most important invariant in the repo.
- `execution/order_router.py` calls `ftmo_rules.can_open()` before every order and `sizing.size_for()` after. No bypass flag exists.
- `backtest/ftmo_sim.py` consumes the same `ftmo_rules.py` functions so a backtest "pass" means exactly what a live "pass" means.

## Data pipeline

Tick data is non-negotiable: a 15m-bar backtest cannot tell you whether your stop was hit before your target inside the same candle, and that ambiguity is where most "profitable" retail backtests die.

| Need | Source | Notes |
|---|---|---|
| Historical ticks, 5+ years | Dukascopy (free, .bi5) | EURUSD, GBPUSD, XAUUSD native; NAS100 as USA100.IDX/USD |
| Live ticks + bars | FTMO MT5 demo via `MetaTrader5` pip package | Same feed the challenge runs on |
| Spread model | Dukascopy bid/ask per tick + FTMO's published typical spreads | Use the worse of the two in backtest |
| Commission | FTMO: $3/lot/side forex, index/metal per spec | Hard-code in `config/ftmo_2step.yaml`, verify on demo |
| News events | Forex Factory weekly JSON (ff_calendar_thisweek.json) | Cache locally; high-impact only |
| Holidays | MT5 `symbol_info().sessions` | Don't maintain a hand table |

**Pipeline steps**

1. `ftmo-bot download --symbol EURUSD --from 2020-01-01` → raw `.bi5` → decoded parquet, one file per symbol-day, columns `ts_utc, bid, ask`.
2. `ftmo-bot resample` → 15m and 4H bars in parquet, with a `session` column tagged in CE(S)T (Europe/Prague) and a `date_cest` column for daily-loss grouping.
3. Integrity checks before any backtest: no gaps > 5 min during sessions, no negative spreads, bid ≤ ask, tick count per hour within 3σ of symbol median. Failing days are excluded and logged, never interpolated.
4. Split: 2020–2023 in-sample, 2024–2025 out-of-sample, 2026 YTD reserved as a final holdout touched once.

**Storage**: local parquet, ~2–4 GB for four symbols over six years. No database in v1.

## Backtest and Monte Carlo layer

The backtest answers one question: *what fraction of 10,000 simulated challenge attempts pass without breaching a rule?* Sharpe, CAGR and win rate are diagnostics, not the score.

**Backtest engine (`backtest/engine.py`)**

- Event-driven over ticks, not bars. Strategy sees completed 15m bars; fills, stops and targets are resolved against the tick stream.
- Fill model: market entries fill at ask (long) / bid (short) of the next tick plus 0.2 pips (forex) / 1 point (NAS100) / 10 cents (gold) slippage. Stops fill at the first tick through the level, with the same slippage. Targets fill at touch, no slippage (conservative on the right side).
- Costs: spread from ticks, commission per `ftmo_2step.yaml`, swap irrelevant (nothing held overnight).
- Output: a trades table (`entry_ts, exit_ts, symbol, side, r_multiple, pnl_usd, mae, mfe, session_id`) and a per-tick equity series — the equity series is what `ftmo_sim.py` needs.

**FTMO simulator (`backtest/ftmo_sim.py`)**

- Replays the equity series day by day in CE(S)T, applying the engine limits (2.5% daily, 6% overall) and the real FTMO limits (5% / 10%) separately. Reports both: how often the engine would have halted you, and how often you'd have actually failed.
- Slices the full history into every possible challenge start date (rolling windows). Each window runs until target hit or rule breached. Reports pass rate, median days to pass, and distribution of max daily drawdown.

**Monte Carlo (`backtest/montecarlo.py`)**

- Block-bootstrap the trades table (block = one session, preserves intra-session correlation), 10,000 paths, each path a fresh challenge from $100K.
- Each path also randomly: drops 10% of trades (missed fills), widens spread by 0–50%, adds 0–1 pip extra slippage. The strategy must pass under stress, not under the historical spread.
- Output: pass probability for Phase 1, Phase 2, and both; probability of breaching daily loss specifically; expected cost to a funded account in challenge fees (fee ÷ pass probability).

**Overfitting controls**

- Parameters are fixed in `strategy.yaml` before running on out-of-sample data. Any change after seeing OOS results resets the OOS clock: pick new params, re-run in-sample, then OOS once.
- Walk-forward: 6-month train, 3-month test, rolling, as a sanity check that one param set holds across regimes.
- Report must show in-sample vs out-of-sample vs holdout side by side. A strategy whose OOS pass rate is under 70% of in-sample is overfit, regardless of absolute numbers.

## Execution layer

Two processes on a Windows VPS in Europe (FTMO's servers are EU-hosted; a London or Frankfurt VPS keeps round-trip under 20 ms). Each process has its own MT5 login. Neither trusts the other to be alive.

**Process 1 — Guard (`risk/guard.py`)**

- Starts first. Polls `mt5.account_info().equity` every 5 s.
- At 00:00 CE(S)T writes `state/daily_baseline.json` with equity and timestamp. On startup, if today's baseline already exists on disk, loads it instead of re-snapshotting.
- If daily loss ≥ 2.5% or overall loss ≥ 6%: `mt5.Close` every position, cancel every pending order, write `state/HALT` with reason, and keep flattening every 5 s until positions = 0. Overall-loss halt requires a human to delete `state/HALT`.
- Writes `state/heartbeat` every 5 s. Logs every decision with equity, baseline, and limit to a rotating file.

**Process 2 — Strategy runner (`cli.py live`)**

- Refuses to start if `state/heartbeat` is older than 10 s or `state/HALT` exists.
- On each completed 15m bar for an instrument in session: `strategy.on_bar()` → `Signal | None` → `ftmo_rules.can_open(signal, equity, baseline, open_positions)` → `sizing.size_for()` → `order_router.place()`.
- Idempotency key = `(symbol, session_date, side)`. Persisted before the order is sent. A crash and restart cannot double-enter.
- Stop and target are placed server-side on the order itself (`sl`, `tp` fields), never managed from Python. The one breakeven modification happens once, then the position is left alone.
- Time exit and Friday flatten are handled by the runner; the guard also enforces them as a backstop.

**Promotion path**

1. FTMO Free Trial account (14-day demo with challenge rules) — run the full stack, verify the guard flattens on a deliberately induced 2.5% drawdown.
2. Second Free Trial, 60 days total of forward-testing across renewals — compare live fills against backtest fill model; adjust slippage assumptions upward if live is worse.
3. Paid challenge only after the Go/no-go section is fully green.

**Monitoring**: Telegram bot message on every order, every guard decision, and a daily 00:05 CE(S)T summary (equity, daily PnL, trades, distance to each limit). If no heartbeat message for 10 minutes during a session, you get a page.

## Go/no-go gates

Every box ticked before any challenge fee is paid. One red box = don't pay. These are the "make sure it's profitable" controls; they can't make the market cooperate, but they stop you funding a system the data already says is losing.

**Data and code**

- [ ] Tick data integrity checks pass for all four symbols, 2020–present
- [ ] `risk/ftmo_rules.py` at 100% branch coverage, including DST transitions and midnight CE(S)T edge cases
- [ ] Backtest and live use the identical `ftmo_rules.py` code path (verified by a test that runs both against the same equity series)

**Backtest (out-of-sample 2024–2025, after params frozen)**

- [ ] ≥ 500 trades across the four instruments
- [ ] Expectancy ≥ 0.25 R per trade after spread, commission and slippage
- [ ] Rolling-window FTMO Phase 1 pass rate ≥ 70%
- [ ] OOS pass rate ≥ 70% of in-sample pass rate (overfit check)
- [ ] Max daily drawdown in any window < 4% of initial balance (buffer under FTMO's 5%)
- [ ] Holdout (2026 YTD) run once; expectancy positive and pass rate within 15 points of OOS

**Monte Carlo (10,000 stressed paths)**

- [ ] P(pass Phase 1 and Phase 2) ≥ 60%
- [ ] P(breach daily loss at FTMO's 5%) ≤ 5%
- [ ] Expected challenge cost to funded = fee ÷ P(pass) ≤ 2 × fee

**Forward (FTMO Free Trial, 60 days)**

- [ ] Guard verified: induced 2.5% drawdown flattened within 10 s, logged, Telegram alert received
- [ ] Live fills within 1.5× backtest slippage assumptions; if worse, re-run backtest with live slippage and re-check gates
- [ ] Forward expectancy ≥ 0.15 R (lower bar: small sample)
- [ ] Zero unintended orders, zero double entries, zero positions held past session end across the full 60 days

**If gates fail**: the next move is a different strategy family (mean reversion in Asian session, or NY-open momentum only), not parameter tuning on this one. Log the failure, keep the infrastructure, swap the `strategy/` module.

## Claude Code prompts

Run these in order, one per session, in an empty `ftmo-bot/` directory. Paste this whole document into the repo as `SPEC.md` first; every prompt references it. Don't move to the next phase until the previous phase's tests pass.

**Phase 0 — CLAUDE.md and scaffold**

> Read SPEC.md fully. Create CLAUDE.md with: the module contracts from "Repo layout" as hard rules; "risk/ftmo_rules.py is pure and shared by backtest and live" as the top invariant; Python 3.11 + uv + pytest + ruff + mypy strict. Scaffold the exact tree in SPEC.md with empty modules, pyproject.toml, config/strategy.yaml and config/ftmo_2step.yaml populated from the Strategy and FTMO rules sections. Add a GitHub Actions workflow running ruff, mypy, pytest. Commit.

**Phase 1 — Rules engine (pure)**

> Implement src/ftmo_bot/risk/ftmo_rules.py per SPEC.md "FTMO rules engine": dataclasses for Limits and AccountState; functions daily_loss(), overall_loss(), can_open(signal, state, limits) returning (bool, reason), should_halt(), next_reset_utc(now) using zoneinfo Europe/Prague. No I/O, no MT5 import. Write pytest cases for: DST spring-forward and fall-back nights, equity exactly at limit, floating loss pushing past limit while balance is fine, baseline persistence across restart, correlation-slot rule. Achieve 100% branch coverage. Do not proceed to other modules.

**Phase 2 — Data pipeline**

> Implement data/dukascopy.py (download + LZMA .bi5 decode to parquet, resumable, rate-limited), data/resample.py (ticks → 15m and 4H bars with CE(S)T session and date_cest columns), data/calendar.py (Forex Factory weekly JSON cache, high-impact filter). Implement the integrity checks in SPEC.md "Data pipeline" as a CLI command that writes a report and excludes failing days. Add the `ftmo-bot download` and `ftmo-bot resample` CLI commands. Test resample against hand-built tick fixtures including a DST boundary. Download EURUSD 2024-01 only as a smoke test.

**Phase 3 — Strategy**

> Implement strategy/base.py (Strategy ABC, Signal dataclass) and strategy/asian_breakout.py exactly per SPEC.md "Strategy spec" steps 1–7. Parameters come only from config/strategy.yaml. Add tests with synthetic bars for: no trade on flat EMA slope, skip when natural stop exceeds 1.5×ATR cap, one entry per instrument per session, news-window suppression, correct range for NAS100 pre-cash definition. The strategy module must not import anything from execution/ or risk/guard.py — add a test that asserts this via import graph.

**Phase 4 — Backtest + FTMO sim + Monte Carlo**

> Implement backtest/engine.py (event-driven over ticks, fill model and costs per SPEC.md), backtest/ftmo_sim.py (rolling-window challenge replay using risk/ftmo_rules.py — assert via test it's the same functions), backtest/montecarlo.py (session-block bootstrap, 10,000 stressed paths), backtest/report.py (HTML with in-sample / OOS / holdout columns and the Go/no-go checklist auto-filled). CLI: `ftmo-bot backtest --split insample|oos|holdout` and `ftmo-bot montecarlo`. Run in-sample on the four symbols with frozen params and show me the report. Do NOT run OOS yet.

**Phase 5 — Execution + guard**

> Implement execution/mt5_client.py (thin typed wrapper over the MetaTrader5 package, retries, structured logging), execution/state.py (daily baseline JSON, heartbeat file, idempotency keys, HALT file), risk/guard.py as a standalone process per SPEC.md "Execution layer" Process 1, execution/order_router.py and `ftmo-bot live` as Process 2, plus Telegram notifications. Server-side SL/TP only; one breakeven modify. Write scripts/run_live.ps1. Mock the MT5 package in tests; cover: runner refuses start on stale heartbeat, guard flattens on induced drawdown, restart does not double-enter, Friday flatten.

**Phase 6 — Gates**

> Run `ftmo-bot backtest --split oos` once with params unchanged since Phase 4. Then holdout once. Then montecarlo. Fill the Go/no-go checklist in the report. If any gate is red, stop and tell me which, with the numbers — do not adjust parameters. If all green, write RUNBOOK.md for the FTMO Free Trial forward test: VPS setup, MT5 login, induced-drawdown test procedure, daily checks.

**Standing instruction for every session**

> If any instruction conflicts with the drawdown limits or the module contracts in SPEC.md, refuse and explain. Never add a flag that bypasses risk/ftmo_rules.py.
