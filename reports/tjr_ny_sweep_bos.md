# TJR NY-session sweep + BOS — gate results

Rules: `research/tjr_ny_sweep_bos.md` (pre-registered). Costs: IBKR $0.005/share, $1.00 min per order, 1 cent slippage on stop/time exits. 5-minute regular-hours bars from Astral. Scored with `scripts/expectancy.py`'s rule.

## SPY — A two-sided, $10,000

| window | final $ | return | maxDD | gain/DD | trades | win% | B&H final $ | B&H return | B&H maxDD | B&H gain/DD | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| fold 1/3 | 10,030 | +0.3% | 0.0% | 3.00 | 2 | 100.0% | 10,774 | +7.7% | 17.8% | 0.39 | no |
| fold 2/3 | 9,906 | -0.9% | 0.9% | -1.00 | 7 | 14.3% | 11,616 | +16.2% | 4.8% | 2.91 | no |
| fold 3/3 | 9,987 | -0.1% | 0.2% | -0.61 | 2 | 50.0% | 11,028 | +10.3% | 8.2% | 1.25 | no |
| full sample | 9,923 | -0.8% | 1.1% | -0.72 | 11 | 36.4% | 13,755 | +37.5% | 17.8% | 1.90 | no |

Full sample: 11 trades on 516 days, avg -0.23R, profit factor 0.37, commissions $22, exits: target 2, stop 7, time 2.

Gate: passes 0/3 folds, full sample no → **FAIL**

## SPY — B long-only (TFSA), $10,000

| window | final $ | return | maxDD | gain/DD | trades | win% | B&H final $ | B&H return | B&H maxDD | B&H gain/DD | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| fold 1/3 | 10,030 | +0.3% | 0.0% | 3.00 | 2 | 100.0% | 10,774 | +7.7% | 17.8% | 0.39 | no |
| fold 2/3 | 9,928 | -0.7% | 0.7% | -1.00 | 6 | 16.7% | 11,616 | +16.2% | 4.8% | 2.91 | no |
| fold 3/3 | 9,987 | -0.1% | 0.2% | -0.61 | 2 | 50.0% | 11,028 | +10.3% | 8.2% | 1.25 | no |
| full sample | 9,945 | -0.5% | 0.8% | -0.65 | 10 | 40.0% | 13,755 | +37.5% | 17.8% | 1.90 | no |

Full sample: 10 trades on 516 days, avg -0.15R, profit factor 0.45, commissions $20, exits: target 2, stop 6, time 2.

Gate: passes 0/3 folds, full sample no → **FAIL**

## SPY — AIR3 (comparison), $10,000

| window | final $ | return | maxDD | gain/DD | trades | win% | B&H final $ | B&H return | B&H maxDD | B&H gain/DD | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| fold 1/3 | 9,572 | -4.3% | 13.7% | -0.28 | 1 | - | 10,774 | +7.7% | 17.8% | 0.39 | no |
| fold 2/3 | 11,078 | +10.8% | 4.7% | 2.07 | 0 | - | 11,616 | +16.2% | 4.8% | 2.91 | no |
| fold 3/3 | 10,980 | +9.8% | 8.2% | 1.19 | 0 | - | 11,028 | +10.3% | 8.2% | 1.25 | no |
| full sample | 11,705 | +17.1% | 13.7% | 1.12 | 1 | - | 13,755 | +37.5% | 17.8% | 1.90 | no |

Gate on this 2-year window: passes 0/3 folds, full sample no → **FAIL**

## SPY — A two-sided, $870

| window | final $ | return | maxDD | gain/DD | trades | win% | B&H final $ | B&H return | B&H maxDD | B&H gain/DD | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| fold 1/3 | 868 | -0.2% | 0.2% | -1.00 | 2 | 0.0% | 915 | +5.1% | 12.4% | 0.38 | no |
| fold 2/3 | 850 | -2.2% | 2.2% | -1.00 | 7 | 0.0% | 970 | +11.5% | 3.6% | 2.88 | no |
| fold 3/3 | 865 | -0.5% | 0.5% | -1.00 | 2 | 0.0% | 948 | +9.0% | 7.3% | 1.23 | no |
| full sample | 844 | -3.0% | 3.0% | -1.00 | 11 | 0.0% | 1,090 | +25.3% | 12.4% | 1.89 | no |

