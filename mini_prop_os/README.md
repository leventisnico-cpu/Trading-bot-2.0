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

## Tests

The strategy, risk, OMS, and config layers are broker-free and covered by
`tests/test_minipropos_*.py`:

```bash
python -m pytest tests -q -k minipropos
```
