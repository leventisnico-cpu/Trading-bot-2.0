# Mini-Prop OS validation scorecard

Generated: 2026-09-15 15:06 UTC

**61/61 checks passed (100.0%) — PASS (gate: >= 75%)**

Simulation: real RiskGuardrails + OMS + EmaCrossoverStrategy, simulated broker (fills at next bar open, 1 tick adverse slippage, $0.62/side commission, partial fills on 2+ units). Historical data: SPY daily adjusted closes (data/prices_us.csv) x10 as an S&P-index/MES proxy, 1 contract, $5 multiplier.

## Checks

- [PASS] lifecycle: exactly one entry and one exit order — [('BUY', 1), ('SELL', 1)]
- [PASS] lifecycle: golden cross entered long — max position 1
- [PASS] lifecycle: death cross exited to flat — final 0, 1 trips
- [PASS] lifecycle: round trip captured most of the up-trend — pnl ['1212']
- [PASS] lifecycle: never short (long-only enforced) — min position 0
- [PASS] lifecycle: position cap never exceeded — max 1 <= 4
- [PASS] lifecycle: order-size cap never exceeded — max order 1
- [PASS] lifecycle: no strategy orders after kill switch — 0 leaked
- [PASS] lifecycle: accounting reconciles (OMS ledger vs raw fills) — error $0.0000
- [PASS] lifecycle: no working orders left at shutdown — 0 open
- [PASS] warmup: zero orders before warmup completes — 0 orders
- [PASS] partials: 2+ unit orders filled via partial fills — 2 filled orders
- [PASS] partials: every filled order completed exactly
- [PASS] partials: accounting reconciles with split fills — error $0.0000
- [PASS] partials: position returned to flat
- [PASS] kill switch: tripped on crash day — daily loss 2700.00 breached limit 1000.00 (start 102038.13 -> 99338.13)
- [PASS] kill switch: book flattened after trip — position after kill 0
- [PASS] kill switch: stays latched (no re-entry on later signal) — active=True
- [PASS] kill switch: no strategy orders leaked past it
- [PASS] hygiene: duplicate exec id + unknown-order fill ignored — {'MES': 1} -> {'MES': 1}
- [PASS] hygiene: corrupt OHLC bar is rejected at construction
- [PASS] hygiene: risk-rejected intents never reach the broker — 0 rejections
- [PASS] config: shipped config.yaml loads
- [PASS] config: paper port configured — port 7497
- [PASS] config: order size fits within risk caps
- [PASS] GFC 2007-2009: never short (long-only enforced) — min position 0
- [PASS] GFC 2007-2009: position cap never exceeded — max 1 <= 4
- [PASS] GFC 2007-2009: order-size cap never exceeded — max order 1
- [PASS] GFC 2007-2009: no strategy orders after kill switch — 0 leaked
- [PASS] GFC 2007-2009: accounting reconciles (OMS ledger vs raw fills) — error $0.0000
- [PASS] GFC 2007-2009: no working orders left at shutdown — 0 open
- [PASS] recovery 2010-2014: never short (long-only enforced) — min position 0
- [PASS] recovery 2010-2014: position cap never exceeded — max 1 <= 4
- [PASS] recovery 2010-2014: order-size cap never exceeded — max order 1
- [PASS] recovery 2010-2014: no strategy orders after kill switch — 0 leaked
- [PASS] recovery 2010-2014: accounting reconciles (OMS ledger vs raw fills) — error $0.0000
- [PASS] recovery 2010-2014: no working orders left at shutdown — 0 open
- [PASS] bull 2015-2019: never short (long-only enforced) — min position 0
- [PASS] bull 2015-2019: position cap never exceeded — max 1 <= 4
- [PASS] bull 2015-2019: order-size cap never exceeded — max order 1
- [PASS] bull 2015-2019: no strategy orders after kill switch — 0 leaked
- [PASS] bull 2015-2019: accounting reconciles (OMS ledger vs raw fills) — error $0.0000
- [PASS] bull 2015-2019: no working orders left at shutdown — 0 open
- [PASS] COVID 2020-2021: never short (long-only enforced) — min position 0
- [PASS] COVID 2020-2021: position cap never exceeded — max 1 <= 4
- [PASS] COVID 2020-2021: order-size cap never exceeded — max order 1
- [PASS] COVID 2020-2021: no strategy orders after kill switch — 0 leaked
- [PASS] COVID 2020-2021: accounting reconciles (OMS ledger vs raw fills) — error $0.0000
- [PASS] COVID 2020-2021: no working orders left at shutdown — 0 open
- [PASS] bear 2022: never short (long-only enforced) — min position 0
- [PASS] bear 2022: position cap never exceeded — max 1 <= 4
- [PASS] bear 2022: order-size cap never exceeded — max order 1
- [PASS] bear 2022: no strategy orders after kill switch — 0 leaked
- [PASS] bear 2022: accounting reconciles (OMS ledger vs raw fills) — error $0.0000
- [PASS] bear 2022: no working orders left at shutdown — 0 open
- [PASS] recent 2023-2026: never short (long-only enforced) — min position 0
- [PASS] recent 2023-2026: position cap never exceeded — max 1 <= 4
- [PASS] recent 2023-2026: order-size cap never exceeded — max order 1
- [PASS] recent 2023-2026: no strategy orders after kill switch — 0 leaked
- [PASS] recent 2023-2026: accounting reconciles (OMS ledger vs raw fills) — error $0.0000
- [PASS] recent 2023-2026: no working orders left at shutdown — 0 open

## Strategy performance (reported as measured, not a gate)

| period | bars | round trips | win rate | net PnL ($) | max DD ($) | kill switch |
|---|---|---|---|---|---|---|
| GFC 2007-2009 | 756 | 16 | 25% | -603 | 1,531 | no |
| recovery 2010-2014 | 1258 | 22 | 55% | +2,021 | 594 | no |
| bull 2015-2019 | 1258 | 26 | 38% | +2,305 | 1,953 | no |
| COVID 2020-2021 | 505 | 5 | 80% | +6,457 | 1,705 | no |
| bear 2022 | 251 | 3 | 67% | -821 | 2,158 | no |
| recent 2023-2026 | 917 | 14 | 36% | +10,572 | 2,373 | no |

Win rates for a trend-following crossover are typically well below 50% (few large winners pay for many small losers); the 75% gate applies to the system-behavior checks above, and no strategy metric here is evidence of live edge (see the repo's Phase 4 verdict).
