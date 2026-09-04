"""R2 #9 — MEDIUM: run_cycle is not idempotent in net_flows — re-running the
same day re-adds the deposit to peak_equity every time, and the inflated
peak eventually fires a FALSE HARD_KILL on flat equity.

The round-1 #10 fix taught pre_trade to guard daily_return against
last_equity_date == today, but the peak update in runner.py step 7
(`state.peak_equity = max(state.peak_equity + net_flows, equity)`) has no
such guard: every same-day call with the same net_flows ratchets the
drawdown baseline by another $100 that was deposited exactly once. With
equity flat at $1,100, seven same-day cycles push peak to $1,700 and the
35% drawdown kill fires — liquidate + halt, manual reset only — on an
account that never lost a cent. Reachable whenever a cycle re-runs against
already-updated state with the same flows (e.g. the GitHub workflow re-runs
after a partial failure, or state was committed but the re-run recomputes
flows from an external source rather than contributions_due).
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
from engine.runner import run_cycle
from engine.state import EngineState, StateStore

REPO = Path(__file__).resolve().parents[1]
cfg = load_config(REPO / "config" / "engine.toml")


class Noop:
    def target_weights(self, prices, today):
        return {}


idx = pd.bdate_range(end="2026-09-04", periods=300)
prices = pd.DataFrame(100.0, index=idx, columns=list(cfg.universe))
tmp = Path(tempfile.mkdtemp())
store = StateStore(tmp / "s.json")
store.save(EngineState(peak_equity=1_000.0, last_equity=1_000.0,
                       last_equity_date="2026-09-03", cash=1_000.0))
broker = PaperBroker(cash=1_100.0, prices={s: 100.0 for s in cfg.universe},
                     cost_model=CostModel(cfg.costs))

killed_at = None
for k in range(10):
    run_cycle(today=date(2026, 9, 4), cfg=cfg, store=store, broker=broker,
              strategy=Noop(), prices=prices, journal=NullJournal(),
              decision_day=False, net_flows=100.0)
    st = store.load()
    print(f"same-day call {k + 1}: peak_equity={st.peak_equity:.0f} "
          f"halted={st.halted}")
    if st.halted:
        killed_at = k + 1
        print(f"-> HARD KILL: {st.halt_reason} (equity was flat at 1,100)")
        break

assert killed_at is None and store.load().peak_equity == 1_100.0, (
    "BUG CONFIRMED: one $100 deposit, re-processed on the same day, ratcheted "
    f"peak_equity to {store.load().peak_equity:.0f} and "
    + (f"fired a false HARD_KILL on call {killed_at} " if killed_at else "")
    + "— pre_trade guards daily_return for last_equity_date == today but the "
    "peak += net_flows update has no same-day idempotence guard"
)
print("fixed: same-day re-runs no longer inflate the peak")
