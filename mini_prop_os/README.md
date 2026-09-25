# Mini-Prop OS

An autonomous, risk-gated trading system for Interactive Brokers built on
`asyncio` + [`ib_insync`](https://ib-insync.readthedocs.io/). This is the
deliberate, separate **live/paper execution build** referenced by the
top-level README — it shares no code path with the backtest `engine/` and
defaults to the IBKR **paper trading** port.

> ⚠️ The repository's Phase 4 verdict still stands: no strategy in this repo
> has passed falsification. Run this system against a **paper** account
> (ports 7497 / 4002) unless you have independent evidence for a strategy
> and change the port deliberately. The EMA-crossover strategy shipped here
> is a reference implementation of the architecture, not an edge.

**Deployment target (2026-09):** the IBKR account this runs against is a
**TFSA** — stocks/ETFs only, **no futures, ever** — so the deployable
configs live in `deploy/` and trade **SPY** on the IB Gateway paper port
(`deploy/config.tfsa-paper.yaml`, `deploy/config.tfsa-paper-dca.yaml`).
The MES config below is kept as the futures reference and for the
validation scorecard; it is not what `deploy/windows/setup.ps1` installs.

The packaged `config.yaml` trades **MES (Micro E-mini S&P 500) futures on CME**:
the front-month contract is auto-resolved at connect time (or pin an expiry
with `contract.last_trade_date`), all notional risk math uses the contract
multiplier (`$5/point` for MES), and the configured multiplier is verified
against the venue's at connect — a mismatch refuses to trade. Futures data
runs with `use_rth: false` since the product trades nearly 24h. To trade a
stock instead, set `sec_type: STK`, `exchange: SMART`, `multiplier: 1.0`,
`use_rth: true` (see `tests/test_minipropos_config.py` for an example).
Note: futures leverage means one MES contract controls ~$30k+ of index
exposure per ~$2k margin — size `order_quantity` and the risk caps
accordingly, and remember MES trades in 0.25-point ticks ($1.25/tick).

## Architecture

```
main.py                 CLI + logging + SIGINT/SIGTERM lifecycle
app.py                  wiring: ib_insync <-> pure core (only file besides
                        core/connection.py that imports ib_insync)
core/
  config.py             typed config, validated from config.yaml
  connection.py         connect, heartbeat, exponential-backoff reconnect
  types.py              Bar, OrderIntent, Fill, Position (broker-agnostic)
strategy/
  base.py               BaseStrategy ABC (bars in -> OrderIntents out)
  ema_crossover.py      incremental EMA crossover, long-only, position-aware
  scheduled_dca.py      mechanical periodic buying, never sells — the only
                        strategy marked DEPLOYABLE: yes (see the gate below)
  tsmom_12_1.py         12-1 month time-series momentum, monthly, long-only
                        (research survivor that failed the gate)
  registry.py           name -> factory, DEPLOYABLE marker, live-port refusal
  adaptive_ema.py       volatility-adaptive crossover (shipped default):
                        regime detection (LOW/NORMAL/HIGH/EXTREME), size
                        scaled down as vol rises, EXTREME = risk-off (exit,
                        no entries), whipsaw entry-confirmation filter, and
                        bounded online learning of per-regime entry
                        thresholds from its own trade outcomes
notify/
  telegram.py           stdlib Telegram alerts + read-only /status console
risk/
  guardrails.py         mandatory pre-trade gate + daily-loss kill switch
execution/
  oms.py                deterministic order state machine, partial fills,
                        JSONL execution audit log
```

Data flow per completed bar:

```
IBKR bars ──▶ Strategy.on_bar ──▶ OrderIntent ──▶ RiskGuardrails.validate
                                                      │ approved
                                                      ▼
              fills/status ◀──── IBKR ◀──── OMS.submit (state machine)
                   │
                   └─▶ positions ledger ─▶ strategy position feedback
```

Risk enforces: parameter validity, per-order quantity cap, long-only (unless
configured), per-symbol share and notional caps, gross-notional cap, and a
daily-loss circuit breaker (tighter of an absolute currency limit and a
percentage of start-of-day equity) that cancels all working orders and
flattens the book. A tripped kill switch only clears via
`RiskGuardrails.reset(operator=...)` — trading logic cannot un-trip it.

The connection layer heartbeats the API (`reqCurrentTime` round-trips) and
reconnects with exponential backoff + jitter on socket loss or repeated
heartbeat misses; on every reconnect the app re-qualifies the contract and
re-subscribes market data, and trading stays disabled in between.

## Running (paper)

1. Start TWS or IB Gateway with API access enabled, logged into a **paper**
   account (TWS paper API port: 7497; Gateway paper: 4002).
2. Install and run:

```bash
pip install ib_insync PyYAML
python -m mini_prop_os                       # uses mini_prop_os/config.yaml
python -m mini_prop_os --config my.yaml      # or your own
```

Ctrl-C / SIGTERM triggers a clean shutdown: working orders are cancelled
(`execution.cancel_on_shutdown`), the book is optionally flattened
(`execution.flatten_on_shutdown`), then the socket closes.

Logs go to the console and `state/mini_prop_os.log`; every order state
transition and fill is also appended to `state/executions.jsonl`.

## The expectancy gate (no strategy ships without it)

```bash
python scripts/expectancy.py --strategy adaptive_ema --symbol SPY \
    --data data/prices_us.csv --folds 3
```

Replays daily closes through the production pipeline with IBKR costs and
prints, per walk-forward fold and for the full sample, final $, CAGR,
max drawdown, round trips, win rate, and buy-and-hold of the same lot.
The rule is hard-coded and printed: **DEPLOYABLE only if final equity
beats buy-and-hold of the same lot in ≥ 2 of 3 folds AND on the full
sample.** Every strategy module carries a `DEPLOYABLE: yes|no` line in
its docstring; `.github/workflows/expectancy.yml` re-runs the gate on
every push and goes red if a strategy marked `yes` fails it, and
`main.py` exits 4 rather than start on a live port with a strategy
marked `no`. Current results (`reports/minipropos_expectancy_spy.md`):

| strategy | folds beaten | full sample | verdict |
|---|---|---|---|
| ema_crossover | 0/3 | no | NOT DEPLOYABLE |
| adaptive_ema | 0/3 | no | NOT DEPLOYABLE |
| scheduled_dca | 3/3 | yes | DEPLOYABLE (accumulated exposure vs one lot — see the report's note; not timing skill) |
| tsmom_12_1 | 1/3 | no | NOT DEPLOYABLE (passed the research pass on SPY, failed the gate — `research/momentum_12_1_vs_tbills.md`) |

## Strategy research (`research/`)

No strategy is coded without a note written first from
`research/TEMPLATE.md`: hypothesis, universe, data, cost model, folds,
benchmark, and a pass/fail rule fixed *before* the numbers are seen.
`python research/run_candidates.py` regenerates the notes; losers are
kept. So far: 200-day SMA filter (FAIL everywhere), 12-1 momentum (PASS
on SPY at the research level, FAIL at the gate), vol-target sizing (FAIL
everywhere).

## Black-Scholes: what it does and does not do here

`quant/blackscholes.py` implements Black-Scholes (spot), Black-76 (the
correct model for options on futures), the Greeks, and an implied-volatility
solver — verified against put-call parity, textbook values, and numerical
derivatives rather than against itself.

**It is not a prediction engine, and cannot be made into one.** The drift
term μ cancels in the hedged-portfolio derivation; that cancellation *is*
the theorem. The equation prices a derivative *relative* to its underlying
precisely by assuming direction is unpredictable. Anyone claiming it makes
trade outcomes predictable has the mathematics backwards.

What the strategy genuinely takes from it is the diffusion term **σS√T**:

- **Entry bands** — a trend must clear `k[regime] × σS√T` to count as
  signal rather than noise. This replaces the earlier ATR proxy with the
  quantity ATR was approximating. The EWMA of `|log return|` is converted
  to a true σ with the `√(π/2)` factor; skipping that understates
  volatility by ~20%.
- **Volatility-target sizing** (`strategy.risk_per_trade`) — position size
  such that a 1-sigma adverse move costs a fixed dollar amount, so a trade
  in a turbulent regime carries the same risk as one in a calm regime. It
  can only size *down* from `order_quantity`, never up.

Measured in the validation scorecard: at four times the volatility, fixed
sizing would have risked **$6,800 against a $2,000 budget**, while
vol-targeted sizing held it to $1,360 — and risk varied by $372 across
regimes instead of $5,068.

So the honest summary: this makes **risk per trade** predictable. It does
not, and mathematically cannot, make **P&L** predictable. Fat tails mean
even the risk figure understates gap moves — the daily-loss kill switch,
not this math, is the tail defense.

## What the AI-quant research contributes here

Three widely-cited projects sit behind the newest modules. Each was adapted
rather than copied, because the literal version does not survive contact
with a single-instrument intraday futures bot.

**Multi-agent LLM trading desks** (TradingAgents) → `strategy/ensemble.py`.
The portable insight is *independent views plus an explicit agreement
requirement*, not the LLMs. Literal agents in the order path would add
seconds of latency to a one-minute bar, make failures non-reproducible
(defeating the regression and mutation tests this system's safety rests
on), and put hallucination directly upstream of order submission. The
ensemble keeps the structure and drops the liability: entry needs
`min_agreement` members, **exit needs one**, and size is the minimum any
agreeing member proposed. LLM agents remain genuinely useful *around* the
loop — proposing strategies, critiquing diffs, summarizing fills — where
latency is free and a human reads the output first.

**LLM news sentiment for allocation** (HARLF) → `risk/event_calendar.py`.
Sentiment-driven *allocation* assumes a multi-asset portfolio rebalancing
daily; this bot trades one contract on minute bars. The transferable core
is that information outside price history predicts risk — and for an
intraday trend-follower the reliable slice is the economic calendar. FOMC,
CPI and NFP produce instant multi-point gaps; entering seconds before one
is the strategy's edge removed and its tail risk multiplied. A calendar
beats a live news model in the trade path on every axis that matters:
deterministic, no network call, no latency, cannot hallucinate. Blackouts
suppress **entries only** — never exits, flattening, or the kill switch.

**LLM strategy discovery** (Automate Strategy Finding) → `quant/statistics.py`.
This is the one that needs the most care. Automated factor search is a
multiple-testing machine: test enough strategies on one history and some
will look excellent through luck alone. The expected maximum Sharpe of N
*worthless* strategies grows with √(2·ln N), so 100 searched strategies
yield a best-of-breed near Sharpe 1.0 from noise. The valuable
contribution is therefore not another generator but the gate every
generator needs — Deflated Sharpe Ratio, Probabilistic Sharpe, and minimum
track record length (Bailey & López de Prado).

### What it says about our own strategy

`python scripts/assess_strategy_credibility.py` points that gate at this
repo's own strategies over the full history:

| strategy | annualized Sharpe | DSR @ 1 trial | @ 10 | @ 100 |
|---|---|---|---|---|
| baseline crossover | 0.651 | 0.997 ✓ | 0.888 | 0.606 |
| adaptive | 0.282 | 0.828 | 0.271 | 0.060 |

The baseline looks **credible only if you pretend it was the first idea
ever tested**. Correct for even ten variants and it fails. Both series
also carry negative skew and kurtosis above 11 — fat-tailed losses that
make a Sharpe less trustworthy, which the formulas penalize.

Note the adaptive strategy earns a *lower* risk-adjusted return than the
baseline while (as measured separately) cutting stress-window drawdown.
That is the trade it makes, now quantified rather than assumed.

The correct response to these numbers is more evidence — out-of-sample
data, live paper fills — not more tuning. Every extra variant tried raises
the bar the table measures against.

## Adaptation, honestly stated

The adaptive strategy's "learning" is a bounded, transparent rule — losing
round trips in a volatility regime raise that regime's entry-confirmation
threshold (winning ones relax it), hard-capped to `[k_min, k_max]`, with
every update logged and the learned state inspectable. It can only make
entries more selective; it can never raise size, invert the signal, or
filter an exit. In the validation stress windows it cut combined drawdown
roughly 40% versus the plain crossover (standing aside entirely in some),
at the measured cost of skipping some winning trades — volatility
adaptation trades upside for exposure control, and none of it is evidence
of edge.

## Telegram

Set `notifications.enabled: true` and export `TELEGRAM_BOT_TOKEN` /
`TELEGRAM_CHAT_ID` (from a git-ignored `.env`; the config only names the
variables). The bot then posts start/stop, "trading enabled", every fill,
every risk reject, and kill-switch events, and answers `/status`,
`/positions`, `/orders` from that one chat. The console is read-only by
design — nothing sent from a phone can place, cancel, or flatten.

## Tests

The strategy, risk, OMS, and config layers are broker-free and covered by
`tests/test_minipropos_*.py`:

```bash
python -m pytest tests -q -k minipropos
```