Full sample: 11 trades on 516 days, avg -0.23R, profit factor 0.00, commissions $22, exits: target 2, stop 7, time 2.

Gate: passes 0/3 folds, full sample no → **FAIL**

## SPY — B long-only (TFSA), $870

| window | final $ | return | maxDD | gain/DD | trades | win% | B&H final $ | B&H return | B&H maxDD | B&H gain/DD | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| fold 1/3 | 868 | -0.2% | 0.2% | -1.00 | 2 | 0.0% | 915 | +5.1% | 12.4% | 0.38 | no |
| fold 2/3 | 854 | -1.8% | 1.8% | -1.00 | 6 | 0.0% | 970 | +11.5% | 3.6% | 2.88 | no |
| fold 3/3 | 865 | -0.5% | 0.5% | -1.00 | 2 | 0.0% | 948 | +9.0% | 7.3% | 1.23 | no |
| full sample | 847 | -2.6% | 2.6% | -1.00 | 10 | 0.0% | 1,090 | +25.3% | 12.4% | 1.89 | no |

Full sample: 10 trades on 516 days, avg -0.15R, profit factor 0.00, commissions $20, exits: target 2, stop 6, time 2.

Gate: passes 0/3 folds, full sample no → **FAIL**

## SPY — AIR3 (comparison), $870

| window | final $ | return | maxDD | gain/DD | trades | win% | B&H final $ | B&H return | B&H maxDD | B&H gain/DD | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| fold 1/3 | 843 | -3.1% | 9.7% | -0.30 | 1 | - | 915 | +5.1% | 12.4% | 0.38 | no |
| fold 2/3 | 941 | +8.2% | 3.7% | 2.04 | 0 | - | 970 | +11.5% | 3.6% | 2.88 | no |
| fold 3/3 | 944 | +8.6% | 7.3% | 1.17 | 0 | - | 948 | +9.0% | 7.3% | 1.23 | no |
| full sample | 994 | +14.3% | 9.7% | 1.38 | 1 | - | 1,090 | +25.3% | 12.4% | 1.89 | no |

Gate on this 2-year window: passes 0/3 folds, full sample no → **FAIL**

## QQQ — A two-sided, $10,000

| window | final $ | return | maxDD | gain/DD | trades | win% | B&H final $ | B&H return | B&H maxDD | B&H gain/DD | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| fold 1/3 | 9,946 | -0.5% | 0.5% | -1.00 | 4 | 25.0% | 11,251 | +12.5% | 21.2% | 0.51 | no |
| fold 2/3 | 10,140 | +1.4% | 0.3% | 5.02 | 7 | 57.1% | 11,953 | +19.5% | 7.4% | 2.16 | no |
| fold 3/3 | 9,854 | -1.5% | 1.5% | -1.00 | 2 | 0.0% | 11,890 | +18.9% | 11.0% | 1.49 | no |
| full sample | 9,939 | -0.6% | 1.5% | -0.41 | 13 | 38.5% | 15,806 | +58.1% | 21.2% | 2.35 | no |

Full sample: 13 trades on 516 days, avg -0.08R, profit factor 0.77, commissions $26, exits: target 2, stop 8, time 3.

Gate: passes 0/3 folds, full sample no → **FAIL**

## QQQ — B long-only (TFSA), $10,000

| window | final $ | return | maxDD | gain/DD | trades | win% | B&H final $ | B&H return | B&H maxDD | B&H gain/DD | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| fold 1/3 | 9,981 | -0.2% | 0.3% | -0.62 | 3 | 33.3% | 11,251 | +12.5% | 21.2% | 0.51 | no |
| fold 2/3 | 10,051 | +0.5% | 0.3% | 2.00 | 4 | 50.0% | 11,953 | +19.5% | 7.4% | 2.16 | no |
| fold 3/3 | 10,000 | +0.0% | 0.0% | 0.00 | 0 | - | 11,890 | +18.9% | 11.0% | 1.49 | no |
| full sample | 10,031 | +0.3% | 0.4% | 0.70 | 7 | 42.9% | 15,806 | +58.1% | 21.2% | 2.35 | no |

Full sample: 7 trades on 516 days, avg -0.03R, profit factor 1.42, commissions $14, exits: target 1, stop 4, time 2.

