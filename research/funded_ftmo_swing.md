# Research note — AIR3 and DIP2 under FTMO 2-Step Swing rules

Written 2026-10-04, **before** this run. Follows
`research/funded_ai_70pct.md`, which used a generic evaluation and found
the 30-day inactivity rule decisive. This note replaces the generic
model with FTMO's published 2-Step Swing rules (as extracted by the
research agent from ftmo.com on 2026-10-04; to be re-checked by the
operator on the pages before any purchase) and adds one disclosed
operational change. The strategies' trading rules are **unchanged**.

## FTMO 2-Step Swing rules modelled
* Account CAD 15,000; fee €155 (refunded with the first reward).
* Phase 1 target +10%, Phase 2 target +5%; no time limit.
* **Max loss:** equity (floating included) must stay above 90% of the
  initial balance at all times. Modelled with the day's low.
* **Max daily loss:** equity must stay above (balance at the start of
  the day − 5% of the initial balance). Balance excludes floating P&L;
  modelled as cash + position at entry value after financing.
* At least 4 trading days per phase (days with a trade).
* **Inactivity:** an evaluation account with no trade for 30 days is
  closed. No inactivity rule on the funded (FTMO Account).
* Swing: overnight and weekend holding allowed; US100 index leverage
  1:15 (so 1.0× and 2.0× notional are both possible).
* Funded: same loss rules; reward 80% of profit; first reward after 14
  days. Survival measured over 252 trading days.

## The one operational change (disclosed, not a strategy change)
**Keep-alive trade:** if 25 calendar days pass without a fill during an
evaluation, the bot opens and immediately closes the minimum position
(0.01 lot) that day. It moves equity by a negligible amount (costs
modelled as zero) and counts as a trading day. Both variants are
reported: **without** keep-alive and **with** keep-alive.

## Instruments, data, costs, strategies
As in `research/funded_ai_70pct.md`: QQQ (2011-03 → 2026-10) as the
US100 proxy; SMH (2003-09 → 2026-10) as the semiconductor proxy (FTMO
has no SMH CFD; NVDA/AMD/AVGO single-stock CFDs are 1:1 leverage on
Swing and are not tested here). AIR3 and DIP2 rules unchanged. 0.02% per
side, 5%/yr financing, next-day open fills. Start dates every 10 trading
days.

## Pre-registered go/no-go (at 1.0×, keep-alive variant, per symbol)
**GO** for buying one evaluation only if: both phases pass in ≥ 60% of
start dates **within 18 months**, **and** the funded account survives
12 months in ≥ 70% of start dates. Otherwise **NO-GO**. Win rate is
reported but is not a go/no-go bar here (the prior note already showed
neither rule reaches 70% in every fold).

## Result
(filled in after the run, below this line, without editing anything
above)

Run 2026-10-04, `python research/funded_ftmo.py --data-dir <dir>`; full
table (both sizings, with and without keep-alive) in
`reports/funded_ftmo_swing.md`.

| symbol | strategy | pass within 18 months | funded 1y survival | verdict |
|---|---|---|---|---|
| QQQ (US100 proxy) | AIR3 | 28% | 54% | **NO-GO** |
| QQQ (US100 proxy) | DIP2 | 8% | 46% | **NO-GO** |
| SMH (semis proxy) | AIR3 | 18% | 45% | **NO-GO** |
| SMH (semis proxy) | DIP2 | 7% | 43% | **NO-GO** |

What was learned:

1. **The keep-alive trade works as intended.** Without it no start date
   passes (inactivity takes 61–89%); with it inactivity disappears as
   a failure cause.
2. **FTMO's daily-loss rule is the real wall.** It is measured from the
   day's starting *balance*, which excludes floating P&L, so any open
   position more than about 5% below its entry price breaches it, even
   with no single bad day. For a swing strategy it acts as a hidden 5%
   stop on every trade. That is now the main failure cause (39–66% of
   attempts at 1.0×), and it also halves funded survival relative to the
   generic model.
3. **Neither rule was designed for that constraint.** AIR3 holds through
   10–25% pullbacks by design; DIP2 has no stop and adds after falls.
4. A strategy built for a prop account would need its own stop well
   inside 5% of entry and about 1% risk per trade. That is a new
   hypothesis and needs a new note; it was not tested here.
5. FTMO's rules were taken from search extracts of ftmo.com because
   direct page fetches were blocked in this environment; the operator
   should read the pages before relying on them.
