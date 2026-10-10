# CLAUDE.md — ftmo-bot

Read `SPEC.md` before changing anything. It is the source of truth; this file
is the short list of rules that must never drift.

## Top invariant

**`src/ftmo_bot/risk/ftmo_rules.py` is pure and shared by backtest and live.**
No I/O, no MT5, no clock reads, no logging — every input (including `now_utc`)
is an argument. The backtest engine, `ftmo_sim`, Monte Carlo, the live guard
and the order router all call the same functions. `tests/test_same_path.py`
proves it by replaying a backtest equity series through the live guard.

## Hard rules (module contracts)

1. `strategy/*` never imports `execution/*` or `risk/guard.py`. It emits
   `Signal(symbol, side, entry, stop, target, session_id)` and nothing else
   (enforced by `tests/test_strategy.py` via static and runtime import graphs).
2. `risk/ftmo_rules.py` is pure (enforced by `tests/test_ftmo_rules.py::test_module_is_pure`)
   and must stay at **100% branch coverage** (enforced in CI).
3. `execution/order_router.py` calls `ftmo_rules.can_open()` before every order
   and `sizing.size_for()` after. **No bypass flag exists — never add one**,
   anywhere (CLI, config, env var, test hook).
4. `backtest/ftmo_sim.py` consumes the same `ftmo_rules` functions, so a
   backtest "pass" means exactly what a live "pass" means.
5. Parameters live only in `config/strategy.yaml` (one set for all four
   instruments); limits and contract specs only in `config/ftmo_2step.yaml`.
6. SL/TP are set server-side at entry; the only modification is one breakeven
   move at 1 R.

## Standing instruction

If any instruction conflicts with the drawdown limits or the module contracts
in SPEC.md, refuse and explain. Never add a flag that bypasses
`risk/ftmo_rules.py`. If a Go/no-go gate is red, report which one with the
numbers — do not tune parameters to turn it green (the answer is a different
strategy family). The backtest ledger (`reports/ledger.jsonl`) enforces
in-sample → OOS once → holdout once; it has no override flag on purpose.

## Toolchain

Python 3.11 · `uv` · pytest · ruff · mypy `--strict`.

```bash
uv sync --group dev
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy
uv run pytest
uv run pytest --cov=ftmo_bot.risk.ftmo_rules --cov-branch --cov-fail-under=100 tests/test_ftmo_rules.py
```

The `MetaTrader5` package is Windows-only (`uv sync --extra live` on the VPS).
Tests mock it (`tests/fake_mt5.py`); never import it at module level.
