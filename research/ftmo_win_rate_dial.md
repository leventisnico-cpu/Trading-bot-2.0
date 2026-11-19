# Diagnostic — what a win rate of 30 in 31 takes

Written 2026-11-09. This is a diagnostic, not a strategy note: nothing
here is a candidate rule and nothing is chosen from the grid.

**The question.** The operator's source for the 5 steps claims about one
losing trade in 31. The bot's 5-step trades lose about one in 2.5
(`research/ftmo_scale_out.md`: 38–39%; `reports/ftmo_bot_replay.md`:
40% in the bot's own code). Is that a fault in the bot?

**The method.** `research/ftmo_win_rate_dial.py`:

* It takes every FAST-4 signal in the study's data, 990 of them, each on
  its own, bought at the next open.
* For each it scans forward for which comes first: a target `a × R`
  above the entry, or a stop `b × R` below it, with R = 3 × ATR(14).
* A gap counts at the open. A bar touching both levels counts as the
  stop (pessimistic) or as the target (optimistic).
* Limits: the signals overlap; there are no costs, no account and no
  FTMO lines.
* Run: `python -B -I research/ftmo_win_rate_dial.py --data-dir <dir>`,
  on the same Astral exports as the studies.

## Result

FAST-4 signals 2012-01-06 → 2026-10-29: 990 over 14.8 years on the four indices (every signal counted, so they overlap). R = 3 × ATR(14).

Each cell: win rate (pessimistic–optimistic), then the payoff per trade in R at the pessimistic rate, before costs. **Bold**: at least 30 wins in 31.

| first target ↓ / stop → | −1R | −2R | −3R | −5R |
|---|---|---|---|---|
| +0.1R | 92.6%–93.0%, +0.019R | **97.2%–97.2%, +0.040R** | **98.4%–98.4%, +0.050R** | **98.7%–98.7%, +0.033R** |
| +0.25R | 84.4%–84.6%, +0.055R | 93.5%–93.5%, +0.104R | 96.0%–96.0%, +0.121R | **97.3%–97.3%, +0.106R** |
| +0.5R | 72.5%–72.5%, +0.087R | 87.6%–87.6%, +0.189R | 92.7%–92.7%, +0.246R | 95.4%–95.4%, +0.247R |
| +1R | 58.9%–58.9%, +0.177R | 78.8%–78.8%, +0.365R | 87.3%–87.3%, +0.492R | 92.4%–92.4%, +0.542R |

The closest stop that gives 30 in 31 here: target +0.1R with the stop at −2R, 20 times further away. It wins 97.2% of the time; one loss takes back 20 wins; the payoff is +0.040R per trade before costs.

## Reading

1. **The win rate is a dial.** It is set by how far the first target
   sits from the stop.
   * The 5 steps fix the first target at the same distance as the stop
     (+10% and −10% in the deck; +1R and −1R here). On these entries
     that gives 59% across all 990 signals, and 61–62% on the trades the
     account takes.
   * No change to steps 3–5 moves it. They act only after the first
     target has been reached.
2. **30 in 31 needs a lopsided bet.** On these entries it takes a first
   target about a tenth of the stop's distance, with the stop twenty
   times further away. Then one loss takes back twenty wins.
3. **A high win rate is not a high return.** The payoff per trade in the
   30-in-31 cells is +0.03 to +0.05R before costs, against +0.18R for
   the symmetric cell.
4. **The wide-stop cells are not an edge.** Their payoffs lean on
   2012–2026 being a rising market, in which a stop 6 to 15 ATR away is
   rarely reached. The sample is one bull market.
5. **What would change the picture.** A hit rate near 97% with a first
   target as far as the stop would need an entry whose price reaches
   +1R before −1R 97 times in 100. That is a property of the entry, and
   the deck discloses no entry rule. With the source's entry rules or a
   verifiable trade record, the same scan can be run on them.
