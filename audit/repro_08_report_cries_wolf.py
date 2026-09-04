"""BUG: on every NON-decision day, run_cycle builds the report with
target_weights={} — and converged(positions, {}, ...) treats every held
position as a deviation from a zero target. A perfectly on-target portfolio
is headlined "PARTIAL REBALANCE — PORTFOLIO NOT AT TARGET" every single day
between rebalances. §11 says a partial rebalance must never be describable
as complete; this does the opposite mistake and trains the operator to
ignore the header (§7's own alarm-fatigue argument).
"""
import sys, tempfile; sys.path.insert(0, "/home/user/Trading-bot-2.0")
from datetime import date
from pathlib import Path
from engine.broker import PaperBroker
from engine.config import load_config
from engine.costs import CostModel
from engine.journal import NullJournal
from engine.report import NOT_AT_TARGET_HEADER
from engine.runner import run_cycle
from engine.state import EngineState, StateStore
from tests.conftest import ConstWeights, flat_prices

cfg = load_config("/home/user/Trading-bot-2.0/config/engine.toml")
tmp = Path(tempfile.mkdtemp())
store = StateStore(tmp / "state.json")
# Portfolio fully at last month's target: 99 shares XUU.TO @ 100, converged.
store.save(EngineState(peak_equity=10_000, last_equity=9_900,
                       last_equity_date="2026-08-27",
                       last_completed_period="2026-08",
                       positions={"XUU.TO": 99.0}, cash=100.0))
prices = flat_prices(list(cfg.universe), days=300, end="2026-08-28")
broker = PaperBroker(cash=100.0, prices={s: 100.0 for s in cfg.universe},
                     cost_model=CostModel(cfg.costs), positions={"XUU.TO": 99.0})

result = run_cycle(today=date(2026, 8, 28), cfg=cfg, store=store, broker=broker,
                   strategy=ConstWeights({"XUU.TO": 1.0}), prices=prices,
                   journal=NullJournal(), decision_day=False)   # ordinary day
print("---- report on an ordinary, fully-converged, no-trade day ----")
print(result.report.splitlines()[0])
assert not result.report.startswith(NOT_AT_TARGET_HEADER), (
    "BUG CONFIRMED: a converged portfolio on a no-trade day is reported as "
    "'PARTIAL REBALANCE — PORTFOLIO NOT AT TARGET' (converged() compared "
    "held positions against the empty {} target)")
