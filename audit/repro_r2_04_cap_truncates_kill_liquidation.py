"""R2 #4 — HIGH: the round-1 batch order cap truncates HARD_KILL liquidation,
permanently stranding positions in a halted account.

The round-1 #1 fix applies `truncate_to_cap` to EVERY batch entering
execute_rebalance — including the "liquidate everything" batch that a
HARD_KILL sends. With more positions than max_orders_per_day, the excess
positions are dropped, the engine sets halted=True and saves — and because
halted means "manual reset only, no automatic recovery, ever (§7)", NO
future cycle can ever sell the remainder. A kill switch that exists to get
you OUT of the market leaves you in it, forever. (Before the round-1 fix
the cap was a no-op, so liquidations always went out in full — this is a
regression introduced by the fix.)
"""
import dataclasses
import sys, tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd

from engine.broker import PaperBroker
from engine.config import load_config
from engine.costs import CostModel
from engine.errors import HaltError
from engine.journal import NullJournal
from engine.runner import run_cycle
from engine.state import EngineState, StateStore

REPO = Path(__file__).resolve().parents[1]
cfg = load_config(REPO / "config" / "engine.toml")
cfg = dataclasses.replace(cfg, risk=dataclasses.replace(cfg.risk, max_orders_per_day=2))


class Noop:
    def target_weights(self, prices, today):
        return {}


idx = pd.bdate_range(end="2026-08-14", periods=300)
prices = pd.DataFrame(100.0, index=idx, columns=list(cfg.universe))
tmp = Path(tempfile.mkdtemp())
store = StateStore(tmp / "state.json")
positions = {"XUU.TO": 20.0, "XEF.TO": 20.0, "XIC.TO": 20.0}  # 3 positions, cap 2
store.save(EngineState(peak_equity=20_000.0, last_equity=20_000.0,
                       last_equity_date="2026-08-13",
                       positions=dict(positions), cash=0.0))
broker = PaperBroker(cash=0.0, prices={s: 100.0 for s in cfg.universe},
                     cost_model=CostModel(cfg.costs), positions=dict(positions))
res = run_cycle(today=date(2026, 8, 14), cfg=cfg, store=store, broker=broker,
                strategy=Noop(), prices=prices, journal=NullJournal(),
                decision_day=False, net_flows=0.0)
after = store.load()
acct = broker.get_account()
print(f"halted: {after.halted} ({after.halt_reason})")
print(f"positions after 'liquidate everything': {acct.positions}")
print(f"dropped: {[(d.order.symbol, d.reason) for d in res.outcome.dropped]}")

# And the halt is permanent: the next cycle refuses to run at all.
try:
    run_cycle(today=date(2026, 8, 17), cfg=cfg, store=store, broker=broker,
              strategy=Noop(), prices=prices, journal=NullJournal(),
              decision_day=False, net_flows=0.0)
    next_cycle = "ran"
except HaltError as exc:
    next_cycle = f"HaltError: {exc}"
print(f"next cycle: {next_cycle}")

assert not (after.halted and acct.positions), (
    "BUG CONFIRMED: HARD_KILL liquidation was truncated by max_orders_per_day "
    f"(cap 2, 3 positions) — the engine is halted forever while still holding "
    f"{acct.positions} (${sum(acct.positions.values()) * 100.0:,.0f} of market "
    "exposure that no future cycle can ever sell)"
)
print("fixed: kill liquidation is exempt from the batch cap")