Gate: passes 0/3 folds, full sample no → **FAIL**

## QQQ — AIR3 (comparison), $10,000

| window | final $ | return | maxDD | gain/DD | trades | win% | B&H final $ | B&H return | B&H maxDD | B&H gain/DD | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| fold 1/3 | 10,100 | +1.0% | 12.5% | 0.07 | 1 | - | 11,251 | +12.5% | 21.2% | 0.51 | no |
| fold 2/3 | 11,371 | +13.7% | 7.4% | 1.61 | 0 | - | 11,953 | +19.5% | 7.4% | 2.16 | no |
| fold 3/3 | 10,505 | +5.1% | 10.5% | 0.46 | 1 | - | 11,890 | +18.9% | 11.0% | 1.49 | no |
| full sample | 12,178 | +21.8% | 12.5% | 1.53 | 2 | - | 15,806 | +58.1% | 21.2% | 2.35 | no |

Gate on this 2-year window: passes 0/3 folds, full sample no → **FAIL**

## QQQ — A two-sided, $870

| window | final $ | return | maxDD | gain/DD | trades | win% | B&H final $ | B&H return | B&H maxDD | B&H gain/DD | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| fold 1/3 | 860 | -1.2% | 1.2% | -1.00 | 4 | 0.0% | 932 | +7.1% | 13.0% | 0.50 | no |
| fold 2/3 | 865 | -0.5% | 0.7% | -0.78 | 7 | 57.1% | 978 | +12.4% | 5.1% | 2.14 | no |
| fold 3/3 | 856 | -1.6% | 1.6% | -1.00 | 2 | 0.0% | 995 | +14.4% | 8.5% | 1.48 | no |
| full sample | 841 | -3.3% | 3.3% | -1.00 | 13 | 30.8% | 1,159 | +33.3% | 13.0% | 2.35 | no |

Full sample: 13 trades on 516 days, avg -0.08R, profit factor 0.10, commissions $26, exits: target 2, stop 8, time 3.

Gate: passes 0/3 folds, full sample no → **FAIL**

## QQQ — B long-only (TFSA), $870

| window | final $ | return | maxDD | gain/DD | trades | win% | B&H final $ | B&H return | B&H maxDD | B&H gain/DD | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| fold 1/3 | 863 | -0.8% | 0.8% | -1.00 | 3 | 0.0% | 932 | +7.1% | 13.0% | 0.50 | no |
| fold 2/3 | 866 | -0.5% | 0.6% | -0.81 | 4 | 50.0% | 978 | +12.4% | 5.1% | 2.14 | no |
| fold 3/3 | 870 | +0.0% | 0.0% | 0.00 | 0 | - | 995 | +14.4% | 8.5% | 1.48 | no |
| full sample | 859 | -1.3% | 1.4% | -0.92 | 7 | 28.6% | 1,159 | +33.3% | 13.0% | 2.35 | no |

Full sample: 7 trades on 516 days, avg -0.03R, profit factor 0.08, commissions $14, exits: target 1, stop 4, time 2.

Gate: passes 0/3 folds, full sample no → **FAIL**

## QQQ — AIR3 (comparison), $870

| window | final $ | return | maxDD | gain/DD | trades | win% | B&H final $ | B&H return | B&H maxDD | B&H gain/DD | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| fold 1/3 | 873 | +0.4% | 7.6% | 0.04 | 1 | - | 932 | +7.1% | 13.0% | 0.50 | no |
| fold 2/3 | 950 | +9.2% | 5.2% | 1.59 | 0 | - | 978 | +12.4% | 5.1% | 2.14 | no |
| fold 3/3 | 916 | +5.2% | 9.3% | 0.54 | 1 | - | 995 | +14.4% | 8.5% | 1.48 | no |
| full sample | 1,005 | +15.6% | 8.4% | 1.60 | 2 | - | 1,159 | +33.3% | 13.0% | 2.35 | no |

Gate on this 2-year window: passes 0/3 folds, full sample no → **FAIL**

## SMH — A two-sided, $10,000

