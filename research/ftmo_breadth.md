# Research note — more markets for the 5 steps (B1–B3)

Written 2026-11-11, **before** any account was run on a new market. The
numbers quoted for the bot's rule are already published
(`research/ftmo_slots_sizing.md`) or come from the prices alone, listed
under "What was known before".

## Why

The operator's order of 2026-11-11: "progress the bot's strategy".

The rule the bot runs (the 5 steps, 3% risk, the 1.5% buffer over the
max-loss line, free slots: **W2+S2** of
`research/ftmo_slots_sizing.md`) takes 14.4 trades a year at +0.079R a
trade. It trades four US indices that fall together: each one's daily
returns correlate 0.83 to 0.91 with the other three, on average. Their
990 signals since 2012 fall on 519 of 3,725 sessions. On the other
sessions the account has nothing new to do.

FTMO offers other markets. If they dip on other days, the same rule has
more to do.

## Hypothesis

If the same rule also trades markets whose dips fall on other days, the
account passes both phases more often, or sooner, without breaching
more often.

It is disproved if no list below beats the four US indices by the rule
under "Pre-registered pass/fail".

Written before the run, so it can be held against the result:

* More signals are certain: the sessions with at least one signal go
  from 519 to 660, 789 or 904 (table below). How many of them become
  trades depends on the slots.
* Whether a trade on a new market pays what a trade on a US index pays
  is not known. It decides the result.
* The rule's numbers (RSI(2) under 10, the 200-day average, 3×ATR, the
  5 steps) were set on US indices. Buying a sharp dip in a rising
  market is a known pattern in stock indices. For gold there is less
  reason to expect it.
* The slots study showed what more trades at a lower payoff do: more
  passes in one period, more breaches in both. The same can happen
  here, and by the rule below that is a fail.

## The lists (fixed)

| list | markets |
|---|---|
| **B0** | US100, US500, US30, US2000: the bot today |
| **B1** | B0 + XAUUSD (gold) |
| **B2** | B0 + GER40, UK100, JP225, AUS200 |
| **B3** | B0 + all five |

Only the list differs. Everything else is W2+S2 exactly as published:

* the FAST-4 entry (close over the 200-day average, RSI(2) under 10,
  bought at the next open) and the 5-step exits;
* 3% risk, the 3× notional cap, the combined-risk cap with its 0.2%
  buffer over the daily line and 1.5% over the max-loss line;
* two positions at risk at most; a position whose stop is at or above
  its entry takes no slot; one position per market;
* when more markets signal than there are slots, the lowest RSI(2)
  goes first, as today;
* costs (0.02% a side), financing (5% a year on the open notional), the
  two same-day fill bounds;
* the FTMO model and checks, the target lock, trading days, keep-alive;
* cohorts and start dates.

With nine markets up to nine positions can be open at once. Never more
than two of them have a stop under their entry.

**Why these five.** They were fixed before any of their prices was
looked at:

* XAUUSD: the one large market on FTMO's list that is not a stock
  index.
* GER40, UK100, JP225, AUS200: the largest stock-index CFDs outside the
  US, one per currency. EU50, FRA40, SPN35 and N25 move with GER40.
  HK50 was left out to keep the list short.

FTMO's symbol list was read on 2026-11-11 from secondary sources
(ftmo.com could not be reached from here). It has to be confirmed in
the operator's MetaTrader before any port.

**Three judged lists, no others.** No single-market list is judged, and
no list is put together from the per-market tables afterwards: that
would be picking from a grid.

## Data

Daily bars from the same source as the four index files (Astral),
split-adjusted, **not** adjusted for cash distributions, like the four.

| market | proxy | file | rows | first | last | sha256 |
|---|---|---|---|---|---|---|
| XAUUSD | GLD | `gld_long.csv` | 3,980 | 2011-01-03 | 2026-10-29 | `9d62e4f2811e4cebd6075f8043867e2055b20fcb00cb20dc466f5d38b9993bd6` |
| GER40 | EWG (MSCI Germany) | `ewg_long.csv` | 3,980 | 2011-01-03 | 2026-10-29 | `5bd6e2e38d3968897974f59a832b12011cd4efbff3f26cc629058d81321f5163` |
| UK100 | EWU (MSCI United Kingdom) | `ewu_long.csv` | 3,980 | 2011-01-03 | 2026-10-29 | `0c468b3ed7fb47af10191bdea785c3366e44bf4d83072a8d49d777c151d4f77c` |
| JP225 | EWJ (MSCI Japan) | `ewj_long.csv` | 3,980 | 2011-01-03 | 2026-10-29 | `75e0ef01aba3ee17522e68141014600db6a0f7daf1e95471bc977c39589a9a4d` |
| AUS200 | EWA (MSCI Australia) | `ewa_long.csv` | 3,980 | 2011-01-03 | 2026-10-29 | `7f919003205372d456c9de8428add2df2b575c11055f81beee293db8282cc621` |

