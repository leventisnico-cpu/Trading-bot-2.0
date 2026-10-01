# Research note — daily-execution candidates on Astral (Sep 2026)

Operator asked for automated daily/intraday execution in the spirit of
Renaissance's Medallion Fund. Medallion's edge (thousands of weak signals
across thousands of instruments, leverage, execution infrastructure) is
not reproducible in a single TFSA. What this project adopts is its
**process**: many small statistically-motivated signals, canonical
parameters fixed in advance, strict out-of-sample folds, full costs, and
losers kept. Every candidate below was written down before any number was
seen; none was re-run with different parameters.

## Hypotheses
- **A — RSI(2) reversion (SPY, daily).** Buy when RSI(2) < 10 and close >
  SMA(200); sell when close > SMA(5). Short-term oversold dips in an
  uptrend revert.
- **B — IBS reversion (SPY, daily).** Internal bar strength
  IBS = (C−L)/(H−L). Buy when IBS < 0.2, sell when IBS > 0.8.
- **C — intraday z-score reversion (SPY, 5-minute bars).** Buy when the
  close is > 2 standard deviations below its 20-bar mean between 09:45 and
  15:30 ET; exit at z > 0 or 15:50 ET. Never holds overnight.
- **D — cross-sectional short-term reversal (20 US large caps, daily).**
  Each trading day hold, equal weight, the 5 stocks with the worst 5-day
  return. The retail analogue of stat-arb reversal.

## Universe
A–C: SPY. D: AAPL MSFT AMZN GOOGL META NVDA JPM JNJ XOM PG V UNH HD KO
PEP MRK CVX WMT BAC CSCO — chosen with today's knowledge, so it carries
survivorship bias; the control below exists to measure that.

## Data source
Astral's historical bars (daily from 2007-09; 5-minute capped at 40,000
bars ≈ Oct 2024 onward; D limited to 2014-04 onward by GOOGL coverage).
Signals evaluate on bar close and fill at the next bar's open.

## Cost model
1 bp commission + 2 bp slippage per side on every order, candidates and
benchmarks alike. $100,000 starting capital.

## Walk-forward folds
- A, B: 2007-09→2013-12, 2014-01→2019-12, 2020-01→2026-09, plus full.
- C: full sample only (≈2 years of 5-minute history).
- D: 2014-04→2018-06, 2018-07→2022-08, 2022-09→2026-09, plus full.

## Benchmark
A–C: SPY buy-and-hold. D: the **same 20 stocks, equal weight, rebalanced
monthly** (so any edge must come from the signal, not the stock list);
SPY shown for reference.

## Pre-registered pass/fail
PASS only if final wealth beats the benchmark in ≥ 2 of 3 folds AND on the
full sample (same rule as `scripts/expectancy.py`).

## Result

| Candidate | Fold 1 | Fold 2 | Fold 3 | Full sample | Verdict |
|---|---|---|---|---|---|
| A RSI(2) | — | — | — | +64% vs SPY +416%, maxDD −14% | **FAIL** |
| B IBS | **+88%** vs +24% | +25% vs +74% | +68% vs +134% | +296% vs +416%, maxDD −27% vs −56% | **FAIL (1/3)** |
| C intraday 5m | — | — | — | **−30%** in 2 yrs, 594 trades, Sharpe −3.2 | **FAIL** |
| D 20-stock reversal | **+143%** vs +106% | **+113%** vs +65% | +85% vs +111% | **+891%** vs +644% (SPY +314%) | **PASS (2/3 + full)** |

Notes:
- C: intraday reversion on SPY does not survive 3 bp/side. Day trading a
  single index ETF is a cost-losing proposition at retail.
- B halves the 2008 drawdown but sits in cash through bull runs, so it
  loses on final wealth in 2 of 3 folds.
