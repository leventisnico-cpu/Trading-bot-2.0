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

## Addendum — switch to tech/AI ETFs (E1 vs buy-and-hold BH5)

Operator asked to trade strong tech/AI ETFs instead of single stocks, and
to be able to short. Shorting is not possible in this setup: the IBKR
account is a TFSA (no short sales), the connected Moomoo account is a cash
account, and Astral's strategy builder is long-only. ETFs are fine in a
TFSA, so the ETF switch was tested.

Universe (pre-registered; liquid tech/AI ETFs with data back to 2013):
QQQ, XLK, SMH, SOXX, IGV. AI-only ETFs (BOTZ 2016, AIQ 2018) were left out
for lack of history across all three folds.
- E1 (trend, long-only): 20% per ETF, held while close > 200d SMA and
  50d SMA > 200d SMA; sold on a close below the 200d SMA. No tuning.
- BH5 (benchmark): the same 5 ETFs equal-weight, rebalanced monthly,
  always invested, started on E1's first eligible trading day.
- $100k, 1+2 bp. PASS if E1 beats BH5 in ≥ 2 of 3 folds AND full sample.

| Window | E1 trend | BH5 buy-and-hold | G45 (for reference) |
|---|---|---|---|
| 2014-01 → 2018-06 | +80% (DD −16.4%) | **+117%** (DD −17.9%) | +13.5% |
| 2018-04 → 2022-08 | +51% (DD −24.1%) | **+104%** (DD −34.3%) | +34.6% |
| 2022-06 → 2026-09 | +157% (DD −19.5%) | **+247%** (DD −27.6%) | +28.4% |
| Full 2014-11 → 2026-09 | +532% (16.8%/yr, DD −24.1%) | **+1,066%** (23.0%/yr, DD −40.1%) | +121% (7.1%/yr) |

Verdict: **E1 FAIL (0/3 folds, full sample loses).** The trend filter cuts
drawdowns by roughly 40% in every window but gives up about half the
return. Both ETF variants beat G45 by a wide margin. The strongest result
is simply holding the five ETFs. Caveat: hindsight. Tech was the best
sector of 2014–2026, and choosing "AI and tech" today uses that knowledge.
BH5's −40% drawdown (−34% in the 2022 fold) is the cost.
Practical note at ~$870: QQQ/SMH trade above $600 a share, so five equal
slots need fractional shares or fewer ETFs.

Astral objects: E1=39301, BH5=39302. Backtests: E1 full
bt_3339945348f5ca08, folds bt_5605eb5a07c28b95 / bt_e2e4d9dd32ce5230 /
bt_6d2a03e804896813; BH5 full bt_ec290157a2082cd0, folds
bt_1ef789ed40fb51ab / bt_5b04daf4e8ae1810 / bt_6634536e42346a76.

## Addendum — ride the strongest AI ETF (AIR1–AIR4 on SOXX)

Operator changed course: ride the AI gold rush in one ETF for as long as
the trend lasts, exit when it ends, and aim for a win rate of 70% or more.

Instrument pick (multi-period returns on 2026-10-01, Astral research):

| ETF | 6M | YTD | 1Y | 3Y | Note |
|---|---|---|---|---|---|
| **SOXX** | +70% | +91% | **+108%** | +263% | iShares semis; strongest unleveraged |
| SMH | +58% | +72% | +85% | +322% | VanEck semis, NVDA-heavy |
| XSD | +61% | +67% | +68% | +174% | equal-weight semis |
| XLK / VGT / IYW | +44–47% | +34–37% | +35–39% | +139–151% | broad tech |
| AIQ / THNQ / CHAT | +39–64% | +29–58% | +32–49% | +143–243% | "AI" labelled, short history |
| USD (2x semis) | +96% | +86% | +93% | +889% | leveraged; decay in chop |

SOXX was chosen: strongest 6M/YTD/1Y of the unleveraged set, tradable on
Astral, history back to 2013. At the close of 2026-10-01: 576.33, 20d SMA
536, 50d SMA 529, 200d SMA 452 (price 27% above the 200d).