The four index files are those of the earlier notes, sha256:

* QQQ `cfab2078c1777e4cf39fab62909d53d2a316fc92b1cfb27dab0719db9ad2e123`
* SPY `66043ca34d7aa4e6b191bf3607a004674f8027f5cb98aa84d0c23e39c07be6ce`
* DIA `be0494ef6804e96889c320e3be4858217c6eada743d80665d01df07a90681f3b`
* IWM `44cc382e05c8da6fdf47fa6b761676cd18867f22ec258d6f02cc47b9533ebdd2`

From 2011-03-23 each of the five new files has exactly the 3,925
sessions the four index files share. The script checks every file's
sha256 and every new file's sessions, and refuses to run otherwise:
nothing is re-aligned, so B0 runs on the published data.

## What these proxies cannot show

The bot would trade FTMO's CFDs. These are US-listed funds. Each
difference is listed with its direction where it has one.

1. **Currency.** EWG, EWU, EWJ and EWA are priced in dollars; the CFDs
   in euros, pounds, yen and Australian dollars. A fund's price moves
   with its index and with the exchange rate. That adds moves the CFD
   does not have: signals that are only currency, and stops hit by
   currency. It adds noise, not a known gain or loss.
2. **Distributions.** The four country funds pay out twice a year,
   roughly 0.5% to 2.5% of the price each time, and the price drops by
   that amount on the ex-date. The drop is not a market move. A long
   position in this model loses it; a CFD does not drop that way. This
   counts **against** the new markets. This run cannot take it out (see
   the next section). (The four US funds pay about 0.1% to 0.5% at a
   time, monthly or quarterly. They stay as published.)
3. **Index.** MSCI's country indices are not the DAX 40, the FTSE 100,
   the Nikkei 225 or the ASX 200. They move closely together, not
   identically.
4. **Hours.** The funds trade 09:30–16:00 New York. The CFDs trade
   almost around the clock, and the four non-US markets make most of
   their moves while New York is closed. In the fund a night's move is
   a gap at the open. So a stop that the CFD would fill at its level
   during the night is filled here at the open, worse; a target is
   filled at the open, better; and a loss during the night is not seen
   by the daily-loss check. The four US indices have the same limit in
   smaller measure.
5. **Costs.** 0.02% a side and 5% a year for every market, as in every
   earlier note. FTMO's spreads on JP225 and AUS200 in the New York
   morning are wider than on the US indices, and its swaps differ by
   market. Neither is modelled.
6. **Gold.** GLD is the gold price less a 0.4% yearly fee, in dollars,
   with no distributions. It is the cleanest of the five proxies.
7. **Margin.** Nine open positions can add up to several times the
   balance. The tables report the largest total, to be held against
   FTMO's margin rules before any port.

