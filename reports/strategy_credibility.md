# Strategy credibility assessment

Generated: 2026-09-20 20:06 UTC

Deflated Sharpe Ratio (Bailey & López de Prado) applied to the shipped strategies over the full SPY history scaled as an MES proxy. DSR is the probability the edge is real **after** correcting for how many strategies were searched to find it.

## adaptive

- Active observations: 2919
- Sharpe (per bar): 0.0177
- Sharpe (annualized): 0.282
- Skew: -1.258  |  Kurtosis: 11.23 (3.0 = normal)

| trials searched | selection bar | DSR | verdict |
|---|---|---|---|
| 1 | 0.0000 | 0.8284 | not credible |
| 10 | 0.0291 | 0.2714 | not credible |
| 100 | 0.0468 | 0.0602 | not credible |
| 1000 | 0.0602 | 0.0116 | not credible |

## baseline

- Active observations: 4673
- Sharpe (per bar): 0.0410
- Sharpe (annualized): 0.651
- Skew: -0.476  |  Kurtosis: 14.41 (3.0 = normal)

| trials searched | selection bar | DSR | verdict |
|---|---|---|---|
| 1 | 0.0000 | 0.9972 | CREDIBLE |
| 10 | 0.0230 | 0.8875 | not credible |
| 100 | 0.0370 | 0.6061 | not credible |
| 1000 | 0.0476 | 0.3277 | not credible |

## Reading this

A DSR below 0.95 means the result is not statistically distinguishable from the best of N worthless strategies. That is not a flaw in the implementation — it is the honest state of a trend-following rule measured against its own search space.

The correct response is more evidence (out-of-sample data, live paper fills), not more parameter tuning: every additional variant tried *raises* the bar this table measures against.