Pre-registered rules (daily bars, long-only, 95% of equity, no tuning
beyond the four variants listed; the benchmark is buy-and-hold SOXX from
the strategy's first eligible day):
- AIR1: buy when close > 200d SMA and 50d > 200d; sell on close < 200d.
- AIR2: 3% band — buy when close > 1.03×200d and 50d > 200d; sell on
  close < 0.97×200d.
- AIR3: 5% band — buy when close > 1.05×200d and 50d > 200d; sell on
  close < 0.95×200d.
- AIR4: AIR2's band plus a pullback entry (close < 20d SMA).

Full sample 2014-11 → 2026-09 ($100k, 1+2 bp):

| Variant | Return | CAGR | Max DD | Closed trades | Win rate |
|---|---|---|---|---|---|
| AIR1 | +683% | 18.9% | −32.4% | 25 | 36% |
| AIR2 | +757% | 19.8% | −33.1% | 9 | 67% |
| **AIR3** | **+796%** | **20.3%** | **−31.7%** | 6 | **83%** (5/6) |
| AIR4 | +714% | 19.3% | −30.0% | 8 | 63% |
| Buy-and-hold SOXX | +1,801% | 28.2% | −46.2% | — | — |

AIR3 was the best ride variant on every column, so it went through the
folds:

| Window | AIR3 | Buy-and-hold SOXX | Winner |
|---|---|---|---|
| 2014-01 → 2018-06 | +100% (DD −18.8%), 2 trades, 2 wins | +140% (DD −25.1%) | B&H |
| 2018-04 → 2022-08 | +56% (DD −29.4%), 3 trades, 2 wins | +122% (DD −39.3%) | B&H |
| 2022-06 → 2026-09 | +192% (DD −31.7%), 2 closed (1 win) + open trade +135% | +381% (DD −41.7%) | B&H |
| Full 2014-11 → 2026-09 | +796% (20.3%/yr, DD −31.7%) | +1,801% (28.2%/yr, DD −46.2%) | B&H |

Verdict against the gate: **AIR3 FAIL (0/3 folds, full sample loses)** —
in a 12-year semiconductor bull, nothing beats holding. What the exit rule
buys is the drawdown: −32% instead of −46%, flat through most of 2022 and
the April-2025 crash, and a defined "trend is over" signal (a close 5%
under the 200-day) that the operator asked for. Win rate: 5 of 6 closed
trades, which meets the 70% target on paper but rests on six trades; one
more loser would make it 71%, two would make it 63%. The losers are
whipsaws when price falls through the band and recovers within weeks.

Leverage check: the same rule on USD (2x semis) returned +3,365%
(34.8%/yr) but with a −51% drawdown and a 58% win rate over 12 trades —
it fails the win-rate target and is not proposed.

Deployment note: SOXX is in regime today (27% above its 200-day), so a
paper deployment buys on the first bar and the exit sits ~24% below the
current price (0.95 × 452 ≈ 439). That is the entry risk of joining a
trend late; the rule has no tighter stop by design.

Astral objects: AIR1=40094, AIR2=40095, AIR3=40097 (saved 6054),
AIR4=40098, AIR3-USD=40099, BH SOXX=40096. Backtests: AIR1 full
bt_3fd940ca420db1c1 (F1 bt_f170d006d97bdb85); AIR2 full
bt_5fd803e4f421247f (F1 bt_3d8ebae78b796b6a); AIR3 full
bt_96c07739243fd562, folds bt_22088f6cc4f274c4 / bt_e58d20836e73459b /
bt_e3fd0664de255152; AIR4 full bt_ba7d4114387ca4a0; AIR3-USD full
bt_75114068bc1df8d5; BH SOXX full bt_f032e004010eb546 (unaligned
bt_9c39e55a05bbd1a3), folds bt_3eb5f50997652005 / bt_8406dfe09cce1bb8 /
bt_389b43db59037b41.

## Addendum — a bear leg for AIR3 (AIR3B-PSQ, AIR3B-SSG) — FAIL

Operator: "when the crash happens, we will short the market." Short sales
are still off the table (TFSA, cash account, long-only builder), so the
bear leg is an inverse ETF bought when the SOXX trend breaks. Two
pre-registered variants, both keeping the AIR3 long leg unchanged:
- AIR3B-PSQ: when SOXX close < 0.95×200d AND 50d < 200d, buy PSQ
  (−1× Nasdaq-100) with 50% of equity; sell PSQ when SOXX close > 200d.
- AIR3B-SSG: same trigger, SSG (−2× semiconductors) with 25% of equity.
Benchmark: AIR3 alone. Same windows, $100k, 1+2 bp.

| Window | AIR3 alone | + PSQ leg | + SSG leg |
|---|---|---|---|
| 2014-01 → 2018-06 | **+100%** (DD −18.8%) | +96% (DD −20.4%) | +85% (DD −24.3%) |
| 2018-04 → 2022-08 | +56% (DD −29.4%) | **+66%** (DD −29.4%) | +59% (DD −29.4%) |
| 2022-06 → 2026-09 | **+192%** (DD −31.7%) | +174% (DD −35.3%) | +128% (DD −43.0%) |
| Full 2014-11 → 2026-09 | +796% (DD −31.7%), 6 trades, 83% win | +812% (DD −35.3%), 14 trades, 43% win | +555% (DD −43.0%), 14 trades, 29% win |

Verdict: **FAIL for both** (PSQ 1/3 folds; SSG 0/3). The PSQ leg traded
8 times in 12 years: one winner, the 2022 bear (+19.5%, +$29.9k), and
seven whipsaw losers (2015, 2016, 2018, and four in late 2024 – spring
2025, −$24.7k together). Net +$5k on a $100k start, bought with a deeper
drawdown and a win rate cut from 83% to 43%. The −2× version loses on
every window: leveraged inverse funds decay while the signal waits.
AIR3's own exit (a close 5% under the 200-day) already takes the book to
cash when the trend breaks; the data says cash is the better bear trade
for this rule set. AIR3 stays on paper unchanged; neither bear variant is
deployed.

Astral objects: AIR3B-PSQ=41108, AIR3B-SSG=41109. Backtests: PSQ full
bt_959f450bbd861cc1, folds bt_b59289ac7ab44e7b / bt_e5912a83e78d5c26 /
bt_6ad0aeec879fbbca; SSG full bt_1c6c91753f98712a, folds
bt_c00757a58b4e1e36 / bt_4452a5913d1e79ba / bt_31d7ece9dd643ce7.
Paper note: AIR3 (saved 6054, deployment 1861) scheduled its first buy —
16.137 SOXX at the 2026-10-05 open — off the 2026-10-01 close of 588.72.

## Addendum — which ETF carries the AIR3 rule best? (cross-ETF sweep)

Operator: "find the one strong ETF that supports this claim and backtest
our strategy on it." The AIR3 rule (buy when close > 1.05×200d and
50d > 200d; sell on close < 0.95×200d; 95% of equity; no tuning) was run
unchanged on six liquid tech/AI ETFs with history back to 2013.

