# Research note — FAST-4 with the bot's risk controls under FTMO rules

Written 2026-11-02, after the pre-registered study `ftmo_fast_pass.md`
(verdict NO-GO; 3% risk per trade by the operator's order) and before
this run. This is not a new strategy and not a parameter search: the
rule, the data, the FTMO model and the start dates are those of the
pre-registered study. What changes is what `ftmo_bot` does on top of the
rule, so that the odds quoted to the operator are the bot's, not the bare
rule's.

## Fixed in advance

* **The combined-risk cap** (`ftmo_bot.rules.risk_room`): every open
  stop together stays `buffer` above the daily and the max-loss line, so
  a second position gets only the room the first one leaves. The bot's
  default buffer is 0.2% of the initial balance; 1.0% is run for the
  trade-off only.
* **Trading days** as FTMO counts them: a Prague calendar day on which a
  position was opened. Closes count for nothing.
* **The target lock:** at target + 0.3% the bot flattens and adds the
  missing trading days with minimum-lot round trips. In the simulation
  the lock triggers on the day's high (the bot ticks every minute) and
  the flatten realises that level less closing costs, one session per
  missing day.
* A notional cap of 3× balance per position (the Swing account's 1:15
  leverage); it never binds on US indices.
* Risk per trade 3% (the operator's order); 2% is run for the trade-off
  only.
* The first row switches everything off and must reproduce the
  pre-registered table on the same data.
* Reported, for both periods: the share of start dates passing Phase 1,
  passing both phases within 6 and 18 months and within the data, the
  share that breached a rule and the share still running (no pass, no
  breach) when the data ends, the quartiles of days to pass, the main
  failure, funded one-year survival with the median one-year return of
  the survivors, and the fees per pass at EUR 89 per attempt (the $10k
  account). FTMO has no time limit, so only a breach costs a new fee.

## Result

Run 2026-11-02, `python -I research/ftmo_bot_policy.py --data-dir <dir>`,
on Astral daily exports to 2026-10-29 (sha256 QQQ `cfab2078…`, SPY
`66043ca3…`, DIA `be0494ef…`, IWM `44cc382e…`; SPY and DIA carry a stray
20:00 UTC bar for 10-29, the last common date, which the loader keeps
over the regular one). Full table in `reports/ftmo_bot_policy.md`.

* The control row reproduces the pre-registered table on the same data
  (test period: 200 trades, 70% win rate, profit factor 1.41, 18% pass
  within 18 months, median 392 days, main failure the daily line in 41%,
  funded survival 36%).

| 3% risk per trade | bare rule, 2011–18 starts | bare rule, 2019–26 starts | bot, 2011–18 starts | bot, 2019–26 starts |
|---|---|---|---|---|
| profit factor of the trades | 1.23 | 1.41 | 1.17 | 1.50 |
| both phases passed, within the data | 29% | 23% | 29% | 70% |
| breached a rule (fee lost) | 71% | 77% | 41% | 1% |
| still running when the data ends | 0% | 0% | 30% | 29% |
| both phases within 18 months | 16% | 18% | 9% | 17% |
| days to pass, quartiles | 380 / 517 / 642 | 330 / 392 / 523 | 465 / 670 / 936 | 554 / 858 / 1,428 |
| funded account survives 1 year | 29% | 36% | 85% | 99% |
| funded 1-year return, median of survivors | +6.8% | +10.1% | +3.9% | +6.6% |
| attempts per pass (fees at EUR 89) | 3.45 (EUR 307) | 4.28 (EUR 381) | 2.40 (EUR 214) | 1.02 (EUR 90) |

* **The cap and the lock change how attempts end, not how fast.** The
  bare rule breaches the daily line in most attempts. The bot almost
  never does in 2019–2026 (4 of 368 start dates) and in 41% of the
  harder 2011–2018 starts, where gaps through the stops still break it;
  the rest of its attempts either pass or are still trading when the
  data ends. Slow is survivable: FTMO has no time limit, and the
  keep-alive handles the inactivity rule.
* **It is slow.** The median pass takes 2.3 years (2019–2026 starts) and
  only about one start in six passes within 18 months. The second
  position is cut to about 1.8% risk, which halves progress.
* **The regime matters.** The same rule had a profit factor of 1.17 in
  2011–2018 and 1.50 in 2019–2026. The honest range for the bot is
  29%–70% of attempts passing within the data, 1%–41% breaching, and
  1.0–2.4 fees per funded account.
* A wider buffer (1.0%) or a lower risk (2%) pass less often within 18
  months in both periods (6%/14% and 0%/6%) and breach as often or more
  in 2011–2018; the bot keeps 3% with the 0.2% buffer.
* Funded: 85%–99% of accounts survive a year, with a median return of
  +3.9% to +6.6% on the account size, of which the trader keeps 80%.