For these reasons a pass here does not change the bot (see "What
happens next").

## The distribution drops are not taken out in this run

The script can run B2 and B3 a second time with the four country
funds' prices adjusted for their cash distributions (`--div-dir`): every
price before an ex-date is multiplied by 1 − the amount ÷ the close of
the session before it, the usual back-adjustment. Those would be rows
"B2 adj" and "B3 adj": reported, not judged.

**This run does not have them.** The funds' distribution histories
could not be fetched from here: the data sites are outside this
environment's allowed network. So limit 2 stands in the judged rows and
is not measured.

If the histories are added later, the two rows are appended under a
dated heading. They would show how much of the result hangs on the
ex-date drops. Nothing is adopted on them.

## What was known before

* W2+S2's published tables (`research/ftmo_slots_sizing.md`). B0 is
  that account.
* **What the prices alone show.** From the script's `--check-only` run
  of 2026-11-11, which runs no account on a new market. A signal is a
  close over the 200-day average with RSI(2) under 10; sessions are the
  3,725 from the first trading day (2012-01-06) on.

  | market | signals | … on sessions with no signal in any US index | average correlation of daily returns with the (other) US indices |
  |---|---|---|---|
  | US100 (QQQ) | 267 | | +0.84 |
  | US500 (SPY) | 236 | | +0.91 |
  | US30 (DIA) | 274 | | +0.87 |
  | US2000 (IWM) | 213 | | +0.83 |
  | XAUUSD (GLD) | 176 | 141 | +0.07 |
  | GER40 (EWG) | 160 | 63 | +0.73 |
  | UK100 (EWU) | 164 | 68 | +0.71 |
  | JP225 (EWJ) | 190 | 89 | +0.68 |
  | AUS200 (EWA) | 194 | 105 | +0.73 |

  Sessions with at least one signal: B0 519, B1 660, B2 789, B3 904.

  So gold is unrelated to the US indices; the four country funds are
  related to them (0.68 to 0.73) but less than the US indices are to
  each other. The lists were fixed before this table was made and were
  not changed after it. (The session's record shows that order. Git
  cannot: this commit is the study's first.)
* **A run on a made-up market, not market data.** The script runs end
  to end on nine invented price series
  (`tests/test_ftmo_breadth.py`). It says nothing about real markets.
* The broad history of these markets since 2011 is public knowledge
  (gold's rise since 2024, for one). The lists were not chosen from it
  and the rule is unchanged.
* **No account has been run on any of the five new markets**, alone or
  in a list. No trade, payoff or pass rate on them is known.

## Reported

For B0 to B3:

* **Per trade**, from the continuous account: the columns of the slots
  note, plus the payoff's standard error and the largest total position
  (open units at their entry prices, as a multiple of the balance, at a
  close).
* **Signals**: the slots note's table.
* **Per market inside each list**: trades, the share reaching +1R
  before the stop, payoff per trade with its standard error, sum of R.
* **Each market alone**: the same rule and account with that one
  market. Reported, not judged. With some dozens of trades per market
  the standard error of a payoff is expected to be about 0.1R to 0.2R,
  more than the whole system's payoff (+0.079R), so this table cannot
  rank markets.
* **FTMO**, by cohort and bound: the slots note's columns (passes
  within 6, 18 and 36 months and within the data, breached, frozen,
  stuck, still trading, days to pass, the main failure, funded
  survival and return, attempts per pass).

## Pre-registered pass/fail

The slots note's rule, unchanged (`judge` in
`research/ftmo_slots_sizing.py`), with B0 as the baseline.

A list **beats B0** if both hold.

* **No worse anywhere.** In both cohorts (2011–18, 2019–26) and under
  both bounds, out of the same start dates:
  * its count of attempts that **breached** a rule is no higher;
  * its count passing **both phases within 18 months** is no lower;
  * its count passing **both phases within the data** is no lower.
* **Better somewhere.** In at least one cohort, under both bounds, it
  passes strictly more often: within 18 months, or within the data.

The pessimistic run is compared with B0's pessimistic run and the
optimistic with the optimistic. Frozen and stuck counts, the funded
figures and everything per market are reported, not judged.

If more than one list beats B0, the preferred one has the higher lowest
share passing within the data across the four cells, then the lower
highest breach share. A remaining tie goes to the list with fewer
markets.

**How much a pass would mean.** Three lists are judged, each in four
cells of about 350 attempts. "Better somewhere" can be met by a margin
of a single attempt, and a margin that small is within noise. The
verdict table shows every margin. So a pass makes a list a candidate
and nothing more, and the next step is a new note with its own rule
fixed before its run.

## What happens next

* **A list beats B0.** It is a candidate, not a change. Next, in this
  order:
  1. the same test on FTMO's own daily bars for the new symbols,
     exported from the operator's MetaTrader, in a new note (the limits
     above are why);
  2. the port into the bot as a setting, switched off: symbols, each
     market's trading hours against FTMO's two-hour rule, contract
     sizes, swaps, the replay audit, review;
  3. the operator's order to switch it on.
* **No list beats B0.** The bot keeps its four markets. The numbers go
  to the operator. No other list is tried on this data.
  * For gold the proxy is clean. A fail of B1 is taken as it stands.
  * For the country lists the funds carry handicaps (limits 1, 2 and
    4). A fail of B2 or B3 says the funds show no gain. Whether FTMO's
    own bars would is step 1's question; it is asked only on the
    operator's order.
* **If the adjusted rows are added later** and disagree with the judged
  rows:
  * judged fail, adjusted pass: the funds cannot settle the question.
    It is reported as such and is not a pass.
  * judged pass, adjusted fail: the pass hangs on the ex-date drops. It
    stays a pass by the rule and is flagged.
* A failed rule is not adopted by judgment. Only the operator's
  explicit order overrides it, and the note records it.

## Checks

* **Before the real run** (checked on every run; a failed check stops
  it, also under `python -O`):
  * the nine files are the ones named under "Data", by sha256;
  * each new file has exactly the four's sessions;
  * B0 through the new script reproduces every published cell of
    W2+S2: the per-trade row under both bounds, the signals row, the
    FTMO row of every cohort and bound, the verdict counts, the number
    of start dates;
  * the account with the added diagnostic (the largest total position)
    makes W2+S2's trades, trade for trade;
  * the signals counted from the prices are the signals the account
    counts.
* **During every run:** never more than two positions with a stop under
  their entry at an entry, and an entry's risk never over its limits
  (assertions of the slots script's account, which every list runs
  through). One position per market holds by construction: the account
  keeps its positions by market.
