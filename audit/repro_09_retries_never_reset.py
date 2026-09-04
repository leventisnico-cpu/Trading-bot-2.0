"""BUG: state.rebalance_retries is only reset on CONVERGENCE. If one bad
month exhausts max_rebalance_retries without converging, every FUTURE
month's rebalance is refused too ("retry cap reached") even though the
broker is healthy again — the engine is permanently soft-bricked until a
human edits the state file, and the warning text misleadingly scopes the
problem to the current period.
"""
import sys, tempfile; sys.path.insert(0, "/home/user/Trading-bot-2.0")
from datetime import date
from pathlib import Path
from engine.broker import PaperBroker
from engine.config import load_config
from engine.costs import CostModel
from engine.journal import NullJournal
from engine.runner import run_cycle
from engine.state import EngineState, StateStore
from tests.conftest import ConstWeights, flat_prices

cfg = load_config("/home/user/Trading-bot-2.0/config/engine.toml")
tmp = Path(tempfile.mkdtemp())
store = StateStore(tmp / "state.json")

# July's rebalance failed max_rebalance_retries times (e.g. venue outage
# week). July never converged; the counter sits at the cap.
store.save(EngineState(peak_equity=10_000, last_equity=10_000,
                       last_equity_date="2026-08-28",
                       last_completed_period="2026-06",     # June was the last good one
                       rebalance_retries=cfg.risk.max_rebalance_retries,
                       cash=10_000.0))

# It is now the AUGUST decision day; broker is perfectly healthy.
prices = flat_prices(list(cfg.universe), days=300, end="2026-08-31")
broker = PaperBroker(cash=10_000.0, prices={s: 100.0 for s in cfg.universe},
                     cost_model=CostModel(cfg.costs))
result = run_cycle(today=date(2026, 8, 31), cfg=cfg, store=store, broker=broker,
                   strategy=ConstWeights({"XUU.TO": 0.95}), prices=prices,
                   journal=NullJournal(), decision_day=True)
print("traded:", result.traded)
print([l for l in result.report.splitlines() if "note:" in l])
print("positions after cycle:", store.load().positions)
assert result.traded, (
    "BUG CONFIRMED: a NEW month's rebalance on a healthy broker was refused "
    "because rebalance_retries from a past month is never reset on period "
    "rollover — the engine stays in cash forever without manual state surgery")