| window | final $ | return | maxDD | gain/DD | trades | win% | B&H final $ | B&H return | B&H maxDD | B&H gain/DD | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| fold 1/3 | 10,024 | +0.2% | 1.0% | 0.23 | 3 | 66.7% | 11,046 | +10.5% | 30.8% | 0.29 | no |
| fold 2/3 | 10,128 | +1.3% | 0.0% | 12.76 | 3 | 66.7% | 16,191 | +61.9% | 11.5% | 3.59 | no |
| fold 3/3 | 10,295 | +2.9% | 0.0% | 29.50 | 3 | 100.0% | 15,343 | +53.4% | 23.4% | 1.41 | no |
| full sample | 10,454 | +4.5% | 1.0% | 4.46 | 9 | 77.8% | 27,181 | +171.8% | 30.8% | 2.48 | no |

Full sample: 9 trades on 516 days, avg +1.45R, profit factor 5.46, commissions $18, exits: target 7, stop 1, time 1.

Gate: passes 0/3 folds, full sample no → **FAIL**

## SMH — B long-only (TFSA), $10,000

| window | final $ | return | maxDD | gain/DD | trades | win% | B&H final $ | B&H return | B&H maxDD | B&H gain/DD | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| fold 1/3 | 10,126 | +1.3% | 0.0% | 12.55 | 2 | 100.0% | 11,046 | +10.5% | 30.8% | 0.29 | no |
| fold 2/3 | 10,128 | +1.3% | 0.0% | 12.76 | 3 | 66.7% | 16,191 | +61.9% | 11.5% | 3.59 | no |
| fold 3/3 | 10,158 | +1.6% | 0.0% | 15.84 | 2 | 100.0% | 15,343 | +53.4% | 23.4% | 1.41 | no |
| full sample | 10,420 | +4.2% | 0.0% | 41.96 | 7 | 85.7% | 27,181 | +171.8% | 30.8% | 2.48 | no |

Full sample: 7 trades on 516 days, avg +1.72R, profit factor 20983.47, commissions $14, exits: target 6, stop 0, time 1.

Gate: passes 0/3 folds, full sample no → **FAIL**

## SMH — AIR3 (comparison), $10,000

| window | final $ | return | maxDD | gain/DD | trades | win% | B&H final $ | B&H return | B&H maxDD | B&H gain/DD | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| fold 1/3 | 9,816 | -1.8% | 13.7% | -0.12 | 1 | - | 11,046 | +10.5% | 30.8% | 0.29 | no |
| fold 2/3 | 14,194 | +41.9% | 11.5% | 2.79 | 0 | - | 16,191 | +61.9% | 11.5% | 3.59 | no |
| fold 3/3 | 15,217 | +52.2% | 23.6% | 1.38 | 0 | - | 15,343 | +53.4% | 23.4% | 1.41 | no |
| full sample | 21,495 | +115.0% | 23.9% | 2.11 | 1 | - | 27,181 | +171.8% | 30.8% | 2.48 | no |

Gate on this 2-year window: passes 0/3 folds, full sample no → **FAIL**

## SMH — A two-sided, $870

| window | final $ | return | maxDD | gain/DD | trades | win% | B&H final $ | B&H return | B&H maxDD | B&H gain/DD | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| fold 1/3 | 868 | -0.3% | 1.0% | -0.28 | 3 | 66.7% | 944 | +8.5% | 26.0% | 0.28 | no |
| fold 2/3 | 872 | +0.3% | 0.2% | 1.24 | 3 | 66.7% | 1,345 | +54.6% | 10.6% | 3.58 | no |
| fold 3/3 | 882 | +1.4% | 0.0% | 14.01 | 3 | 100.0% | 1,334 | +53.3% | 23.4% | 1.41 | no |
| full sample | 882 | +1.4% | 1.0% | 1.39 | 9 | 77.8% | 2,096 | +141.0% | 26.0% | 2.48 | no |

Full sample: 9 trades on 516 days, avg +1.45R, profit factor 2.15, commissions $18, exits: target 7, stop 1, time 1.

Gate: passes 0/3 folds, full sample no → **FAIL**

## SMH — B long-only (TFSA), $870

