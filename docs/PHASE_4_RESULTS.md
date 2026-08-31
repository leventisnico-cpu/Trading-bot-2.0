# Phase 4 Results — measured, not tuned

CAD universe: ['XUU.TO', 'XEF.TO', 'XEC.TO', 'XIC.TO', 'ZAG.TO'], 2015-02-02 → 2025-10-24 (2800 bars). Adjusted closes (distributions reinvested). Costs: fixed_per_order, min 1.0 CAD/order, spread 10.0bps, slippage 2.0bps, all per order (§6).

## 1. The actual deployment: $0 start, $100/week

| config | CAGR (TWR) | vol | Sharpe | maxDD | fees paid | fee drag/yr | final $ |
|---|---|---|---|---|---|---|---|
| dual momentum 12-1 | 17.37% | 16.25% | 1.07 | -25.77% | 1,692 | 0.26% | 199,041 |
| buy-and-hold DCA 100% US equity | 1.17% | 16.74% | 0.15 | -48.50% | 105 | 0.03% | 82,876 |
| buy-and-hold DCA 60/40 | 8.44% | 12.24% | 0.72 | -33.79% | 165 | 0.03% | 117,440 |

## 2. Net return by account size (no contributions)

| config | CAGR (TWR) | vol | Sharpe | maxDD | fees paid | fee drag/yr | final $ |
|---|---|---|---|---|---|---|---|
| $1,000 | 16.86% | 15.64% | 1.07 | -25.22% | 86 | 0.35% | 5,644 |
| $2,500 | 17.51% | 16.38% | 1.07 | -26.51% | 174 | 0.27% | 15,013 |
| $5,000 | 17.60% | 16.46% | 1.07 | -26.47% | 320 | 0.25% | 30,266 |
| $10,000 | 17.55% | 16.47% | 1.06 | -26.53% | 617 | 0.24% | 60,273 |
| $25,000 | 17.64% | 16.53% | 1.07 | -26.52% | 1,545 | 0.24% | 151,975 |
| $100,000 | 17.65% | 16.55% | 1.07 | -26.59% | 6,183 | 0.24% | 607,967 |

## 3. Cost sensitivity ($5,000 start, no contributions)

| config | CAGR (TWR) | vol | Sharpe | maxDD | fees paid | fee drag/yr | final $ |
|---|---|---|---|---|---|---|---|
| commission x0.0 | 17.61% | 16.43% | 1.07 | -26.31% | 280 | 0.22% | 30,307 |
| commission x0.5 | 17.61% | 16.44% | 1.07 | -26.37% | 300 | 0.24% | 30,286 |
| commission x1.0 | 17.60% | 16.46% | 1.07 | -26.47% | 320 | 0.25% | 30,266 |
| commission x2.0 | 17.43% | 16.40% | 1.06 | -26.64% | 356 | 0.28% | 29,777 |
| commission x4.0 | 17.40% | 16.46% | 1.06 | -27.05% | 437 | 0.35% | 29,695 |
| spread 5bps | 17.64% | 16.42% | 1.07 | -26.27% | 221 | 0.17% | 30,372 |
| spread 20bps | 17.29% | 16.40% | 1.05 | -26.94% | 510 | 0.41% | 29,400 |
| spread 40bps | 16.86% | 16.39% | 1.03 | -27.83% | 879 | 0.72% | 28,218 |

## 4. Parameter sensitivity ($5,000, no contributions) — robustness check, not a menu (§10)

| lookback | skip | top_n | CAGR | Sharpe | maxDD |
|---|---|---|---|---|---|
| 3 | 0 | 1 | 15.47% | 0.93 | -26.34% |
| 3 | 0 | 2 | 10.12% | 0.87 | -18.50% |
| 3 | 1 | 1 | 16.14% | 0.96 | -20.70% |
| 3 | 1 | 2 | 11.46% | 0.98 | -24.43% |
| 6 | 0 | 1 | 13.39% | 0.83 | -24.75% |
| 6 | 0 | 2 | 10.31% | 0.90 | -22.83% |
| 6 | 1 | 1 | 8.29% | 0.56 | -34.16% |
| 6 | 1 | 2 | 13.95% | 1.18 | -22.35% |
| 9 | 0 | 1 | 15.94% | 0.98 | -32.87% |
| 9 | 0 | 2 | 12.11% | 1.07 | -21.68% |
| 9 | 1 | 1 | 14.93% | 0.92 | -33.84% |
| 9 | 1 | 2 | 13.16% | 1.15 | -17.76% |
| 12 | 0 | 1 | 21.93% | 1.28 | -18.25% |
| 12 | 0 | 2 | 17.04% | 1.43 | -19.26% |
| 12 | 1 | 1 | 17.60% | 1.07 | -26.47% |
| 12 | 1 | 2 | 14.39% | 1.24 | -19.24% |

grid Sharpe: median 0.98, min 0.56, max 1.43; chosen (12-1, top1): 1.07

## 5. Performance by fold (single run, sliced — no resets)

| fold | period | strategy Sharpe | 60/40 Sharpe | strategy maxDD |
|---|---|---|---|---|
| 1 | 2015-02-02 → 2018-08-29 | 0.23 | -0.12 | -26.47% |
| 2 | 2018-08-30 → 2022-03-28 | 1.59 | 1.07 | -15.91% |
| 3 | 2022-03-29 → 2025-10-24 | 1.20 | 1.14 | -19.00% |

## 6. Long-history US proxy (SPY/EFA/EEM, AGG defensive; approximate USD 1 min commission)

| config | CAGR (TWR) | vol | Sharpe | maxDD | fees paid | fee drag/yr | final $ |
|---|---|---|---|---|---|---|---|
| dual momentum 12-1 (US) | -0.98% | 7.20% | -0.10 | -38.14% | 106 | 0.11% | 4,013 |
| 60/40 SPY/AGG | 9.47% | 12.26% | 0.80 | -25.39% | 133 | 0.04% | 37,314 |

2007-10 → 2009-06: strategy maxDD -29.19% vs 60/40 maxDD -10.49%

## Flags

- none raised by the automated checks

*(Verdict is written separately in docs/PHASE_4_REPORT.md after human review of these numbers — this file is measurements only.)*
