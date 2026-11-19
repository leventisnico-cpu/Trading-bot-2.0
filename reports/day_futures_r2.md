# DAY-70 results (round 2)

Data: Astral 5m, 2024-09-11 to 2026-10-05 (516 sessions); selection 2024-09-11 to 2025-12-04 (309), test 2025-12-04 to 2026-10-05 (207). sha256 SPY `08f74f09…`, QQQ `97571a72…`. Costs 1 bp/side. P&L in $ for 1 MES (SPY) + 1 MNQ (QQQ) per signal.

| system | parameter | period | trades | per day | win rate | PF | net $ | avg win $ | avg loss $ | max DD $ | months + |
|---|---|---|---|---|---|---|---|---|---|---|---|
| R2 | t=0.10% | selection | 668 | 2.16 | 74% | 0.81 | -3,326 | 29 | 101 | 3,946 | 7/15 |
| R2 | t=0.10% | test | 404 | 1.95 | 72% | 0.79 | -2,811 | 37 | 121 | 3,025 | 4/11 |
| R2 | t=0.15% | selection | 579 | 1.87 | 72% | 0.95 | -930 | 47 | 126 | 2,950 | 8/15 |
| R2 | t=0.15% | test | 340 | 1.64 | 67% | 0.84 | -2,516 | 59 | 140 | 3,204 | 4/11 |
| R2 | t=0.20% | selection | 509 | 1.65 | 70% | 1.06 | 1,194 | 63 | 139 | 2,437 | 9/15 |
| R2 | t=0.20% | test | 304 | 1.47 | 64% | 0.95 | -770 | 78 | 146 | 2,200 | 5/11 |

**Chosen in selection:** system R2, parameter 0.20% (selection choices: R2=0.20%).

Test-period GO bar:
* win rate ≥ 70%: FAIL
* PF ≥ 1.2 and net > 0: FAIL
* ≥ 1 trade per session: PASS
* ≥ 6 profitable months: FAIL
* max DD < half of net: FAIL

**Verdict: NO-GO**