Full sample 2014-11 → 2026-09 ($100k, 1+2 bp):

| ETF | Return | CAGR | Max DD | Closed trades | Win rate |
|---|---|---|---|---|---|
| **SMH** (VanEck semis) | **+1,098%** | **23.3%** | **−27.6%** | 5 | 80% |
| SOXX (iShares semis; on paper now) | +796% | 20.3% | −31.7% | 6 | 83% |
| QQQ | +293% | 12.2% | −21.7% | 7 | 71% |
| VGT | +285% | 12.0% | −22.5% | 7 | 71% |
| XSD (equal-weight semis) | +270% | 11.6% | −44.3% | 10 | 50% |
| XLK | +238% | 10.8% | −27.0% | 7 | 71% |

SMH vs SOXX, walk-forward:

| Window | AIR3 on SMH | AIR3 on SOXX | Winner |
|---|---|---|---|
| 2014-01 → 2018-06 | **+121%** (DD −18.0%) | +100% (DD −18.8%) | SMH |
| 2018-04 → 2022-08 | **+58%** (DD −27.6%) | +56% (DD −29.4%) | SMH |
| 2022-06 → 2026-09 | **+304%** (DD −24.1%) | +192% (DD −31.7%) | SMH |
| Full 2014-11 → 2026-09 | **+1,098%** (DD −27.6%) | +796% (DD −31.7%) | SMH |

Verdict: **SMH carries the rule better than SOXX in 3/3 folds and the
full sample, with a smaller drawdown in every window.** SOXX was picked on
1-year momentum (+108% vs +85%); over twelve years the rule prefers SMH's
heavier NVDA/TSMC weighting and fewer whipsaws (5 trades vs 6). Caveat:
choosing the best of six instruments after the fact is a mild form of
selection; the fold-by-fold consistency is what makes it credible.
Proposal: move the paper deployment from SOXX to SMH (saved as
"AIR3 SMH ride (5% band)") — operator approval required before any
undeploy/deploy. SOXX, XSD, XLK, QQQ, VGT stay as research objects.

Astral objects: SMH=41110, XSD=41111, XLK=41112, QQQ=41113, VGT=41114.
Backtests (full): SMH bt_741fc186aeb5a5cb, XSD bt_95b3ecfb616b07d4, XLK
bt_051fa6233bf9d339, QQQ bt_7120b3fb7ad6239d, VGT bt_65f5ba96f5b8d79a.
SMH folds: bt_0037c4bb07ba03bf / bt_c791ed4759387a41 / bt_4a753cf579495275.
