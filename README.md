# Trading-bot 2.0

A systematic trading engine built to falsify its own strategy — and which did.

**Phase 4 verdict: [DO NOT DEPLOY the dual-momentum strategy](docs/PHASE_4_REPORT.md).**
On 2015–2026 data with real per-order costs, it loses to buy-and-hold DCA on
risk-adjusted terms in every sub-period, and showed no 2008 crash protection on
the long-history proxy. The engine, tests, and paper-mode automation remain —
they faithfully execute whatever the config says, including the boring static
allocation the evidence actually supports.

## What's here

| | |
|---|---|
| `docs/PHASE_0-2_REPORT.md` | Asset class derived from capital ($100/wk, Canada), venue research, strategy evidence |
| `docs/PHASE_4_RESULTS.md` / `PHASE_4_REPORT.md` | Measurements and the verdict |
| `engine/` | Backtester (t+1 lag, shared live code path), risk layer with structural veto, atomic state, per-order cost model, execution sequencing |
| `config/engine.toml` | Every limit and threshold. Tests read from here — retuning a limit cannot silently disable its test |
| `tests/` | 81 tests: invariants (incl. bit-identical lookahead test), 11 named failure-mode regressions + 16 audit-round regressions, synthetic suite |
| `tools/mutation_test.py` | 24 safety mutations, each must be detected by a failing test |
| `scripts/daily_run.py` + `.github/workflows/paper.yml` | Daily **paper-mode** cycle on GitHub Actions (no credentials exist or are needed) |

## What this system CANNOT do

- **It cannot beat buy-and-hold.** That is the measured result, not modesty.
- **It cannot trade live.** There is no live-execution code path (Phase 5 was
  gated on a Phase 4 pass and was never built). Making it trade live requires a
  deliberate separate build, separate credentials, and a strategy that first
  survives falsification.
- **It cannot protect against a crash faster than its decision cadence.**
  Monthly decisions mean up to a month of full exposure to anything the market
  does in between; the hard-kill liquidation also fills a bar later, not
  instantly.
- **It cannot recover itself after a hard kill.** By design: a fired kill
  switch stays fired until a human inspects and clears state (§7).
- **It cannot trade through bad data.** A missing, stale, or NaN price for any
  held or universe symbol refuses the whole cycle. This is a feature.
- **It does not model taxes**, currency conversion beyond avoiding it
  (CAD-listed universe), or venue-specific order-book microstructure beyond
  spread + slippage per order.

## When to STOP using it

- The paper account hits the configured max drawdown or the daily job reports
  HALTED — investigate; do not just reset state.
- Reports show repeated `⚠ data refusals` — the data source has rotted.
- Fees observed at the venue differ from `config/engine.toml` — re-verify the
  schedule; every backtest number depends on it.
- You feel the urge to tune parameters until results look better. §10. Stop.

## Running

```
pip install numpy pandas pytest
python -m pytest tests -q          # must be green before anything else matters
python tools/mutation_test.py      # every safety fix must be detected
python scripts/phase4_backtest.py  # reproduce the measurements (data/ in repo)
```
