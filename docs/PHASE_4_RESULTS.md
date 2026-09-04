# Phase 4 Results — measured, not tuned

CAD universe: ['XUU.TO', 'XEF.TO', 'XEC.TO', 'XIC.TO', 'ZAG.TO'], 2015-02-20 → 2026-08-28 (2892 bars). Adjusted closes (distributions reinvested). Costs: fixed_per_order, min 1.0 CAD/order, spread 10.0bps, slippage 2.0bps, all per order (§6).

## 1. The actual deployment: $0 start, $100/week

| config | CAGR (TWR) | vol | Sharpe | maxDD | fees paid | fee drag/yr | final $ |
|---|---|---|---|---|---|---|---|
| dual momentum 12-1 | 7.98% | 15.20% | 0.58 | -27.44% | 2,248 | 0.58% | 92,762 |
| buy-and-hold DCA 100% US equity | 13.67% | 15.93% | 0.88 | -27.51% | 90 | 0.02% | 134,586 |
| buy-and-hold DCA 60/40 | 8.58% | 10.21% | 0.86 | -20.01% | 119 | 0.03% | 94,699 |

## 2. Net return by account size (no contributions)

| config | CAGR (TWR) | vol | Sharpe | maxDD | fees paid | fee drag/yr | final $ |
|---|---|---|---|---|---|---|---|
| $1,000 | 7.70% | 15.30% | 0.56 | -28.41% | 146 | 0.90% | 2,342 |
| $2,500 | 7.98% | 15.45% | 0.57 | -28.39% | 286 | 0.69% | 6,030 |
| $5,000 | 7.99% | 15.47% | 0.57 | -28.39% | 572 | 0.69% | 12,078 |
| $10,000 | 7.99% | 15.48% | 0.57 | -28.44% | 1,146 | 0.69% | 24,165 |
| $25,000 | 8.00% | 15.49% | 0.57 | -28.45% | 2,867 | 0.69% | 60,464 |
| $100,000 | 8.00% | 15.50% | 0.57 | -28.46% | 11,473 | 0.69% | 241,910 |

## 3. Cost sensitivity ($5,000 start, no contributions)

| config | CAGR (TWR) | vol | Sharpe | maxDD | fees paid | fee drag/yr | final $ |
|---|---|---|---|---|---|---|---|
| commission x0.0 | 8.27% | 15.46% | 0.59 | -28.19% | 371 | 0.44% | 12,444 |
| commission x0.5 | 8.14% | 15.45% | 0.58 | -28.15% | 473 | 0.57% | 12,266 |
| commission x1.0 | 7.99% | 15.47% | 0.57 | -28.39% | 572 | 0.69% | 12,078 |
| commission x2.0 | 7.69% | 15.47% | 0.56 | -28.85% | 766 | 0.95% | 11,692 |
| commission x4.0 | 7.12% | 15.50% | 0.52 | -29.68% | 1,135 | 1.46% | 11,002 |
| spread 5bps | 8.16% | 15.45% | 0.59 | -28.15% | 447 | 0.53% | 12,298 |
| spread 20bps | 7.65% | 15.48% | 0.55 | -28.85% | 816 | 1.01% | 11,652 |
| spread 40bps | 6.95% | 15.48% | 0.51 | -29.66% | 1,274 | 1.65% | 10,803 |

## 4. Parameter sensitivity ($5,000, no contributions) — robustness check, not a menu (§10)

| lookback | skip | top_n | CAGR | Sharpe | maxDD |
|---|---|---|---|---|---|
| 3 | 0 | 1 | 8.02% | 0.61 | -26.18% |
| 3 | 0 | 2 | 8.14% | 0.71 | -20.82% |
| 3 | 1 | 1 | 6.20% | 0.47 | -27.18% |
| 3 | 1 | 2 | 4.44% | 0.39 | -32.31% |
| 6 | 0 | 1 | 4.21% | 0.35 | -28.65% |
| 6 | 0 | 2 | 8.19% | 0.67 | -27.29% |
| 6 | 1 | 1 | 6.08% | 0.45 | -27.23% |
| 6 | 1 | 2 | 8.05% | 0.64 | -27.22% |
| 9 | 0 | 1 | 7.65% | 0.56 | -28.19% |
| 9 | 0 | 2 | 8.57% | 0.67 | -32.41% |
| 9 | 1 | 1 | 6.58% | 0.49 | -28.13% |
| 9 | 1 | 2 | 8.32% | 0.65 | -32.54% |
| 12 | 0 | 1 | 9.30% | 0.67 | -28.12% |
| 12 | 0 | 2 | 8.97% | 0.71 | -32.41% |
| 12 | 1 | 1 | 7.99% | 0.57 | -28.39% |
| 12 | 1 | 2 | 9.13% | 0.70 | -33.10% |

grid Sharpe: median 0.63, min 0.35, max 0.71; chosen (12-1, top1): 0.57

## 5. Performance by fold (single run, sliced — no resets)

| fold | period | strategy Sharpe | 60/40 Sharpe | strategy maxDD |
|---|---|---|---|---|
| 1 | 2015-02-20 → 2018-12-20 | 0.42 | 0.62 | -18.68% |
| 2 | 2018-12-21 → 2022-10-26 | 0.30 | 0.66 | -28.14% |
| 3 | 2022-10-27 → 2026-08-28 | 1.09 | 1.49 | -19.66% |

## 6. Long-history US proxy (SPY/EFA/EEM, AGG defensive; approximate USD 1 min commission)

| config | CAGR (TWR) | vol | Sharpe | maxDD | fees paid | fee drag/yr | final $ |
|---|---|---|---|---|---|---|---|
| dual momentum 12-1 (US) ⚠HALTED | 2.51% | 11.05% | 0.28 | -35.02% | 105 | 0.05% | 8,823 |
| 60/40 SPY/AGG ⚠HALTED | -0.21% | 6.18% | -0.00 | -35.26% | 25 | 0.02% | 4,760 |

2007-10 → 2009-06: strategy maxDD -35.02% vs 60/40 maxDD -35.26%

## Flags

- none raised by the automated checks

*(Verdict is written separately in docs/PHASE_4_REPORT.md after human review of these numbers — this file is measurements only.)*
