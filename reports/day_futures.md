# DAY-70 results

Data: Astral 5m, 2024-09-11 to 2026-10-05 (516 sessions); selection 2024-09-11 to 2025-12-04 (309), test 2025-12-04 to 2026-10-05 (207). sha256 SPY `08f74f09…`, QQQ `97571a72…`. Costs 1 bp/side. P&L in $ for 1 MES (SPY) + 1 MNQ (QQQ) per signal.

| system | parameter | period | trades | per day | win rate | PF | net $ | avg win $ | avg loss $ | max DD $ | months + |
|---|---|---|---|---|---|---|---|---|---|---|---|
| G | g_min=0.10% | selection | 402 | 1.30 | 47% | 0.86 | -3,565 | 120 | 121 | 4,215 | 7/16 |
| G | g_min=0.10% | test | 283 | 1.37 | 51% | 0.82 | -4,318 | 139 | 173 | 6,069 | 3/11 |
| G | g_min=0.20% | selection | 315 | 1.02 | 50% | 0.91 | -2,073 | 132 | 143 | 3,277 | 8/16 |
| G | g_min=0.20% | test | 230 | 1.11 | 50% | 0.82 | -3,981 | 159 | 196 | 5,718 | 3/11 |
| G | g_min=0.30% | selection | 231 | 0.75 | 48% | 0.91 | -1,788 | 161 | 161 | 3,614 | 8/16 |
| G | g_min=0.30% | test | 180 | 0.87 | 51% | 0.82 | -3,558 | 172 | 221 | 5,238 | 4/11 |
| R | t=0.10% | selection | 1388 | 4.49 | 72% | 0.72 | -11,072 | 29 | 102 | 11,197 | 4/16 |
| R | t=0.10% | test | 903 | 4.36 | 73% | 0.79 | -6,365 | 36 | 122 | 6,691 | 3/11 |
| R | t=0.15% | selection | 1192 | 3.86 | 70% | 0.86 | -6,398 | 47 | 125 | 6,909 | 7/16 |
| R | t=0.15% | test | 758 | 3.66 | 69% | 0.90 | -3,304 | 58 | 145 | 4,678 | 5/11 |
| R | t=0.20% | selection | 1053 | 3.41 | 66% | 0.93 | -3,252 | 63 | 133 | 4,023 | 8/16 |
| R | t=0.20% | test | 665 | 3.21 | 65% | 0.94 | -2,133 | 78 | 155 | 4,390 | 4/11 |
| R | t=0.30% | selection | 902 | 2.92 | 62% | 1.00 | 79 | 90 | 146 | 2,597 | 8/16 |
| R | t=0.30% | test | 546 | 2.64 | 58% | 0.90 | -3,750 | 111 | 168 | 5,818 | 4/11 |

**Chosen in selection:** system R, parameter 0.10% (selection choices: R=0.10%).

Test-period GO bar:
* win rate ≥ 70%: PASS
* PF ≥ 1.2 and net > 0: FAIL
* ≥ 1 trade per session: PASS
* ≥ 6 profitable months: FAIL
* max DD < half of net: FAIL

**Verdict: NO-GO**