* **The published cells** in the script are checked against the text of
  `research/ftmo_slots_sizing.md` by a test.
* **The script:** new, `research/ftmo_breadth.py`, committed with this
  note, before the run. It imports `research/ftmo_slots_sizing.py`
  (sha256
  `203706b9a0c2cbc87cc454bb5121305916554110a127c09957005a17a5c9b562`)
  and through it the earlier scripts, all unchanged, and runs the same
  account and FTMO functions.
* **Tests:** `tests/test_ftmo_breadth.py`, on made-up markets: the
  lists; the loading and its refusal of another calendar or other
  files; the adjustment; the B0 check catching a changed cell and
  stopping the run before any new market; `--check-only` running the
  four indices only; the start dates; the verdict rows and the
  tie-break; end-to-end runs with and without the distributions.
* **Run on the data before this note was committed:** only
  `--check-only`. It runs B0 (already published) and the table under
  "What was known before". It passed.

## Not tested here

* Other markets: EU50, FRA40, SPN35, N25, HK50, oil, currencies.
* More or fewer than two positions at risk, or another order than the
  lowest RSI(2) first.
* Rule numbers set per market.
* FTMO's own bars. That is step 1 above and needs the operator's
  MetaTrader.

Results are appended below under a dated heading. Nothing above is
edited.

## Results — 2026-11-11

**How it was run.**

* Command: `python -B -I research/ftmo_breadth.py --data-dir <dir>
  --extra-dir <dir>`. It took 1 minute 48 seconds on four cores.
* The note, the script and its tests were committed and pushed first
  (commit `1dd00e2`, 22:36 UTC); the run started after that (22:36:42
  UTC).
* Data: the nine files named under "Data". The script checked each
  file's sha256 before anything else.
* Script: sha256 `3e0d84d73d2ab465f521f69e4e7d8c102afda558922f5240d540f95ec50aec28`,
  unchanged since that commit.
* One run. Nothing was changed after it. No `--div-dir`: there are no
  adjusted rows.

Common dates 2011-03-23 → 2026-10-29; continuous account 2012-01-06 → 2026-10-29; start dates (2011–18 / 2019–26): 352 / 368 evaluations. Checks passed: the nine files are the note's (sha256); each new file has exactly the four indices' sessions; B0 through this script reproduces every published cell of W2+S2 (per trade, signals, FTMO, the verdict counts).

* **B0**: US100, US500, US30, US2000 (the bot today)
* **B1**: B0 + XAUUSD
* **B2**: B0 + GER40, UK100, JP225, AUS200
* **B3**: B0 + all five

**What the prices alone show** (sessions from the first trading day on; no account is involved). A signal: close over the 200-day average and RSI(2) under 10.

| market | signals | … on sessions with no signal in any US index | average correlation of daily returns with the (other) US indices |
|---|---|---|---|
| US100 (QQQ) | 267 |  | +0.84 |
| US500 (SPY) | 236 |  | +0.91 |
| US30 (DIA) | 274 |  | +0.87 |
| US2000 (IWM) | 213 |  | +0.83 |
| XAUUSD (GLD) | 176 | 141 | +0.07 |
| GER40 (EWG) | 160 | 63 | +0.73 |
| UK100 (EWU) | 164 | 68 | +0.71 |
| JP225 (EWJ) | 190 | 89 | +0.68 |
| AUS200 (EWA) | 194 | 105 | +0.73 |

Sessions with at least one signal, of 3725: B0 519, B1 660, B2 789, B3 904.

**Per trade** (continuous account; trades open at the end left out):

| list | bound | trades | trades per year | TP1 before stop | P&L win rate | avg win (R) | avg loss (R) | payoff (R/trade) | avg first risk | median sessions held | most open at once | CAGR | max DD | payoff's standard error | largest total position (× balance) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B0 | pessimistic | 214 | 14.4 | 58.9% | 58.9% | +0.92 | -1.13 | +0.079 | 2.45% | 22 | 4 | +1.4% | 37.3% | ±0.073 | 3.24 |
| B0 | optimistic | 214 | 14.4 | 58.9% | 58.9% | +0.92 | -1.13 | +0.079 | 2.45% | 22 | 4 | +1.4% | 37.3% | ±0.073 | 3.24 |
| B1 | pessimistic | 244 | 16.5 | 57.4% | 57.4% | +0.94 | -1.15 | +0.050 | 2.40% | 22 | 5 | +1.2% | 37.5% | ±0.071 | 2.72 |
| B1 | optimistic | 244 | 16.5 | 57.4% | 57.4% | +0.95 | -1.15 | +0.055 | 2.40% | 22 | 5 | +1.3% | 37.5% | ±0.072 | 2.72 |
| B2 | pessimistic | 288 | 19.4 | 52.8% | 52.8% | +0.89 | -1.17 | -0.087 | 2.39% | 20 | 8 | -5.4% | 65.7% | ±0.064 | 3.36 |
| B2 | optimistic | 288 | 19.4 | 52.8% | 52.8% | +0.89 | -1.17 | -0.085 | 2.39% | 20 | 8 | -5.3% | 65.1% | ±0.064 | 3.36 |
| B3 | pessimistic | 301 | 20.3 | 52.8% | 52.8% | +0.92 | -1.18 | -0.071 | 2.38% | 21 | 7 | -4.6% | 70.2% | ±0.064 | 3.81 |
| B3 | optimistic | 301 | 20.3 | 52.8% | 52.8% | +0.92 | -1.18 | -0.069 | 2.38% | 21 | 7 | -4.5% | 69.7% | ±0.064 | 3.81 |

