"""BUG: run_cycle has no equity>0 guard on the decision leg (run_backtest
does: `and equity > 0`). On a decision day with $0 equity — precisely the
documented deployment shape, "$0 start, $100/week", bootstrapped on a
month-end before the first Monday — compute_orders raises ValueError,
run_cycle blows up, and daily_run only catches HaltError, so the daily job
crashes with a traceback and writes no report.
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
store.save(EngineState(last_equity_date="2026-08-31"))   # the daily_run bootstrap
prices = flat_prices(list(cfg.universe), days=300, end="2026-08-31")
broker = PaperBroker(cash=0.0, prices={s: 100.0 for s in cfg.universe},
                     cost_model=CostModel(cfg.costs))
try:
    run_cycle(today=date(2026, 8, 31), cfg=cfg, store=store, broker=broker,
              strategy=ConstWeights({"XUU.TO": 1.0}), prices=prices,
              journal=NullJournal(), decision_day=True)
    print("cycle completed without crashing")
except ValueError as exc:
    raise AssertionError(
        f"BUG CONFIRMED: run_cycle crashed on a $0-equity decision day: {exc!r} "
        "(daily_run.py catches only HaltError, so the scheduled job dies with a "
        "traceback and writes no report)")
