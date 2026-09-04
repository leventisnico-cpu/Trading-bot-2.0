"""R2 #1 — HIGH: a HARD_KILL whose liquidation raises ExecutionError is never
persisted: `state.halted = True` is set in memory (runner.py step 5) but the
ExecutionError from `execute_rebalance` on the liquidation propagates out of
`run_cycle` BEFORE `store.save(state)` (step 7). The saved state still says
halted=False, so the next cycle loads an un-halted engine and trades again —
"manual reset only, no automatic recovery, ever (§7)" is silently violated by
a venue outage at the worst possible moment. (The ordinary-rebalance path
catches ExecutionError since round-1 fix #12; the liquidation path does not.)
"""
import sys, tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd

from engine.broker import PaperBroker, PaperBrokerKnobs
from engine.config import load_config
from engine.costs import CostModel
from engine.errors import ExecutionError
from engine.journal import NullJournal
from engine.runner import run_cycle
from engine.state import EngineState, StateStore

REPO = Path(__file__).resolve().parents[1]
cfg = load_config(REPO / "config" / "engine.toml")


class Noop:
    def target_weights(self, prices, today):
        return {}


idx = pd.bdate_range(end="2026-08-14", periods=300)
prices = pd.DataFrame(100.0, index=idx, columns=list(cfg.universe))

tmp = Path(tempfile.mkdtemp())
store = StateStore(tmp / "state.json")
# peak 10,000 vs current equity 5,000 -> 50% drawdown > 35% max -> HARD_KILL.
store.save(EngineState(peak_equity=10_000.0, last_equity=10_000.0,
                       last_equity_date="2026-08-13",
                       positions={"XUU.TO": 50.0}, cash=0.0))
# Venue goes down on the FIRST liquidation order.
broker = PaperBroker(cash=0.0, prices={s: 100.0 for s in cfg.universe},
                     cost_model=CostModel(cfg.costs),
                     positions={"XUU.TO": 50.0},
                     knobs=PaperBrokerKnobs(outage_after_n_orders=0))

try:
    run_cycle(today=date(2026, 8, 14), cfg=cfg, store=store, broker=broker,
              strategy=Noop(), prices=prices, journal=NullJournal(),
              decision_day=False, net_flows=0.0)
    print("run_cycle returned normally (unexpected)")
except ExecutionError as exc:
    print(f"ExecutionError propagated out of run_cycle: {exc}")

after = store.load()
print(f"persisted state after the kill: halted={after.halted!r}, "
      f"halt_reason={after.halt_reason!r}")

assert after.halted, (
    "BUG CONFIRMED: HARD_KILL fired (drawdown 50% > 35%) but the venue outage "
    "during liquidation aborted run_cycle before store.save() — the durable "
    "state still says halted=False, so tomorrow's cycle loads an un-halted "
    "engine and keeps trading through a fired kill switch"
)
print("fixed: halt survived the liquidation failure")