**Signals** (continuous account, pessimistic bound; 'free': a position whose stop is at or above its entry):

| list | signals | planned for the next open | entered | not taken: market already held | … by a free position | not taken: slots full | … while a free position was open | … while every open position was free | sessions with two or more positions open |
|---|---|---|---|---|---|---|---|---|---|
| B0 | 990 | 216 | 216 | 550 | 191 | 224 | 45 | 5 | 2428 of 3725 |
| B1 | 1166 | 246 | 246 | 605 | 203 | 315 | 98 | 6 | 2616 of 3725 |
| B2 | 1698 | 290 | 290 | 656 | 241 | 752 | 400 | 14 | 2642 of 3725 |
| B3 | 1874 | 303 | 303 | 675 | 224 | 896 | 518 | 14 | 2776 of 3725 |

**Per market, inside each list** (continuous account, pessimistic bound; payoff ± its standard error):

| list | market | trades | TP1 before stop | payoff (R/trade) | sum of R |
|---|---|---|---|---|---|
| B0 | US100 (QQQ) | 59 | 56% | +0.060 ± 0.152 | +3.5 |
| B0 | US500 (SPY) | 55 | 55% | +0.048 ± 0.149 | +2.6 |
| B0 | US30 (DIA) | 58 | 60% | +0.038 ± 0.132 | +2.2 |
| B0 | US2000 (IWM) | 42 | 67% | +0.204 ± 0.151 | +8.6 |
| B1 | US100 (QQQ) | 54 | 57% | +0.082 ± 0.160 | +4.4 |
| B1 | US500 (SPY) | 44 | 50% | -0.086 ± 0.163 | -3.8 |
| B1 | US30 (DIA) | 55 | 60% | +0.089 ± 0.154 | +4.9 |
| B1 | US2000 (IWM) | 45 | 62% | +0.114 ± 0.148 | +5.1 |
| B1 | XAUUSD (GLD) | 46 | 57% | +0.035 ± 0.175 | +1.6 |
| B2 | US100 (QQQ) | 49 | 53% | +0.020 ± 0.169 | +1.0 |
| B2 | US500 (SPY) | 34 | 59% | +0.071 ± 0.181 | +2.4 |
| B2 | US30 (DIA) | 45 | 51% | -0.175 ± 0.149 | -7.9 |
| B2 | US2000 (IWM) | 27 | 52% | -0.162 ± 0.185 | -4.4 |
| B2 | GER40 (EWG) | 33 | 45% | -0.186 ± 0.214 | -6.1 |
| B2 | UK100 (EWU) | 32 | 50% | -0.151 ± 0.200 | -4.8 |
| B2 | JP225 (EWJ) | 35 | 54% | -0.060 ± 0.198 | -2.1 |
| B2 | AUS200 (EWA) | 33 | 58% | -0.094 ± 0.171 | -3.1 |
| B3 | US100 (QQQ) | 42 | 55% | +0.044 ± 0.185 | +1.8 |
| B3 | US500 (SPY) | 32 | 53% | -0.021 ± 0.193 | -0.7 |
| B3 | US30 (DIA) | 40 | 50% | -0.183 ± 0.161 | -7.3 |
| B3 | US2000 (IWM) | 28 | 50% | -0.189 ± 0.181 | -5.3 |
| B3 | XAUUSD (GLD) | 40 | 57% | +0.086 ± 0.191 | +3.5 |
| B3 | GER40 (EWG) | 28 | 43% | -0.251 ± 0.234 | -7.0 |
| B3 | UK100 (EWU) | 27 | 48% | -0.174 ± 0.221 | -4.7 |
| B3 | JP225 (EWJ) | 35 | 54% | -0.046 ± 0.201 | -1.6 |
| B3 | AUS200 (EWA) | 29 | 62% | -0.000 ± 0.184 | -0.0 |

