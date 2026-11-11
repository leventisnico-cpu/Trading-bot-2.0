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
