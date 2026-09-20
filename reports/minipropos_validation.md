# Mini-Prop OS validation scorecard

Generated: 2026-09-20 20:07 UTC

**138/138 checks passed (100.0%) — PASS (gate: >= 75%)**

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
- [PASS] whipsaw: baseline demonstrably whipsaws in chop — baseline entries 57
- [PASS] whipsaw: adaptive filter cuts entries vs baseline — 0 vs 57
- [PASS] whipsaw: adaptive loses less than baseline in chop — adaptive +0 vs baseline -14103
- [PASS] whipsaw-adaptive: never short (long-only enforced) — min position 0
- [PASS] whipsaw-adaptive: position cap never exceeded — max 0 <= 4
- [PASS] whipsaw-adaptive: order-size cap never exceeded — max order 0
- [PASS] whipsaw-adaptive: no strategy orders after kill switch — 0 leaked
- [PASS] whipsaw-adaptive: accounting reconciles (OMS ledger vs raw fills) — error $0.0000
- [PASS] whipsaw-adaptive: no working orders left at shutdown — 0 open
- [PASS] flash crash: strategy was long before the crash — max position 2
- [PASS] flash crash: EXTREME regime flagged during the crash — regimes ['EXTREME', 'EXTREME', 'EXTREME', 'EXTREME', 'EXTREME', 'EXTREME', 'EXTREME', 'EXTREME']
- [PASS] flash crash: strategy went flat and stayed flat — final 0, 0 re-entries
- [PASS] flash crash: accounting reconciles through the crash — error $0.0000
- [PASS] sizing: calm-regime entry uses base size — quantities [2]
- [PASS] sizing: high-vol entry is cut to half size — quantities [1]
- [PASS] learning: sawtooth produced losing round trips to learn from — 5 losses / 6 trips
- [PASS] learning: entry thresholds tightened after losses — {'LOW': 0.05, 'NORMAL': 0.55, 'HIGH': 0.35}
- [PASS] learning: thresholds stay hard-bounded
- [PASS] vol-target: quiet market takes a larger position — 10 vs 2 contracts
- [PASS] vol-target: dollar risk stays within budget in both regimes — calm $1,732, loud $1,360 (budget $2,000)
- [PASS] vol-target: risk is far more uniform than fixed sizing — sized spread $372 vs unsized $5,068
- [PASS] vol-target: fixed sizing would have blown the budget — $6,800 at 10 contracts
- [PASS] vol-target: never sizes above the configured base — max 10 <= 10
- [PASS] blackout: active during the release window — window +/-15min around 12:30
- [PASS] blackout: names the event responsible
- [PASS] blackout: risk-flattening is never an entry
- [PASS] blackout: empty calendar never suppresses anything
- [PASS] ensemble: unanimity is never looser than a single signal — 0 entries under 2-of-2 agreement
- [PASS] ensemble: warmup waits for the slowest member — 120 bars
- [PASS] ensemble: size is the most conservative member proposal — min() of agreeing members
- [PASS] statistics: best of 200 noise trials looks good naively — naive PSR 0.990 (the trap)
- [PASS] statistics: deflation rejects that same noise — DSR 0.322
- [PASS] statistics: a genuinely strong signal still survives — DSR 1.000
- [PASS] statistics: a flat equity curve is not infinitely good — guards against divide-by-residue
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
- [PASS] stress GFC autumn 2008 (adaptive): never short (long-only enforced) — min position 0
- [PASS] stress GFC autumn 2008 (adaptive): position cap never exceeded — max 2 <= 4
- [PASS] stress GFC autumn 2008 (adaptive): order-size cap never exceeded — max order 2
- [PASS] stress GFC autumn 2008 (adaptive): no strategy orders after kill switch — 0 leaked
- [PASS] stress GFC autumn 2008 (adaptive): accounting reconciles (OMS ledger vs raw fills) — error $0.0000
- [PASS] stress GFC autumn 2008 (adaptive): no working orders left at shutdown — 0 open
- [PASS] stress GFC autumn 2008: adaptive does not materially worsen drawdown — 667 vs 1,028
- [PASS] stress euro crisis 2011 (adaptive): never short (long-only enforced) — min position 0
- [PASS] stress euro crisis 2011 (adaptive): position cap never exceeded — max 2 <= 4
- [PASS] stress euro crisis 2011 (adaptive): order-size cap never exceeded — max order 2
- [PASS] stress euro crisis 2011 (adaptive): no strategy orders after kill switch — 0 leaked
- [PASS] stress euro crisis 2011 (adaptive): accounting reconciles (OMS ledger vs raw fills) — error $0.0000
- [PASS] stress euro crisis 2011 (adaptive): no working orders left at shutdown — 0 open
- [PASS] stress euro crisis 2011: adaptive does not materially worsen drawdown — 385 vs 942
- [PASS] stress yuan shock 2015 (adaptive): never short (long-only enforced) — min position 0
- [PASS] stress yuan shock 2015 (adaptive): position cap never exceeded — max 0 <= 4
- [PASS] stress yuan shock 2015 (adaptive): order-size cap never exceeded — max order 0
- [PASS] stress yuan shock 2015 (adaptive): no strategy orders after kill switch — 0 leaked
- [PASS] stress yuan shock 2015 (adaptive): accounting reconciles (OMS ledger vs raw fills) — error $0.0000
- [PASS] stress yuan shock 2015 (adaptive): no working orders left at shutdown — 0 open
- [PASS] stress yuan shock 2015: adaptive does not materially worsen drawdown — 0 vs 187
- [PASS] stress volmageddon+Q4 2018 (adaptive): never short (long-only enforced) — min position 0
- [PASS] stress volmageddon+Q4 2018 (adaptive): position cap never exceeded — max 2 <= 4
- [PASS] stress volmageddon+Q4 2018 (adaptive): order-size cap never exceeded — max order 2
- [PASS] stress volmageddon+Q4 2018 (adaptive): no strategy orders after kill switch — 0 leaked
- [PASS] stress volmageddon+Q4 2018 (adaptive): accounting reconciles (OMS ledger vs raw fills) — error $0.0000
- [PASS] stress volmageddon+Q4 2018 (adaptive): no working orders left at shutdown — 0 open
- [PASS] stress volmageddon+Q4 2018: adaptive does not materially worsen drawdown — 1,284 vs 1,284
- [PASS] stress COVID crash 2020 (adaptive): never short (long-only enforced) — min position 0
- [PASS] stress COVID crash 2020 (adaptive): position cap never exceeded — max 0 <= 4
- [PASS] stress COVID crash 2020 (adaptive): order-size cap never exceeded — max order 0
- [PASS] stress COVID crash 2020 (adaptive): no strategy orders after kill switch — 0 leaked
- [PASS] stress COVID crash 2020 (adaptive): accounting reconciles (OMS ledger vs raw fills) — error $0.0000
- [PASS] stress COVID crash 2020 (adaptive): no working orders left at shutdown — 0 open
- [PASS] stress COVID crash 2020: adaptive does not materially worsen drawdown — 0 vs 2,075
- [PASS] stress bear market 2022 (adaptive): never short (long-only enforced) — min position 0
- [PASS] stress bear market 2022 (adaptive): position cap never exceeded — max 2 <= 4
- [PASS] stress bear market 2022 (adaptive): order-size cap never exceeded — max order 2
- [PASS] stress bear market 2022 (adaptive): no strategy orders after kill switch — 0 leaked
- [PASS] stress bear market 2022 (adaptive): accounting reconciles (OMS ledger vs raw fills) — error $0.0000
- [PASS] stress bear market 2022 (adaptive): no working orders left at shutdown — 0 open
- [PASS] stress bear market 2022: adaptive does not materially worsen drawdown — 2,457 vs 2,453
- [PASS] stress aggregate: adaptive cuts combined drawdown across all high-vol windows — $4,793 vs $7,969

