"""R2 #6 — MEDIUM: negative cash is back — a PARTIAL fill on an approved
full-exit sell still pays the $1 minimum fee out of sub-$1 proceeds.

Round-1 fix #6 added the dust guard `frac >= 1.0` in filter_orders, but the
fraction is computed at the FULL order size, and PaperBroker's sell path
still credits `filled * px - cost.total` unconditionally. A 2-share, $2.20
position passes the guard (all-in cost ~45% of notional), then fills 40%:
0.8 shares x $1.10 = $0.88 of proceeds against a commission floor of $1.00
— cash goes negative through the exact hole the fix claimed to close.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.broker import PaperBroker, PaperBrokerKnobs
from engine.config import load_config
from engine.costs import CostModel
from engine.execution import execute_rebalance
from engine.orders import Order, Side
from engine.risk import RiskEngine

REPO = Path(__file__).resolve().parents[1]
cfg = load_config(REPO / "config" / "engine.toml")
cm = CostModel(cfg.costs)
risk = RiskEngine(cfg.risk, cm)

px = 1.10
frac = cm.all_in_fraction(shares=2.0, price=px)
print(f"all-in close cost at FULL size: {frac:.1%} of notional "
      "(< 100%, so the round-1 dust guard approves the exit)")

broker = PaperBroker(cash=0.0, prices={"DUST": px}, cost_model=cm,
                     positions={"DUST": 2.0},
                     knobs=PaperBrokerKnobs(fill_fraction={"DUST": 0.4}))
o = Order(symbol="DUST", side=Side.SELL, shares=2.0, is_full_exit=True)
out = execute_rebalance(broker, risk, [o], {"DUST": px})
acct = broker.get_account()
print(f"results: {[(r.status.value, r.filled_shares) for r in out.results]}")
print(f"dropped: {[(d.order.symbol, d.reason) for d in out.dropped]}")
print(f"cash after the partial full-exit fill: {acct.cash:.4f}")

assert acct.cash >= 0, (
    f"BUG CONFIRMED: cash is {acct.cash:.4f} — the dust guard checks cost "
    "fraction at full order size only, and the broker's sell path still pays "
    "the $1.00 minimum commission out of $0.88 of partial-fill proceeds "
    "(round-1 finding #6 resurrected by fill_fraction < 1)"
)
print("fixed: partial fills can no longer drive cash negative")