- D passes, with three caveats that must be resolved before real money:
  1. **Risk-adjusted it is not better**: full-sample Sharpe 0.92 vs 1.07
     for the control, max drawdown −38% vs −31%. The extra return comes
     with extra volatility from holding 5 names.
  2. **The latest fold lost** (2022-09→2026-09), consistent with the
     reversal premium decaying.
  3. **Fee realism**: ~20,850 orders in 12.5 years (~1,670/yr). At IBKR's
     $1 minimum per order that is ~$1,670/yr — about 1.7%/yr on $100k and
     far more on a smaller account — against an edge of ~2.8%/yr over the
     control. The 1 bp model understates this for small trims.
- Next step for D (new hypothesis, new note): trade only when the
  top-5 membership changes (no drift trims) and re-measure with a
  per-order $1 minimum at the account size actually intended.

## Addendum — the operator's real account size

The operator's intended capital is ~$1,200 CAD (~$870 USD). At that size
IBKR's $1 minimum per order is ~0.6% of a ~$170 position (D) and ~0.12%
of a one-share SPY order (B). Re-run 2014-04→2026-09 with those costs:

| Candidate | $870, realistic fees | SPY buy-and-hold |
|---|---|---|
| D 20-stock reversal (60 bp/order) | **−99.99%** (wiped out) | +314% |
| B IBS (12 bp/order) | **−2%** | +314% |

Neither strategy is viable below roughly six figures. At this size the
only approach that survives costs is buying and holding a broad index
(lump sum plus scheduled contributions).

## Addendum — TJR/ICT-style NY-open liquidity sweep (E)

Operator asked for a copy of TJR's day-trading approach. Mechanical,
long-only (TFSA) version on QQQ 5-minute bars, pre-registered: opening
range = 09:30–09:45 ET; between 09:45 and 11:00, a bar that trades below
the opening-range low and closes back above it triggers a buy; stop
−0.3%, target +0.6% (2R); flat at 15:50. Oct 2024 → Sep 2026 (5-minute
history cap), 324 trades:

| Costs | Result | Win rate | Profit factor |
|---|---|---|---|
| Institutional (1 bp + 2 bp slippage), $100k | **−14%** | 38% | 0.77 |
| Real account (~$870, 18 bp/order ≈ $1 min + 2 bp) | **−70%** | 30% | 0.12 |

FAIL — the rule loses before costs, and the $1 minimum turns a slow bleed
into a wipe-out at this account size. Discretionary traders apply
judgement this mechanical rule does not capture; that judgement cannot be
backtested, which is exactly why it cannot be trusted with the account.

## Addendum — popular Astral Explore strategies, re-tested

Explore's "popular" list (≥25%/yr advertised) is mostly crypto and spot
gold, which a TFSA cannot hold, and several entries show impossible
statistics (Sharpe > 100). The two stock strategies were re-tested:

- **AMD Bollinger mean reversion** (15m; advertised +52% Dec 2025→Aug
  2026, zero costs). Out of sample 2021-01→2025-11 at ~$870 with $1-min
  fees: **−27%, max drawdown −70%**, vs **AMD buy-and-hold +118%**.
  Overfit to its publication window.
