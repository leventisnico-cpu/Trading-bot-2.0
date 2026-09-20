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

The shipped config trades **MES (Micro E-mini S&P 500) futures on CME**:
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
  adaptive_ema.py       volatility-adaptive crossover (shipped default):
                        regime detection (LOW/NORMAL/HIGH/EXTREME), size
                        scaled down as vol rises, EXTREME = risk-off (exit,
                        no entries), whipsaw entry-confirmation filter, and
                        bounded online learning of per-regime entry
                        thresholds from its own trade outcomes
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

## Tests

The strategy, risk, OMS, and config layers are broker-free and covered by
`tests/test_minipropos_*.py`:

```bash
python -m pytest tests -q -k minipropos
```
