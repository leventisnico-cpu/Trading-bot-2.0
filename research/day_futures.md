# Research note: DAY-70, daily index-futures day trades with a 70% win rate

Written 2026-10-05, **before** any number was looked at.

The operator's order (2026-10-05) is daily day trades on futures with a
minimum 70% win rate, paper-traded for 2 weeks before any funded
account.

FAST-4 (`research/ftmo_fast_pass.md`) is a swing system that trades a
few times a month, so it does not meet this order. This note replaces it
as the system under test.

## Instruments and data

* **Contracts and proxies:** MES and MNQ (micro E-mini S&P 500 and
  Nasdaq-100). They are traded through their ETF twins, SPY and QQQ,
  which track the futures tick for tick in the cash session.
* **Why proxies:** Astral rejects raw futures contracts ("Direct futures
  contracts are not supported yet"). The paper run must therefore use
  the ETFs.
* **P&L conversion:** P&L is converted to micro-futures dollars. 1 MES =
  $5 × S&P points ≈ $50 × SPY dollars. 1 MNQ = $2 × NDX points ≈
  $81 × QQQ dollars (the NDX/QQQ ratio is about 40.6).
* **Data:** Astral 5-minute bars, regular session only, 2024-09-11 to
  2026-10-05. Input sha256: SPY `08f74f09…`, QQQ `97571a72…`.
* **Selection period:** the first 60% of sessions. **Test period:** the
  last 40%. Every result is reported for both.
* **Costs:** 1 bp of price per side, about 2 bp round trip. For MES at
  S&P 7,700 that is about 1.5 points ≈ $7.70 round trip. A realistic
  micro round trip, with commission ~$1.24 plus 1 tick of slippage each
  side, costs about $3.75, so these costs are conservative.

## Fills (conservative)

* A signal on a bar's close fills at the **next bar's open**.
* Stops and targets rest in the market and fill at their price, or at
  the bar's open if the bar gaps through.
* If a bar touches both the stop and the target, the **stop** counts.
* Every position is flat by the 15:55 bar close. No position is ever
  held overnight.
* Each symbol has at most one position at a time. New entries stop at
  15:00.

## The two systems (fixed rules; one free parameter each)

**G: opening-gap fade.**
* Gap = today's 09:30 open / yesterday's last close − 1.
* If g_min ≤ |gap| ≤ 1.0%, fade the gap. Decide at the close of the
  09:30–09:35 bar and fill at the next bar's open.
* Target: yesterday's close (the gap filled). Stop: entry ∓ |gap| × close
  (the gap's size again, beyond the entry). Time exit: 15:55.
* At most 1 trade per symbol per day.
* Free parameter: g_min ∈ {0.10, 0.20, 0.30}%.

**R: intraday RSI(2) pullback with the day's direction.**
* RSI(2) is Wilder's, computed on 5-minute closes and carried across
  days.
* Long when RSI(2) < 10 and close > today's 09:30 open. Short when
  RSI(2) > 90 and close < today's 09:30 open.
* Target: t% from entry. Stop: 3 × t% from entry. Time exit: 15:55.
* Entries from 09:45 to 15:00. Several trades per day are allowed, one
  at a time per symbol.
* Free parameter: t ∈ {0.10, 0.15, 0.20, 0.30}%.

## Choosing, in the selection period only

1. For each system, pick the parameter value with the highest profit
   factor among those with a win rate ≥ 70%. Ties go to the smaller
   value.
2. Then pick the system with the higher selection-period profit factor.
   If neither system reaches 70% in selection, the verdict is NO-GO.

## GO bar: test period, chosen system, SPY and QQQ combined, after costs

All five must hold:
1. **Win rate ≥ 70%.**
2. **Profit factor ≥ 1.2** and net P&L > 0.
3. **At least 1 trade per session on average.** These are daily day
   trades.
4. **Profitable in at least 6 of the test-period calendar months.**
5. **Max drawdown smaller than half the test-period net P&L**, measured
   on 1 MES + 1 MNQ per signal.

If GO, the system goes to the Astral paper account for 2 weeks (the
operator's order) and is then wired into the FTMO/futures bot.

If NO-GO, it does **not** go to paper as a "70% system". The result is
reported as it is.

## Result

(filled in after the run, below this line, without editing anything
above)

Run 2026-10-05, `python research/day_futures.py --data-dir <dir> --report
reports/day_futures.md`. Full table in `reports/day_futures.md`.
516 sessions: selection 309 (2024-09-11 → 2025-12-03), test 207
(2025-12-04 → 2026-10-05).

| system | chosen parameter | test win rate | test PF | test net $ (1 MES + 1 MNQ) | trades/session | months + |
|---|---|---|---|---|---|---|
| R (RSI(2) pullback) | t = 0.10% | 73% | 0.79 | −6,365 | 4.4 | 3/11 |
| G (gap fade) | none reached 70% | 50–51% | 0.82 | −3,558 to −4,318 | 0.9–1.4 | 3–4/11 |

**Verdict: NO-GO.** R reaches the 70% win rate but loses money: the
average win is $36 and the average loss $122. Sensitivity, outside the
pre-registered test and over the whole sample: at **zero** costs R
with t = 0.10–0.30% has a profit factor of only 1.02–1.11; at 0.5
bp/side it is 0.88–1.02. The high win rate is bought with losses 3–4×
larger than wins, and there is no edge underneath to pay for it. G has
no edge at all (about 50% wins, PF below 1 even before costs).

## Round 2: DAY-70b (pre-registered 2026-10-05, after round 1's result)

One variant, judged by the same selection rule and GO bar as round 1.
This is a second look at the same data, so a pass would need extra
caution before going to paper.

**R2:** R plus a daily-trend filter.
* Longs only if the previous session's close is above the 20-session
  average of daily closes; shorts only if it is below.
* Everything else as R: target t, stop 3t, entries from 09:45 to 15:00,
  flat at 15:55.
* Free parameter: t ∈ {0.10, 0.15, 0.20}%.

### Result
(filled in below after the run)

Run 2026-10-05 (`--round 2`, `reports/day_futures_r2.md`). Selection
chose t = 0.20% (70% wins, PF 1.06). In the test period it made **64%
wins, PF 0.95, −$770, 5/11 profitable months. NO-GO.** At t = 0.10%,
R2 keeps its 72% win rate in the test period but has PF 0.79. The trend
filter does not create an edge.

## Conclusion of rounds 1–2

On two years of 5-minute index data, a simple intraday system can win
70% of its trades, but none of these makes money. The average loss is
3–4× the average win, and the raw edge is about zero before costs. The
only system in this repo that has both a 70%+ win rate and a real edge
is FAST-4, which holds 1–10 days (`research/ftmo_fast_pass.md`).

## Round 3: DAY-M (pre-registered 2026-10-05). NOT a 70% system.

The operator asked for a 70% win rate. Rounds 1–2 show that no simple
day-trading rule meets it profitably, so this round tests the best-known
*profitable* intraday effect so that the operator can choose. The win
rate is reported, not required.

**M: intraday momentum** (Gao, Han, Li & Zhou 2018, "Market intraday
momentum").
* Signal: the return from yesterday's last close to today's 10:00 bar
  close. If it is positive, buy at the open of the 15:30 bar; if it is
  negative, short there.
* Exit: the 15:55 bar close.
* One trade per symbol per day, every day. No stop (it is a 30-minute
  hold). No free parameter.

GO bar (test period, after costs): PF ≥ 1.2, net > 0, ≥ 6/11 profitable
months, ≥ 0.9 trades/session, max DD < half of net. The selection
period is reported alongside for consistency.

### Result
(filled in below after the run)

Run 2026-10-05 (`reports/day_futures_r3.md`). Test period: 42% wins, PF
0.92, −$1,198, 4/11 profitable months. Selection period: 46% wins, PF
0.75. **NO-GO.** The published intraday-momentum effect is not present
in SPY/QQQ over 2024–2026 after costs.

## Overall verdict (rounds 1–3)

No day-trading rule tested here is profitable after costs, at any win
rate. The ones that win ≥ 70% of trades (R, R2) lose money, because the
losers are 3–4× the winners. This repo has tested six ideas so far:
TJR's sweep/BOS, the AI-70 swing set, FTMO swing, prop-native, FAST-4,
and DAY-70 rounds 1–3. FAST-4 is the only one with a 70% win rate and a
positive profit factor, and it holds positions for 1–10 days.
