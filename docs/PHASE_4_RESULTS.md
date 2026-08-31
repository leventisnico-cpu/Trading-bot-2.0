# Phase 4 Results — measured, not tuned

CAD universe: ['XUU.TO', 'XEF.TO', 'XEC.TO', 'XIC.TO', 'ZAG.TO'], 2015-02-20 → 2026-08-28 (2892 bars). Adjusted closes (distributions reinvested). Costs: fixed_per_order, min 1.0 CAD/order, spread 10.0bps, slippage 2.0bps, all per order (§6).

## 1. The actual deployment: $0 start, $100/week

| config | CAGR (TWR) | vol | Sharpe | maxDD | fees paid | fee drag/yr | final $ |
|---|---|---|---|---|---|---|---|
| dual momentum 12-1 | 0.00% | 0.00% | nan | 0.00% | 0 | 0.00% | 52,700 |
| buy-and-hold DCA 100% US equity | 0.00% | 0.00% | nan | 0.00% | 0 | 0.00% | 52,700 |
| buy-and-hold DCA 60/40 | 0.00% | 0.00% | nan | 0.00% | 0 | 0.00% | 52,700 |

## 2. Net return by account size (no contributions)

| config | CAGR (TWR) | vol | Sharpe | maxDD | fees paid | fee drag/yr | final $ |
|---|---|---|---|---|---|---|---|
| $1,000 | 8.39% | 15.60% | 0.59 | -28.18% | 119 | 0.72% | 2,520 |
| $2,500 | 8.65% | 15.69% | 0.61 | -28.21% | 233 | 0.56% | 6,474 |
| $5,000 | 8.67% | 15.70% | 0.61 | -28.18% | 466 | 0.55% | 12,985 |
| $10,000 | 8.68% | 15.71% | 0.61 | -28.17% | 934 | 0.55% | 25,996 |
| $25,000 | 8.69% | 15.73% | 0.61 | -28.22% | 2,337 | 0.56% | 65,028 |
| $100,000 | 8.69% | 15.73% | 0.61 | -28.21% | 9,352 | 0.56% | 260,137 |

## 3. Cost sensitivity ($5,000 start, no contributions)

| config | CAGR (TWR) | vol | Sharpe | maxDD | fees paid | fee drag/yr | final $ |
|---|---|---|---|---|---|---|---|
| commission x0.0 | 8.87% | 15.68% | 0.62 | -28.11% | 322 | 0.38% | 13,249 |
| commission x0.5 | 8.77% | 15.70% | 0.61 | -28.20% | 395 | 0.47% | 13,112 |
| commission x1.0 | 8.67% | 15.70% | 0.61 | -28.18% | 466 | 0.55% | 12,985 |
| commission x2.0 | 8.49% | 15.69% | 0.60 | -28.14% | 607 | 0.73% | 12,729 |
| commission x4.0 | 8.12% | 15.71% | 0.58 | -28.17% | 880 | 1.08% | 12,243 |
| spread 5bps | 8.81% | 15.70% | 0.62 | -28.19% | 355 | 0.42% | 13,167 |
| spread 20bps | 8.40% | 15.69% | 0.59 | -28.15% | 683 | 0.82% | 12,611 |
| spread 40bps | 7.89% | 15.73% | 0.56 | -28.20% | 1,097 | 1.36% | 11,944 |

## 4. Parameter sensitivity ($5,000, no contributions) — robustness check, not a menu (§10)

| lookback | skip | top_n | CAGR | Sharpe | maxDD |
|---|---|---|---|---|---|
| 3 | 0 | 1 | 8.02% | 0.61 | -26.18% |
| 3 | 0 | 2 | 8.14% | 0.71 | -20.82% |
| 3 | 1 | 1 | 9.96% | 0.70 | -27.23% |
| 3 | 1 | 2 | 7.39% | 0.59 | -32.31% |
| 6 | 0 | 1 | 4.21% | 0.35 | -28.65% |
| 6 | 0 | 2 | 8.19% | 0.67 | -27.29% |
| 6 | 1 | 1 | 8.59% | 0.60 | -27.97% |
| 6 | 1 | 2 | 8.09% | 0.64 | -33.07% |
| 9 | 0 | 1 | 7.65% | 0.56 | -28.19% |
| 9 | 0 | 2 | 8.57% | 0.67 | -32.41% |
| 9 | 1 | 1 | 7.58% | 0.54 | -28.00% |
| 9 | 1 | 2 | 9.07% | 0.69 | -32.46% |
| 12 | 0 | 1 | 9.30% | 0.67 | -28.12% |
| 12 | 0 | 2 | 8.97% | 0.71 | -32.41% |
| 12 | 1 | 1 | 8.67% | 0.61 | -28.18% |
| 12 | 1 | 2 | 9.55% | 0.74 | -31.50% |

grid Sharpe: median 0.65, min 0.35, max 0.74; chosen (12-1, top1): 0.61

## 5. Performance by fold (single run, sliced — no resets)

| fold | period | strategy Sharpe | 60/40 Sharpe | strategy maxDD |
|---|---|---|---|---|
| 1 | 2015-02-20 → 2018-12-20 | 0.32 | 0.62 | -18.68% |
| 2 | 2018-12-21 → 2022-10-26 | 0.40 | 0.65 | -28.18% |
| 3 | 2022-10-27 → 2026-08-28 | 1.12 | 1.49 | -19.66% |

## 6. Long-history US proxy (SPY/EFA/EEM, AGG defensive; approximate USD 1 min commission)

| config | CAGR (TWR) | vol | Sharpe | maxDD | fees paid | fee drag/yr | final $ |
|---|---|---|---|---|---|---|---|
| dual momentum 12-1 (US) | 10.74% | 19.61% | 0.62 | -37.12% | 1,619 | 0.37% | 51,589 |
| 60/40 SPY/AGG | 8.10% | 10.97% | 0.76 | -35.26% | 76 | 0.03% | 29,674 |

2007-10 → 2009-06: strategy maxDD -37.12% vs 60/40 maxDD -35.26%

## Flags

- none raised by the automated checks

*(Verdict is written separately in docs/PHASE_4_REPORT.md after human review of these numbers — this file is measurements only.)*
