# Phase 4 Verdict

## DO NOT DEPLOY the dual-momentum strategy. The falsification attempt succeeded.

This system was built to prove its own strategy worthless and deploy only if that
attempt failed (§2). The attempt did not fail. On real data, with real per-order
costs, the strategy loses to the boring alternative:

| $0 start, $100/week, 2015–2026, CAD ETFs at IBKR fixed fees | CAGR (TWR) | Sharpe | maxDD | final wealth |
|---|---|---|---|---|
| Dual momentum 12-1 | 7.95% | 0.58 | −27.4% | **$105,795** |
| Buy-and-hold DCA, 100% US equity (XUU) | 13.59% | 0.88 | −27.8% | **$152,969** |
| Buy-and-hold DCA, 60/40 | 8.63% | 0.86 | −20.0% | **$108,237** |

*(Numbers re-measured TWICE, after each adversarial audit round. Round 1
found the "12-1" momentum actually spanned 13 months plus 13 engine bugs;
round 2 found 15 more, including ~10% of deposits going missing on holiday
Mondays — see audit/ROUND1.md and audit/ROUND2.md. The verdict survived
both corrections: the strategy trails both benchmarks on final wealth.)*

The full measurements are in [PHASE_4_RESULTS.md](PHASE_4_RESULTS.md). What they say:

1. **The strategy underperforms buy-and-hold on risk-adjusted terms in every
   fold.** Not one bad stretch: 60/40's Sharpe beats the strategy's in all three
   sub-periods (0.62/0.66/1.49 vs 0.42/0.30/1.09). Against 100% equity DCA it is
   ~$42,000 of final wealth behind, with the *same* maximum drawdown — and it
   now trails even the 60/40 on final wealth.

2. **The advertised crash protection did not show up.** On the long-history US
   proxy including 2008 (SPY/EFA/EEM with AGG defensive, 2004–2026), the
   strategy's crisis drawdown was −35.0% vs −35.3% for 60/40 — statistically
   nothing. Top-1 concentration walked the book into the fastest-crashing asset
   (EM after its 2007 run) faster than a 12-1 monthly filter could walk it out.
   Dual momentum's headline drawdown claims did not survive contact with this
   implementation and sample.

3. **Costs are NOT the problem — the strategy is.** Fee drag is ~0.6%/yr at
   $2,500 and barely better at $100,000 (net-return-by-size table, §6). The
   $100/week account CAN express this strategy at IBKR Canada's fixed fees.
   It just shouldn't.

4. **The measurement is credible.** Net Sharpe of 0.58 sits inside the
   0.4–0.7 band the post-publication-decay literature predicts (Phase 2). No
   result tripped the Sharpe > 1.5 assume-a-bug flag (§2). The parameter grid
   (16 cells, Sharpe 0.35–0.71) shows the whole family underperforming the
   benchmark's 0.86 — this is not one unlucky parameter cell, and no cell was
   cherry-picked (§10).

Honest caveats, stated rather than hidden:
- The CAD sample (2015–2026) is one relentless US bull market — the regime most
  hostile to rotation strategies and most flattering to 100% equity DCA. But the
  regime where momentum is *supposed* to pay (2008, in the US proxy) showed no
  protection either. The hypothesis "it will work in the next bear market" is
  exactly the kind of weakly-evidenced claim Phase 2 requires discounting.
- Adjusted closes approximate total return; Canadian withholding/tax treatment
  is not modeled and does not change the ordering above.

## What the evidence DOES support

Boring wins: **contribution-directed DCA into a static allocation** (the
benchmark rows) — one or two buys a month, fee drag ~0.02–0.03%/yr, no
rotation. The engine, risk layer, and paper-mode automation built here execute
that faithfully: data validation, order batching, kill switches, atomic state,
full reporting. That is an *automation* win, not a trading edge, and it is the
honest deliverable of this project.

Per §9, the paper-mode daily job runs with no credentials and no live-execution
code path exists. Phase 5 (live execution) is **not earned** by this verdict and
is not built.
