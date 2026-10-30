# DAY-70 results (round 3: intraday momentum M)

Same data and costs as rounds 1-2 (2024-09-11 to 2026-10-05, selection to 2025-12-04).

| period | trades | per day | win rate | PF | net $ | avg win $ | avg loss $ | max DD $ | months + |
|---|---|---|---|---|---|---|---|---|---|
| selection | 607 | 1.96 | 46% | 0.75 | -5,681 | 62 | 69 | 5,945 | 5/16 |
| test | 412 | 1.99 | 42% | 0.92 | -1,198 | 76 | 59 | 3,712 | 4/11 |

Test-period GO bar:
* PF ≥ 1.2 and net > 0: FAIL
* ≥ 6 profitable months: FAIL
* ≥ 0.9 trades per session: PASS
* max DD < half of net: FAIL

**Verdict: NO-GO**