## Strategy performance (reported as measured, not a gate)

Baseline ema_crossover across full regimes:

| period | bars | round trips | win rate | net PnL ($) | max DD ($) | kill switch |
|---|---|---|---|---|---|---|
| GFC 2007-2009 | 756 | 16 | 25% | -603 | 1,531 | no |
| recovery 2010-2014 | 1258 | 22 | 55% | +2,021 | 594 | no |
| bull 2015-2019 | 1258 | 26 | 38% | +2,305 | 1,953 | no |
| COVID 2020-2021 | 505 | 5 | 80% | +6,457 | 1,705 | no |
| bear 2022 | 251 | 3 | 67% | -821 | 2,158 | no |
| recent 2023-2026 | 917 | 14 | 36% | +10,572 | 2,373 | no |

High-volatility stress windows, baseline vs volatility-adaptive (regime sizing + EXTREME risk-off + confirmed entries + bounded online threshold learning):

| window | strategy | round trips | win rate | net PnL ($) | max DD ($) | kill switch |
|---|---|---|---|---|---|---|
| GFC autumn 2008 | baseline | 3 | 0% | -822 | 1,028 | no |
| GFC autumn 2008 | adaptive | 1 | 0% | -232 | 667 | no |
| euro crisis 2011 | baseline | 2 | 0% | -111 | 942 | no |
| euro crisis 2011 | adaptive | 1 | 0% | -291 | 385 | no |
| yuan shock 2015 | baseline | 0 | - | +710 | 187 | no |
| yuan shock 2015 | adaptive | 0 | - | +0 | 0 | no |
| volmageddon+Q4 2018 | baseline | 4 | 50% | -400 | 1,284 | no |
| volmageddon+Q4 2018 | adaptive | 2 | 50% | +100 | 1,284 | no |
| COVID crash 2020 | baseline | 1 | 100% | +2,048 | 2,075 | TRIPPED |
| COVID crash 2020 | adaptive | 0 | - | +0 | 0 | no |
| bear market 2022 | baseline | 1 | 0% | -1,965 | 2,453 | TRIPPED |
| bear market 2022 | adaptive | 1 | 0% | -2,457 | 2,457 | TRIPPED |

Win rates for a trend-following crossover are typically well below 50% (few large winners pay for many small losers); the 75% gate applies to the system-behavior checks above, and no strategy metric here is evidence of live edge (see the repo's Phase 4 verdict).
