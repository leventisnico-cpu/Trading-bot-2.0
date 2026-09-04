"""R2 #2 — HIGH: a data glitch in ANY risk asset liquidates the ENTIRE book.

DualMomentum._momentum returns None when a symbol's 253-bar window has >5%
NaN (or too little history). target_weights then returns {} ("stay in cash
rather than rank a partial menu"). But an empty target dict is not "stay
put" — compute_orders treats every held symbol as target 0 shares and emits
is_full_exit SELLs of everything. validate_prices does NOT catch it (it only
checks the LAST value per symbol), so the §5.7 principle — "a data gap must
never silently become target weight 0" — is violated one layer up: 20 NaNs
in XEC.TO (a symbol we don't even hold) sell the whole XUU.TO position and
pay real costs to do it.
"""
import sys, tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd

from engine.broker import PaperBroker
from engine.config import load_config
from engine.costs import CostModel
from engine.data import validate_prices
from engine.journal import NullJournal
from engine.runner import run_cycle
from engine.state import EngineState, StateStore
from engine.strategies import DualMomentum

REPO = Path(__file__).resolve().parents[1]
cfg = load_config(REPO / "config" / "engine.toml")

idx = pd.bdate_range(end="2026-08-31", periods=600)
prices = pd.DataFrame(100.0, index=idx, columns=list(cfg.universe))
# Feed glitch: ~8% NaN scattered through XEC.TO's momentum window; its LAST
# value is fine, so validate_prices passes.
col = prices.columns.get_loc("XEC.TO")
for k in range(20):
    prices.iloc[-250 + k * 10, col] = np.nan

validate_prices(prices, set(cfg.universe), date(2026, 8, 31),
                cfg.data.max_staleness_days)  # passes: last values all fresh
print("validate_prices: PASSED (the glitch is invisible to the data layer)")

strategy = DualMomentum(cfg.universe, cfg.strategy)
print("target_weights:", strategy.target_weights(prices, date(2026, 8, 31)))

tmp = Path(tempfile.mkdtemp())
store = StateStore(tmp / "state.json")
positions = {"XUU.TO": 50.0}  # $5,000 held in XUU.TO, whose data is perfect
store.save(EngineState(peak_equity=5_000.0, last_equity=5_000.0,
                       last_equity_date="2026-08-28",
                       positions=dict(positions), cash=0.0))
broker = PaperBroker(cash=0.0, prices={s: 100.0 for s in cfg.universe},
                     cost_model=CostModel(cfg.costs), positions=dict(positions))
res = run_cycle(today=date(2026, 8, 31), cfg=cfg, store=store, broker=broker,
                strategy=strategy, prices=prices, journal=NullJournal(),
                decision_day=True, net_flows=0.0)
acct = broker.get_account()
fills = [(r.order.side.value, r.order.symbol, r.status.value)
         for r in (res.outcome.results if res.outcome else [])]
print(f"fills: {fills}")
print(f"positions after: {acct.positions}, cash: {acct.cash:.2f}")

assert acct.positions.get("XUU.TO", 0.0) > 0, (
    "BUG CONFIRMED: 20 NaN closes in XEC.TO (not even held) made DualMomentum "
    "return {} and the engine SOLD THE ENTIRE XUU.TO position "
    f"(fills={fills}, cash now {acct.cash:.2f}) instead of refusing or "
    "holding — a data gap became 'target weight 0' for the whole book (§5.7)"
)
print("fixed: glitchy cross-section no longer liquidates held positions")