| window | final $ | return | maxDD | gain/DD | trades | win% | B&H final $ | B&H return | B&H maxDD | B&H gain/DD | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| fold 1/3 | 876 | +0.7% | 0.0% | 7.14 | 2 | 100.0% | 944 | +8.5% | 26.0% | 0.28 | no |
| fold 2/3 | 872 | +0.3% | 0.2% | 1.24 | 3 | 66.7% | 1,345 | +54.6% | 10.6% | 3.58 | no |
| fold 3/3 | 876 | +0.7% | 0.0% | 6.94 | 2 | 100.0% | 1,334 | +53.3% | 23.4% | 1.41 | no |
| full sample | 885 | +1.7% | 0.2% | 7.76 | 7 | 85.7% | 2,096 | +141.0% | 26.0% | 2.48 | no |

Full sample: 7 trades on 516 days, avg +1.72R, profit factor 8.76, commissions $14, exits: target 6, stop 0, time 1.

Gate: passes 0/3 folds, full sample no → **FAIL**

## SMH — AIR3 (comparison), $870

| window | final $ | return | maxDD | gain/DD | trades | win% | B&H final $ | B&H return | B&H maxDD | B&H gain/DD | passes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| fold 1/3 | 854 | -1.8% | 12.1% | -0.13 | 1 | - | 944 | +8.5% | 26.0% | 0.28 | no |
| fold 2/3 | 1,116 | +28.2% | 8.4% | 2.78 | 0 | - | 1,345 | +54.6% | 10.6% | 3.58 | no |
| fold 3/3 | 1,323 | +52.0% | 23.6% | 1.37 | 0 | - | 1,334 | +53.3% | 23.4% | 1.41 | no |
| full sample | 1,561 | +79.5% | 20.1% | 2.10 | 1 | - | 2,096 | +141.0% | 26.0% | 2.48 | no |

Gate on this 2-year window: passes 0/3 folds, full sample no → **FAIL**

## Summary

| symbol | strategy | start $ | folds passed | full-sample return | B&H return | maxDD | B&H maxDD | gate |
|---|---|---|---|---|---|---|---|---|
| SPY | A two-sided | 10,000 | 0/3 | -0.8% | +37.5% | 1.1% | 17.8% | FAIL |
| SPY | B long-only (TFSA) | 10,000 | 0/3 | -0.5% | +37.5% | 0.8% | 17.8% | FAIL |
| SPY | AIR3 | 10,000 | 0/3 | +17.1% | +37.5% | 13.7% | 17.8% | FAIL |
| SPY | A two-sided | 870 | 0/3 | -3.0% | +25.3% | 3.0% | 12.4% | FAIL |
| SPY | B long-only (TFSA) | 870 | 0/3 | -2.6% | +25.3% | 2.6% | 12.4% | FAIL |
| SPY | AIR3 | 870 | 0/3 | +14.3% | +25.3% | 9.7% | 12.4% | FAIL |
| QQQ | A two-sided | 10,000 | 0/3 | -0.6% | +58.1% | 1.5% | 21.2% | FAIL |
| QQQ | B long-only (TFSA) | 10,000 | 0/3 | +0.3% | +58.1% | 0.4% | 21.2% | FAIL |
| QQQ | AIR3 | 10,000 | 0/3 | +21.8% | +58.1% | 12.5% | 21.2% | FAIL |
| QQQ | A two-sided | 870 | 0/3 | -3.3% | +33.3% | 3.3% | 13.0% | FAIL |
| QQQ | B long-only (TFSA) | 870 | 0/3 | -1.3% | +33.3% | 1.4% | 13.0% | FAIL |
| QQQ | AIR3 | 870 | 0/3 | +15.6% | +33.3% | 8.4% | 13.0% | FAIL |
| SMH | A two-sided | 10,000 | 0/3 | +4.5% | +171.8% | 1.0% | 30.8% | FAIL |
| SMH | B long-only (TFSA) | 10,000 | 0/3 | +4.2% | +171.8% | 0.0% | 30.8% | FAIL |
| SMH | AIR3 | 10,000 | 0/3 | +115.0% | +171.8% | 23.9% | 30.8% | FAIL |
| SMH | A two-sided | 870 | 0/3 | +1.4% | +141.0% | 1.0% | 26.0% | FAIL |
| SMH | B long-only (TFSA) | 870 | 0/3 | +1.7% | +141.0% | 0.2% | 26.0% | FAIL |
| SMH | AIR3 | 870 | 0/3 | +79.5% | +141.0% | 20.1% | 26.0% | FAIL |
