# FAST-4 under FTMO 2-Step rules

Rules: `research/ftmo_fast_pass.md` (pre-registered). Common dates 2011-03-23 → 2026-09-30; selection starts before 2019-01-01, test starts from it.

| risk/trade | period | trades | win rate | profit factor | pass ≤6 mo | pass ≤18 mo | median days to pass | main failure | funded 1y survival |
|---|---|---|---|---|---|---|---|---|---|
| 0.5% | selection | 196 | 65% | 1.23 | 0% | 0% | nan | P1 unfinished 89% | 100% |
| 0.5% | test | 196 | 70% | 1.41 | 0% | 0% | nan | P1 unfinished 100% | 100% |
| 1.0% | selection | 196 | 65% | 1.23 | 0% | 0% | 4608 | P2 unfinished 55% | 100% |
| 1.0% | test | 196 | 70% | 1.41 | 0% | 0% | 1470 | P2 unfinished 55% | 100% |
| 1.5% | selection | 196 | 65% | 1.23 | 0% | 0% | 3313 | P2 max_loss 16% | 100% |
| 1.5% | test | 196 | 70% | 1.41 | 0% | 0% | 1575 | P1 unfinished 17% | 100% |
| 2.0% | selection | 196 | 65% | 1.23 | 0% | 0% | 1080 | P1 max_loss 23% | 76% |
| 2.0% | test | 196 | 70% | 1.41 | 0% | 7% | 1086 | P2 unfinished 10% | 100% |
| 2.5% | selection | 196 | 65% | 1.23 | 0% | 9% | 460 | P1 daily_loss 52% | 40% |
| 2.5% | test | 196 | 70% | 1.41 | 0% | 4% | 727 | P1 daily_loss 37% | 56% |
| 3.0% | selection | 196 | 65% | 1.23 | 0% | 16% | 517 | P1 daily_loss 62% | 29% |
| 3.0% | test | 196 | 70% | 1.41 | 0% | 18% | 392 | P1 daily_loss 40% | 37% |

Chosen in the selection period: **0.5%** risk per trade (highest pass ≤6 months with funded survival ≥70%).

Test period at 0.5%: win rate 70% (bar ≥70%), pass ≤6 months 0% (bar ≥50%), funded survival 100% (bar ≥70%), profit factor 1.41 (bar >1.2) → **NO-GO**
