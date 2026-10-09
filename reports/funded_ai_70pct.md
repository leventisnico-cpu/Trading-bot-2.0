# AI-trade strategies vs a two-phase prop evaluation

Rules: `research/funded_ai_70pct.md` (pre-registered). Next-day open fills, 0.02% per side, 5%/yr financing on notional.

## SMH — AIR3 (2003-09-10 → 2026-10-02)

Full sample at 1.0×: 10 trades, win rate 60%, folds 25%, 67%, 100%; average win +86.70%, average loss -6.58% of the balance at entry; ending balance 13.16× the start.

| sizing | eval pass | median days to pass | P1 max loss | P1 daily loss | inactive (either phase) | other | funded survives 1y | median funded 1y return |
|---|---|---|---|---|---|---|---|---|
| 1.0× | 0% | nan | 6% | 9% | 85% | 0% | 32% | +7.5% |
| 2.0× | 0% | nan | 7% | 45% | 48% | 0% | 5% | +0.0% |

Bars at 1.0×: win rate ≥70% everywhere no; eval pass ≥60% no (0%); funded survival ≥70% no (32%) → **FAIL**

## SMH — DIP2 (2003-09-10 → 2026-10-02)

Full sample at 1.0×: 156 trades, win rate 69%, folds 76%, 58%, 73%; average win +2.81%, average loss -2.33% of the balance at entry; ending balance 2.87× the start.

| sizing | eval pass | median days to pass | P1 max loss | P1 daily loss | inactive (either phase) | other | funded survives 1y | median funded 1y return |
|---|---|---|---|---|---|---|---|---|
| 1.0× | 0% | nan | 0% | 2% | 97% | -0% | 81% | +4.2% |
| 2.0× | 0% | nan | 3% | 18% | 79% | 0% | 21% | +5.4% |

Bars at 1.0×: win rate ≥70% everywhere no; eval pass ≥60% no (0%); funded survival ≥70% YES (81%) → **FAIL**

## QQQ — AIR3 (2011-03-23 → 2026-10-02)

Full sample at 1.0×: 8 trades, win rate 62%, folds 33%, 50%, 100%; average win +55.26%, average loss -6.47% of the balance at entry; ending balance 4.17× the start.

| sizing | eval pass | median days to pass | P1 max loss | P1 daily loss | inactive (either phase) | other | funded survives 1y | median funded 1y return |
|---|---|---|---|---|---|---|---|---|
| 1.0× | 0% | nan | 4% | 1% | 95% | 0% | 57% | +16.2% |
| 2.0× | 0% | nan | 7% | 27% | 66% | -0% | 10% | +36.7% |

Bars at 1.0×: win rate ≥70% everywhere no; eval pass ≥60% no (0%); funded survival ≥70% no (57%) → **FAIL**

## QQQ — DIP2 (2011-03-23 → 2026-10-02)

Full sample at 1.0×: 133 trades, win rate 68%, folds 67%, 59%, 77%; average win +1.54%, average loss -1.80% of the balance at entry; ending balance 1.61× the start.

| sizing | eval pass | median days to pass | P1 max loss | P1 daily loss | inactive (either phase) | other | funded survives 1y | median funded 1y return |
|---|---|---|---|---|---|---|---|---|
| 1.0× | 0% | nan | 2% | 1% | 96% | 1% | 86% | +3.9% |
| 2.0× | 1% | 56 | 3% | 15% | 79% | 3% | 29% | +11.1% |

Bars at 1.0×: win rate ≥70% everywhere no; eval pass ≥60% no (0%); funded survival ≥70% YES (86%) → **FAIL**

## Summary (1.0× sizing)

| symbol | strategy | trades | win rate | fold win rates | eval pass | funded 1y survival | verdict |
|---|---|---|---|---|---|---|---|
| SMH | AIR3 | 10 | 60% | 25% / 67% / 100% | 0% | 32% | FAIL |
| SMH | DIP2 | 156 | 69% | 76% / 58% / 73% | 0% | 81% | FAIL |
| QQQ | AIR3 | 8 | 62% | 33% / 50% / 100% | 0% | 57% | FAIL |
| QQQ | DIP2 | 133 | 68% | 67% / 59% / 77% | 0% | 86% | FAIL |
