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

Astral objects: A=37934, B=37936 (saved 5777), C=37935, D=37938
(saved 5778), control=37940, SPY benchmark=37638.
