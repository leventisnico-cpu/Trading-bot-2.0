# FAST-4 under FTMO 2-Step rules: the bot's risk controls

Companion to `reports/ftmo_fast_pass.md` (`research/ftmo_bot_policy.py`). Common dates 2011-03-23 → 2026-10-29; selection starts before 2019-01-01, test starts from it; 368 test start dates. Cap: every open stop together stays the buffer above both loss lines. Lock: flatten at target + 0.3%, add missing trading days with minimum-lot round trips. 'Both, ever' counts passes within the data, however long they took; late start dates have less room. 'Breached': a daily-loss, max-loss or inactivity breach ended the attempt. 'Still running': no pass and no breach when the data ends.

| policy | period | trades | win rate | profit factor | P1 passed | both ≤6 mo | both ≤18 mo | both, ever | breached | still running | days to pass (p25 / median / p75) | main failure | funded 1y survival | funded 1y return (median, survivors) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| pre-registered 3% (no cap, no lock) | selection | 196 | 65% | 1.23 | 38% | 0% | 16% | 29% | 71% | 0% | 380 / 517 / 642 | P1 daily_loss 62% | 29% | +6.8% |
| pre-registered 3% (no cap, no lock) | test | 200 | 70% | 1.41 | 59% | 0% | 18% | 23% | 77% | 0% | 330 / 392 / 523 | P1 daily_loss 41% | 36% | +10.1% |
| bot 3%: cap 0.2%, lock | selection | 196 | 65% | 1.17 | 57% | 0% | 9% | 29% | 41% | 30% | 465 / 670 / 936 | P1 daily_loss 21% | 85% | +3.9% |
| bot 3%: cap 0.2%, lock | test | 200 | 70% | 1.50 | 89% | 0% | 17% | 70% | 1% | 29% | 554 / 858 / 1428 | P2 unfinished 19% | 99% | +6.6% |
| bot 3%: cap 1.0%, lock | selection | 196 | 65% | 1.12 | 48% | 0% | 6% | 16% | 48% | 36% | 522 / 622 / 1229 | P1 daily_loss 32% | 86% | +2.7% |
| bot 3%: cap 1.0%, lock | test | 181 | 70% | 1.55 | 87% | 0% | 14% | 78% | 0% | 22% | 612 / 970 / 1570 | P1 unfinished 13% | 100% | +5.5% |
| bot 2%: cap 0.2%, lock | selection | 196 | 65% | 1.24 | 56% | 0% | 0% | 20% | 45% | 34% | 898 / 1040 / 2469 | P1 daily_loss 21% | 86% | +3.7% |
| bot 2%: cap 0.2%, lock | test | 200 | 70% | 1.40 | 90% | 0% | 6% | 80% | 0% | 20% | 690 / 1200 / 1575 | P2 unfinished 10% | 100% | +5.1% |

**Fees per funded account** at EUR 89 per attempt: a breach costs a new fee; a slow attempt keeps running, since FTMO has no time limit. The passing attempt's fee comes back with the first payout.

* pre-registered 3% (no cap, no lock), selection period: 3.45 attempts per pass, about EUR 307 of fees per pass.
* pre-registered 3% (no cap, no lock), test period: 4.28 attempts per pass, about EUR 381 of fees per pass.
* bot 3%: cap 0.2%, lock, selection period: 2.40 attempts per pass, about EUR 214 of fees per pass.
* bot 3%: cap 0.2%, lock, test period: 1.02 attempts per pass, about EUR 90 of fees per pass.
* bot 3%: cap 1.0%, lock, selection period: 4.04 attempts per pass, about EUR 359 of fees per pass.
* bot 3%: cap 1.0%, lock, test period: 1.00 attempts per pass, about EUR 89 of fees per pass.
* bot 2%: cap 0.2%, lock, selection period: 3.21 attempts per pass, about EUR 286 of fees per pass.
* bot 2%: cap 0.2%, lock, test period: 1.00 attempts per pass, about EUR 89 of fees per pass.

The pre-registered row must match `reports/ftmo_fast_pass.md` run on the same data; the other rows are the same rule with the bot's risk controls, not a new strategy choice. 3% risk per trade is the operator's order; the 2% row is shown for the trade-off only.