**Each market alone** (the same rule and account with that one market; reported, not judged):

| market | bound | trades | TP1 before stop | payoff (R/trade) | sum of R |
|---|---|---|---|---|---|
| US100 (QQQ) | pessimistic | 72 | 60% | +0.176 ± 0.131 | +12.7 |
| US100 (QQQ) | optimistic | 72 | 60% | +0.176 ± 0.131 | +12.7 |
| US500 (SPY) | pessimistic | 67 | 57% | +0.078 ± 0.136 | +5.2 |
| US500 (SPY) | optimistic | 67 | 58% | +0.097 ± 0.133 | +6.5 |
| US30 (DIA) | pessimistic | 74 | 61% | +0.074 ± 0.122 | +5.5 |
| US30 (DIA) | optimistic | 73 | 60% | +0.073 ± 0.125 | +5.3 |
| US2000 (IWM) | pessimistic | 56 | 66% | +0.235 ± 0.137 | +13.1 |
| US2000 (IWM) | optimistic | 55 | 65% | +0.228 ± 0.140 | +12.5 |
| XAUUSD (GLD) | pessimistic | 55 | 60% | +0.099 ± 0.157 | +5.4 |
| XAUUSD (GLD) | optimistic | 55 | 60% | +0.098 ± 0.157 | +5.4 |
| GER40 (EWG) | pessimistic | 58 | 45% | -0.165 ± 0.160 | -9.6 |
| GER40 (EWG) | optimistic | 57 | 44% | -0.202 ± 0.158 | -11.5 |
| UK100 (EWU) | pessimistic | 57 | 53% | -0.082 ± 0.150 | -4.7 |
| UK100 (EWU) | optimistic | 57 | 53% | -0.082 ± 0.150 | -4.7 |
| JP225 (EWJ) | pessimistic | 63 | 62% | +0.099 ± 0.140 | +6.3 |
| JP225 (EWJ) | optimistic | 63 | 62% | +0.099 ± 0.140 | +6.3 |
| AUS200 (EWA) | pessimistic | 61 | 59% | +0.005 ± 0.127 | +0.3 |
| AUS200 (EWA) | optimistic | 61 | 59% | +0.005 ± 0.127 | +0.3 |

**FTMO** (cohorts by start date; columns as in `research/ftmo_slots_sizing.md`). Frozen: flat at the end with under 0.05% of room. Stuck: flat at the end and a new entry may risk under 0.5%. Attempts per pass counts a stuck attempt as lost.

