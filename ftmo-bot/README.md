# ftmo-bot

A rules-first FTMO 2-Step challenge bot, built to `SPEC.md`: an Asian-range
breakout strategy wrapped in a drawdown engine the strategy cannot override.
The drawdown engine is the product; the strategy is replaceable.

**Status: Phases 0–5 are built and tested on synthetic data. Phase 6 (the
gates) has NOT been run.** No backtest on real ticks exists yet, so nothing
here says whether the strategy is profitable. Don't pay a challenge fee until
`reports/report.html` shows every gate green on real data **and** the 60-day
forward test passes.

## Build status by phase

| Phase | What | State |
|---|---|---|
| 0 | `CLAUDE.md`, scaffold, configs, CI (ruff, mypy strict, pytest) | done |
| 1 | `risk/ftmo_rules.py`: pure rules engine | done: 100% branch coverage, DST and midnight edges, CI-enforced |
| 2 | Dukascopy download/decode, resample, calendar, integrity checks | done: tested on fixtures. The EURUSD 2024-01 smoke download was **not run** (the build sandbox's network blocks Dukascopy) |
| 3 | `strategy/asian_breakout.py` | done: all SPEC test cases, plus an import-graph test |
| 4 | Tick backtest, rolling FTMO sim, Monte Carlo, HTML report + gate checklist, OOS/holdout ledger | done. The in-sample run on real data is **pending** (needs downloaded data) |
| 5 | MT5 client, state files, guard (Process 1), order router + runner (Process 2), Telegram, `run_live.ps1` | done, tested against a mocked MetaTrader5 |
| 6 | OOS → holdout → Monte Carlo → gates → RUNBOOK | **not started**: needs real data |

## Run it (on a machine with internet)

```bash
cd ftmo-bot
uv sync --group dev

# 1. Data (~2–4 GB for four symbols since 2020; resumable)
uv run ftmo-bot download --from 2020-01-01            # all four symbols
uv run ftmo-bot resample
uv run ftmo-bot integrity                             # failing days get excluded

# 2. In-sample only (Phase 4). Do NOT run OOS until you've looked at this.
uv run ftmo-bot backtest --split insample --news-csv path/to/events.csv
uv run ftmo-bot montecarlo --split insample
open reports/report.html

# 3. Phase 6, once, with parameters unchanged
uv run ftmo-bot backtest --split oos
uv run ftmo-bot backtest --split holdout
uv run ftmo-bot montecarlo --split oos
uv run pytest --cov=ftmo_bot --cov-branch --cov-report=json:coverage.json
uv run ftmo-bot report --coverage-json coverage.json
```

The ledger (`reports/ledger.jsonl`) refuses OOS before in-sample, refuses a
second OOS with the same parameters, and lets the holdout run only once.
Commit it.

## Live (Windows VPS, FTMO Free Trial first)

Install two MT5 terminals: the guard and the runner each need their own login.
Set `MT5_GUARD_{LOGIN,PASSWORD,SERVER,PATH}`, `MT5_{LOGIN,PASSWORD,SERVER,PATH}`,
and optionally `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `HEALTHCHECK_URL`. Then:

```powershell
uv sync --extra live
.\scripts\run_live.ps1 -Mode paper
```

## Known risks to check before trusting any result

- **The stop cap may starve the strategy of trades.** SPEC step 4 skips any
  breakout whose range-based stop is wider than 1.5 × ATR(14, 15m). Asian
  ranges are often wider than that, so the ≥ 500-trade OOS gate may fail. If
  it does, the SPEC says to try a different strategy family, not to loosen the cap.
- **Historical news.** Forex Factory publishes only the current week. Without
  a historical events CSV (`--news-csv`), the backtest's news filter does
  nothing and the report warns about it.
- **Values marked VERIFY** in `config/ftmo_2step.yaml` (NAS100 contract size
  and symbol name, metal and index commissions, typical spreads, server
  timezone, challenge fee) must be checked on the FTMO demo before the gates mean anything.
- **Overall-loss modelling.** Overall loss depends on the challenge start date.
  The continuous backtest enforces daily limits tick by tick, and `ftmo_sim`
  replays the 6% and 10% overall limits for every rolling start date.
