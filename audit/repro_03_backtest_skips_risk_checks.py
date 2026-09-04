"""BUG (parity): the backtest evaluates the risk kill switches
(drawdown hard-kill, equity floor, daily-loss stand-down) ONLY on decision
days, while live run_cycle evaluates them EVERY day. A drawdown that
breaches max_drawdown_pct intra-month and recovers by month-end:
  - live: HARD_KILL fires on the breach day, liquidates at the bottom, halts.
  - backtest: never notices; reports halted=False, keeps compounding.
Same config, same prices, opposite outcomes -> invariant 3 broken.
"""
import sys, tempfile, dataclasses; sys.path.insert(0, "/home/user/Trading-bot-2.0")
from datetime import date
from pathlib import Path
import pandas as pd

from engine.backtest import run_backtest
from engine.broker import PaperBroker
from engine.config import load_config
from engine.costs import CostModel
from engine.journal import NullJournal
from engine.runner import run_cycle
from engine.state import EngineState, StateStore
from tests.conftest import ConstWeights

cfg = load_config("/home/user/Trading-bot-2.0/config/engine.toml")
cfg = dataclasses.replace(cfg, universe=("XUU.TO",))   # one-symbol universe
print("max_drawdown_pct =", cfg.risk.max_drawdown_pct)

# Price path: flat 100, crash to 55 (-45% > 35% limit) mid-month, full recovery
# before the next decision day.
idx = pd.bdate_range("2026-01-05", periods=60)
px = [100.0] * 60
for k in range(25, 30):
    px[k] = 55.0                       # 45% drawdown for a week
prices = pd.DataFrame({"XUU.TO": px}, index=idx)

# ---- BACKTEST: decision on day 0 (buy) and day 55 (well after recovery) ----
res = run_backtest(
    prices, ConstWeights({"XUU.TO": 1.0}), cfg,
    initial_equity=10_000.0,
    is_decision_day=lambda i: i in (0, 55),
)
print(f"backtest: halted={res.halted}, halts={res.halts}, "
      f"final equity={res.equity.iloc[-1]:,.2f}")

# ---- LIVE: run_cycle daily over the same marks, same config ----------------
tmp = Path(tempfile.mkdtemp())
store = StateStore(tmp / "state.json")
shares = 99.0  # ~ what the backtest buys
store.save(EngineState(peak_equity=9_900.0, last_equity=9_900.0,
                       last_equity_date="2026-01-05",
                       positions={"XUU.TO": shares}, cash=100.0))
live_halted, halt_day = False, None
for i in range(1, 60):
    state = store.load()
    if state.halted:
        live_halted, halt_day = True, halt_day or idx[i].date()
        break
    broker = PaperBroker(cash=state.cash, prices={"XUU.TO": px[i]},
                         cost_model=CostModel(cfg.costs),
                         positions=dict(state.positions))
    run_cycle(today=idx[i].date(), cfg=cfg, store=store, broker=broker,
              strategy=ConstWeights({"XUU.TO": 1.0}), prices=prices.iloc[:i + 1],
              journal=NullJournal(), decision_day=(i in (0, 55)))
final = store.load()
print(f"live:     halted={final.halted}, reason={final.halt_reason!r}, "
      f"cash={final.cash:,.2f}, positions={final.positions}")

assert res.halted == final.halted, (
    "BUG CONFIRMED: identical prices + config -> live hard-kills and liquidates "
    "at the bottom, backtest sails through un-halted (risk gate only runs on "
    "decision days in run_backtest)")