| list | period | P1 passed | both ≤6 mo | both ≤18 mo | both ≤36 mo | both, ever | breached | frozen | stuck | still trading | days to pass (p25 / median / p75) | main failure | funded 1y survival | funded 1y return | attempts per pass |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B0 pessimistic | 2011–18 | 45% | 5% | 33.8% | 35.2% | 35.2% | 21.0% | 43.8% | 43.8% | 0.0% | 209 / 260 / 322 | P1 unfinished 35% | 77% | -6.7% | 2.84 |
| B0 pessimistic | 2019–26 | 52% | 9% | 30.4% | 42.4% | 42.4% | 8.4% | 38.3% | 38.3% | 10.9% | 214 / 360 / 602 | P1 unfinished 41% | 92% | +1.7% | 2.10 |
| B0 optimistic | 2011–18 | 48% | 8% | 34.1% | 35.5% | 35.5% | 19.3% | 45.2% | 45.2% | 0.0% | 188 / 237 / 302 | P1 unfinished 34% | 77% | -6.4% | 2.82 |
| B0 optimistic | 2019–26 | 58% | 12% | 39.4% | 51.9% | 51.9% | 7.3% | 31.8% | 31.8% | 9.0% | 192 / 309 / 519 | P1 unfinished 34% | 92% | +1.7% | 1.75 |
| B1 pessimistic | 2011–18 | 41% | 3% | 28.4% | 28.4% | 28.4% | 16.5% | 55.1% | 55.1% | 0.0% | 250 / 313 / 401 | P1 unfinished 44% | 85% | -8.2% | 3.52 |
| B1 pessimistic | 2019–26 | 61% | 12% | 31.8% | 31.8% | 31.8% | 4.9% | 55.4% | 55.4% | 7.9% | 156 / 219 / 320 | P1 unfinished 35% | 95% | +4.1% | 2.90 |
| B1 optimistic | 2011–18 | 43% | 3% | 31.2% | 31.2% | 31.2% | 16.2% | 52.6% | 52.6% | 0.0% | 232 / 298 / 359 | P1 unfinished 41% | 85% | -8.2% | 3.20 |
| B1 optimistic | 2019–26 | 62% | 16% | 39.4% | 39.4% | 39.4% | 4.9% | 48.1% | 48.1% | 7.6% | 143 / 216 / 296 | P1 unfinished 33% | 95% | +4.1% | 2.34 |
| B2 pessimistic | 2011–18 | 33% | 7% | 13.9% | 13.9% | 13.9% | 27.3% | 58.8% | 58.8% | 0.0% | 153 / 180 / 232 | P1 unfinished 50% | 72% | -8.6% | 7.18 |
| B2 pessimistic | 2019–26 | 39% | 8% | 16.6% | 16.6% | 16.6% | 42.9% | 34.5% | 34.5% | 6.0% | 122 / 189 / 336 | P1 daily_loss 31% | 46% | -3.7% | 5.67 |
| B2 optimistic | 2011–18 | 34% | 11% | 15.1% | 15.1% | 15.1% | 26.1% | 58.8% | 58.8% | 0.0% | 115 / 155 / 186 | P1 unfinished 50% | 72% | -8.6% | 6.64 |
| B2 optimistic | 2019–26 | 39% | 9% | 17.4% | 17.4% | 17.4% | 39.9% | 37.0% | 37.0% | 5.7% | 117 / 168 / 321 | P1 daily_loss 30% | 46% | -3.9% | 5.42 |
| B3 pessimistic | 2011–18 | 26% | 4% | 9.9% | 9.9% | 9.9% | 27.3% | 62.8% | 62.8% | 0.0% | 156 / 192 / 369 | P1 unfinished 53% | 79% | -8.6% | 10.06 |
| B3 pessimistic | 2019–26 | 30% | 12% | 23.4% | 23.4% | 23.4% | 31.0% | 41.0% | 41.0% | 4.6% | 127 / 177 / 268 | P1 unfinished 42% | 59% | -5.5% | 4.08 |
| B3 optimistic | 2011–18 | 27% | 9% | 12.2% | 12.2% | 12.2% | 27.6% | 60.2% | 60.2% | 0.0% | 110 / 155 / 184 | P1 unfinished 52% | 79% | -8.6% | 8.19 |
| B3 optimistic | 2019–26 | 32% | 14% | 25.3% | 25.3% | 25.3% | 28.8% | 41.8% | 41.8% | 4.1% | 112 / 143 / 280 | P1 unfinished 42% | 59% | -5.5% | 3.80 |

### Verdict against B0, by the pre-registered rule

| list | cohort | bound | breached: list vs B0 | both ≤18 mo | both, ever | no worse |
|---|---|---|---|---|---|---|
| B1 | 2011–18 | pessimistic | 58/352 (16.5%) vs 74/352 (21.0%) | 100/352 (28.4%) vs 119/352 (33.8%) | 100/352 (28.4%) vs 124/352 (35.2%) | no |
| B1 | 2011–18 | optimistic | 57/352 (16.2%) vs 68/352 (19.3%) | 110/352 (31.2%) vs 120/352 (34.1%) | 110/352 (31.2%) vs 125/352 (35.5%) | no |
| B1 | 2019–26 | pessimistic | 18/368 (4.9%) vs 31/368 (8.4%) | 117/368 (31.8%) vs 112/368 (30.4%) | 117/368 (31.8%) vs 156/368 (42.4%) | no |
| B1 | 2019–26 | optimistic | 18/368 (4.9%) vs 27/368 (7.3%) | 145/368 (39.4%) vs 145/368 (39.4%) | 145/368 (39.4%) vs 191/368 (51.9%) | no |
| **B1** | | | | | | no worse anywhere: no; better somewhere: no |
| B2 | 2011–18 | pessimistic | 96/352 (27.3%) vs 74/352 (21.0%) | 49/352 (13.9%) vs 119/352 (33.8%) | 49/352 (13.9%) vs 124/352 (35.2%) | no |
| B2 | 2011–18 | optimistic | 92/352 (26.1%) vs 68/352 (19.3%) | 53/352 (15.1%) vs 120/352 (34.1%) | 53/352 (15.1%) vs 125/352 (35.5%) | no |
| B2 | 2019–26 | pessimistic | 158/368 (42.9%) vs 31/368 (8.4%) | 61/368 (16.6%) vs 112/368 (30.4%) | 61/368 (16.6%) vs 156/368 (42.4%) | no |
| B2 | 2019–26 | optimistic | 147/368 (39.9%) vs 27/368 (7.3%) | 64/368 (17.4%) vs 145/368 (39.4%) | 64/368 (17.4%) vs 191/368 (51.9%) | no |
| **B2** | | | | | | no worse anywhere: no; better somewhere: no |
| B3 | 2011–18 | pessimistic | 96/352 (27.3%) vs 74/352 (21.0%) | 35/352 (9.9%) vs 119/352 (33.8%) | 35/352 (9.9%) vs 124/352 (35.2%) | no |
| B3 | 2011–18 | optimistic | 97/352 (27.6%) vs 68/352 (19.3%) | 43/352 (12.2%) vs 120/352 (34.1%) | 43/352 (12.2%) vs 125/352 (35.5%) | no |
| B3 | 2019–26 | pessimistic | 114/368 (31.0%) vs 31/368 (8.4%) | 86/368 (23.4%) vs 112/368 (30.4%) | 86/368 (23.4%) vs 156/368 (42.4%) | no |
| B3 | 2019–26 | optimistic | 106/368 (28.8%) vs 27/368 (7.3%) | 93/368 (25.3%) vs 145/368 (39.4%) | 93/368 (25.3%) vs 191/368 (51.9%) | no |
| **B3** | | | | | | no worse anywhere: no; better somewhere: no |