- **GOOG 15m ORB 3RR** (advertised +83%): Astral's own engine refuses to
  reproduce it ("historical performance cannot be reproduced by the
  current engine"), so the advertised number is unverifiable.

## Addendum — "copy the traders who turned small accounts into millions" (F)

Operator asked for ≥8% per trade by copying small-account-to-millions
traders (Kullamägi/Qullamaggie, Minervini, Zanger, O'Neil, Darvas, Ryan).
Their shared method is the momentum breakout: strong uptrend, tight
consolidation, breakout on volume, cut losses at 7–8%, trail winners.
F encodes that with canonical published rules on 8 growth stocks (NVDA
AMD TSLA META NFLX AVGO MU CRM), daily bars, 45% per position, stop −8%,
exit on a close below the 20-day SMA. 2014-01 → 2026-09, 50 trades:

| Run | Result | Win rate | Avg per trade | Profit factor |
|---|---|---|---|---|
| $100k, 1+2 bp | +93% (5.8%/yr), maxDD −23% | 54% | **+3.3%** | 2.27 |
| ~$870, 25+2 bp ($1 min) | +74% (4.9%/yr), maxDD −23% | 50% | **+2.8%** | 1.99 |
| Control: hold the same 8 stocks, equal weight | **+8,085%** (41%/yr), maxDD −51% | — | — | — |
| SPY buy-and-hold (2014-04 →) | +314% | — | — | — |

Findings: the first candidate here with positive expectancy that survives
small-account fees (only ~4 trades a year). It does not reach 8% per
trade, and it loses badly to simply holding the same stocks — the
control's result is hindsight: these 8 names were chosen because they
became the decade's winners. That is also the core problem with the
"small account to millions" stories: the survivors are visible, the far
larger number who ran the same method and failed are not.

Astral objects: F=37979, control F=37980, E=37962, AMD=37964, GOOG=37965. A=37934, B=37936 (saved 5777), C=37935, D=37938
(saved 5778), control=37940, SPY benchmark=37638.

## Addendum — "Wall Street Income Masterclass" 5-step system (G)

Operator supplied a 10-slide deck (Andrew Antiles, "Wall Street Income
Masterclass") described as the system hedge-fund traders use. It contains
**no entry rule** — only sizing and exit management:

1. Same size: every trade is 30% of the account.
2. Same risk: stop −10% (so 3% of the account at risk).
3. Sell 1/2 at +10%, move the stop to break-even.
4. Sell 1/4 at +12–15%, move the stop to +10%.
5. Never sell the last 1/4 manually; trail the stop up.

Claims checked before testing:
- "Lose 33 in a row to blow up": false arithmetic. 3% losses compound;
  after 33 straight losses 37% of the account remains, and a 50% drawdown
  takes 23 losses. More importantly, the deck's risk math assumes every
  stop fills at −10%; gaps through stops do not.
- "+517.6% (Jan–Aug 2026) trading SPY": SPY itself rose 13.4% over that
  window (local data). At 30% position size with a 10% first target, a
  trade in SPY *shares* cannot produce that: replaying the 5 exit steps
  from every SPY entry day 1999–2026 (6,662 trades, close-only) gives a
  median holding period of 176 trading days (~8 months), an average of
  +5.1% per trade (vs +7.9% for simply holding SPY over the same windows),
  and +1.5% per trade at the account level. The headline number implies
  options/leverage or a selected sample; it is not reproducible from the
  rules shown.

Test: the deck's exits are orthogonal to our entries, so they were bolted
onto F's entry signal (first breakout day only), pre-registered, no tuning.
Each signal buys three tranches: 1/2 with TP +10% / SL −10%; 1/4 with TP
+13.5% and SL −10% → break-even once +10% is reached; 1/4 with SL −10% →
break-even at +10% → +10% at +20% → trailing 10% (of entry) below the high.
G = 30% per trade (as the deck says); G45 = 45% per trade (F's exposure,
isolates the exit logic from the size change). 2014-01 → 2026-09.

| Run | Return | CAGR | Max DD | Sharpe | Win | Avg/trade | PF |
|---|---|---|---|---|---|---|---|
| F (live on paper), $100k, 1+2 bp | +93% | 5.8% | −23.2% | 0.48 | 54% | +3.3% | 2.27 |
| G 30%, $100k, 1+2 bp | +71% | 4.7% | −15.2% | 0.57 | 62% | +3.1% | 1.99 |
| **G45, $100k, 1+2 bp** | **+121%** | **7.1%** | **−16.7%** | **0.63** | 62% | +3.7% | 2.25 |
| F, $870, 25+2 bp | +74% | 4.9% | −23% | — | 50% | +2.8% | 1.99 |
| G 30%, $870, 115+2 bp ($1 min on 1/4 lots) | +17% | 1.3% | −17.2% | 0.20 | 54% | +0.8% | 1.22 |
| G45, $870, 77+2 bp | +58% | 4.0% | −19.7% | 0.39 | 57% | +2.2% | 1.60 |

Walk-forward, G45 vs F ($100k, 1+2 bp; each window includes 277 bars of
indicator warm-up so trading starts at the fold boundary):

| Fold | G45 | F | Winner |
|---|---|---|---|
| 2014-04 → 2018-06 | +13.5% (DD −20.7%) | +9.8% (DD −12.2%) | G45 |
| 2018-07 → 2022-08 | +34.6% (DD −8.9%) | +22.5% (DD −23.2%) | G45 |
| 2022-09 → 2026-09 | +28.4% (DD −13.6%) | +35.3% (DD −12.3%) | F |
| Full sample | +121% | +93% | G45 |

Verdict: **PASS at institutional costs (2/3 folds + full sample)** — the
deck's scale-out/break-even exits improve F's entries on return and
drawdown when commissions are negligible. **FAIL at the operator's
current $870**: splitting every trade into three exits multiplies IBKR's
$1-minimum fees, and both G variants lose to F after realistic costs.
(The flat-bps fee model is approximate; it overstates the cost of the
merged entry order and understates small partial sells.) F stays the
paper deployment at $870; G45 becomes the candidate once position slices
are large enough that $1 per partial sell is immaterial (roughly $5k+
account, where a 1/4 slice is ~$560 and $1 ≈ 0.2%).

Astral objects: G=38695, G45=38696. Backtests: G $100k bt_e077665e44ae801f,
G $870 bt_b0af823ad862eb2b / bt_d0d89380277cdea3, G45 $100k
bt_c512476acbf371a5, G45 $870 bt_74a73007b76f4ef7, folds G45
bt_ef8c70bb9705bd8d / bt_467da3f351bd3661 / bt_2bbc6110992868e5, folds F
bt_019bed65b0fb95fa / bt_f0c52b5d859a61bb / bt_23753e2df628b7d2.

## Addendum — trading bear markets too (G45B, inverse-ETF bear leg)

Operator asked for the strategy to trade bearish as well as bullish. The
account is a TFSA: short selling is not allowed (and Astral's builder is
long-only), so the only bearish instrument consistent with ORDERS.md
("stocks/ETFs only") is a **long position in an inverse ETF**. PSQ
(−1x Nasdaq-100, unleveraged, so no 3x decay) was chosen because the 8
G45 names are Nasdaq-100 growth stocks.

Pre-registered before any run (no tuning, no second variant):
- Longs: G45 unchanged.
- Bear regime: QQQ close < 200-day SMA AND 50-day SMA < 200-day SMA.
- Entry: first day the regime turns on → buy PSQ with 45% of equity
  (same exposure as one G45 trade), hard stop −8% from entry.
- Exit: QQQ closes back above its 50-day SMA (or the stop).
- Benchmark: G45 itself (the question is whether the bear leg adds value).
- Same windows and costs as the G45 test ($100k, 1+2 bp); PASS only if
  G45B beats G45 in ≥ 2 of 3 folds AND on the full sample.

| Window | G45B | G45 | Winner |
|---|---|---|---|
| 2014-04 → 2018-06 | +2.9% (DD −21.2%) | +13.5% (DD −20.7%) | G45 |
| 2018-07 → 2022-08 | +39.6% (DD −13.3%) | +34.6% (DD −8.9%) | G45B |
| 2022-09 → 2026-09 | +25.5% (DD −13.6%) | +28.4% (DD −13.6%) | G45 |
| Full 2014 → 2026-09 | +103% (DD −16.7%) | +121% (DD −16.7%) | G45 |

Verdict: **FAIL (1/3 folds, full sample loses).** The bear leg added 12
PSQ trades over 12 years; win rate fell from 62% to 54%. It paid only in
the 2018–2022 fold (the 2022 bear), and even there it *raised* that fold's
drawdown (−8.9% → −13.3%). Elsewhere QQQ dipped under its 200-day,
triggered the entry, and snapped back through the 50-day: whipsaw. It did
not lower the full-sample drawdown at all. G45 already defends in bear
markets by holding cash — its breakout filter requires an uptrend, which
is why its 2018–2022 drawdown was −8.9%. G45 stays on paper; G45B is not
deployed.

Astral objects: G45B=39265. Backtests: full bt_df5d0fd3ed7dbf01, folds
bt_d71f23d492dd9469 / bt_24002dd5d18a0588 / bt_81147788a1ac2137
(G45 baselines as in the G addendum).
