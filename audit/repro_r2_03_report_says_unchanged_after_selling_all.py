"""R2 #3 — MEDIUM: the report headlines "NO REBALANCE TODAY — HOLDINGS
UNCHANGED" on a day the engine SOLD EVERY POSITION.

Round-1 fix #8 keyed the header on `target_weights` being truthy. But a
strategy that returns {} (all-zero target) still produces full-exit SELL
orders via compute_orders, and run_cycle executes them (traded=True, fills
in outcome). build_report then takes the empty-target branch and prints
NO_REBALANCE_HEADER — "HOLDINGS UNCHANGED" — directly above the order list
that shows the liquidation. The same empty-target case also skips the §5.9
convergence bookkeeping (last_completed_period is never set).
"""
import sys, tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd

from engine.broker import PaperBroker
from engine.config import load_config
from engine.costs import CostModel
from engine.journal import NullJournal
from engine.report import NO_REBALANCE_HEADER
from engine.runner import run_cycle
from engine.state import EngineState, StateStore

REPO = Path(__file__).resolve().parents[1]
cfg = load_config(REPO / "config" / "engine.toml")


class AllCash:
    """Any strategy that goes fully to cash returns {} — e.g. DualMomentum
    with a defensive asset whose momentum is negative."""

    def target_weights(self, prices, today):
        return {}


idx = pd.bdate_range(end="2026-08-31", periods=300)
prices = pd.DataFrame(100.0, index=idx, columns=list(cfg.universe))
tmp = Path(tempfile.mkdtemp())
store = StateStore(tmp / "state.json")
positions = {"XUU.TO": 50.0}
store.save(EngineState(peak_equity=5_000.0, last_equity=5_000.0,
                       last_equity_date="2026-08-28",
                       positions=dict(positions), cash=0.0))
broker = PaperBroker(cash=0.0, prices={s: 100.0 for s in cfg.universe},
                     cost_model=CostModel(cfg.costs), positions=dict(positions))
res = run_cycle(today=date(2026, 8, 31), cfg=cfg, store=store, broker=broker,
                strategy=AllCash(), prices=prices, journal=NullJournal(),
                decision_day=True, net_flows=0.0)
sold = bool(res.outcome and any(r.filled_shares > 0 for r in res.outcome.results))
header = res.report.splitlines()[0]
print("---- report ----")
print(res.report)
print("----------------")
print(f"positions were sold: {sold}; header: {header!r}")

assert not (sold and header == NO_REBALANCE_HEADER), (
    "BUG CONFIRMED: the engine liquidated the whole book this cycle "
    f"(traded={res.traded}, fills={[(r.order.symbol, r.filled_shares) for r in res.outcome.results]}) "
    f"but the report's first line is {header!r} — the one header the operator "
    "must be able to trust says HOLDINGS UNCHANGED on the day everything was sold"
)
print("fixed: header no longer claims 'unchanged' after selling")