**No list beats B0** by the rule.

## Verdict (2026-11-11)

**No list beats B0. The bot keeps its four markets.** Nothing is
ported. The hypothesis is refuted on these proxies.

## What was learned

1. **Gold (B1) makes the account safer and slower. It fails on passes.**
   * Breaches fall in every cell: 16.2–16.5% against 19.3–21.0%
     (2011–18 starts) and 4.9% against 7.3–8.4% (2019–26).
   * Passes within the data fall in every cell: 28.4–31.2% against
     35.2–35.5%, and 31.8–39.4% against 42.4–51.9%.
   * Within 18 months it passes less often for 2011–18 starts (100 and
     110 of 352 against 119 and 120) and about as often for 2019–26
     (117 against 112, 145 against 145 of 368).
   * More attempts end frozen: 52.6–55.1% and 48.1–55.4%, against
     43.8–45.2% and 31.8–38.3%.
   * Per trade: 244 trades instead of 214, at +0.050R to +0.055R
     instead of +0.079R. The gold trades inside B1: 46, at +0.035R ±
     0.175. Gold alone: 55 trades, +0.099R ± 0.157.
   * Gold's proxy is clean, so by this note the fail is taken as it
     stands.
2. **The country funds (B2, B3) lose.**
   * B2 breaches 26.1–27.3% (2011–18) and 39.9–42.9% (2019–26) of
     attempts, against 19.3–21.0% and 7.3–8.4%. It passes within the
     data in 13.9–15.1% and 16.6–17.4%, against 35.2–35.5% and
     42.4–51.9%.
   * B3 breaches 27.3–27.6% and 28.8–31.0%, and passes in 9.9–12.2%
     and 23.4–25.3%.
   * The continuous account loses money: −0.087R to −0.069R a trade,
     −5.4% to −4.5% a year, with drawdowns of 65–70%. B0 makes +0.079R
     a trade and +1.4% a year, with a 37% drawdown.
   * Alone, under this rule: Germany −0.165R to −0.202R ± 0.16, the UK
     −0.082R ± 0.15, Australia +0.005R ± 0.13, Japan +0.099R ± 0.14.
   * Inside the lists the new markets also take the slots when the US
     indices signal. Signals not taken because the slots were full go
     from 224 to 752 (B2) and 896 (B3). The US indices make 155 trades
     in B2 instead of 214, and those sum to −8.9R instead of +16.9R.
   * For 2019–26 starts, B2's main failure is the daily-loss limit
     (30–31% of attempts). Up to eight positions are open at once.
   * A funded B2 account survives a year in 46% of 2019–26 starts,
     against 92% for B0.
3. **No single market's payoff can be told from zero.**
   * The standard errors are 0.12R to 0.23R per market, as expected.
     The US indices alone make +0.07R to +0.24R a trade; none is two
     standard errors from zero.
   * The same holds for the rule as the bot runs it: +0.079R ± 0.073 a
     trade over 214 trades, about one standard error from zero.
   * This note does not show why the US trades that B2 still takes do
     worse than B0's (−8.9R over 155 trades against +16.9R over 214).
   * So the per-market tables are not used to pick markets, and no
     list is built from them.
4. **What the fail means for the country lists.**
   * The funds' handicaps (distributions, currency, hours) were not
     taken out and were not measured. This note cannot say how much of
     the gap they explain. The gap is large.
   * By this note the fail stands for the funds. A test on FTMO's own
     bars is run only on the operator's order.
5. **Margin.** The largest total position at a close was 3.24× the
   balance for B0 and 2.72× to 3.81× for the other lists.

## What happens next (2026-11-11)

* The bot is unchanged: US100, US500, US30 and US2000.
* No other list is tried on this data.
* More or fewer than two positions at risk, and another order than the
  lowest RSI(2) first, stay untested. Each would be a new note.
