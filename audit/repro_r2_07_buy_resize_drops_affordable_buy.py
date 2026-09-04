"""R2 #7 — MEDIUM: the round-1 #7 buy-resize fix seeds the resize with the
FULL planned order's cost and only ever decrements — an affordable buy is
dropped whenever the planned order's own cost exceeds available cash.

execution.py: `resized = floor((available - cost.total) / px)` where `cost`
is the cost of `o.shares` (the PLANNED size). When the planned order is much
larger than cash supports (exactly the situation the re-read exists for —
e.g. this month's sells expired unfilled, so the cash they were to free
never arrived), `available - cost.total` is negative, `resized <= 0`, and
the buy is dropped as "insufficient confirmed cash" even though a smaller
buy is perfectly affordable. The while-loop only walks DOWN from the seed;
nothing ever walks up toward what the cash actually supports.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.broker import PaperBroker
from engine.config import load_config
from engine.costs import CostModel
from engine.execution import execute_rebalance
from engine.orders import Order, Side
from engine.risk import RiskEngine

REPO = Path(__file__).resolve().parents[1]
cfg = load_config(REPO / "config" / "engine.toml")
cm = CostModel(cfg.costs)
risk = RiskEngine(cfg.risk, cm)

available, px, planned = 200.0, 30.0, 10_000.0
seed_cost = cm.order_cost(shares=planned, price=px).total
afford6 = 6 * px + cm.order_cost(shares=6, price=px).total
print(f"available cash: {available:.2f}; planned buy: {planned:g} sh @ {px}")
print(f"cost of the PLANNED order used as resize seed: {seed_cost:.2f} "
      f"-> seed floor(({available} - {seed_cost:.0f})/{px}) < 0")
print(f"6 shares would cost {afford6:.2f} <= {available:.2f} (affordable, "
      f"notional {6 * px:.0f} > min_order_notional {cfg.risk.min_order_notional:.0f})")

broker = PaperBroker(cash=available, prices={"B": px}, cost_model=cm)
out = execute_rebalance(broker, risk,
                        [Order(symbol="B", side=Side.BUY, shares=planned)],
                        {"B": px})
print(f"results: {[(r.status.value, r.filled_shares) for r in out.results]}")
print(f"dropped: {[(d.order.symbol, d.reason) for d in out.dropped]}")
print(f"cash after: {broker.get_account().cash:.2f} (nothing was bought)")

bought = sum(r.filled_shares for r in out.results)
assert bought > 0, (
    "BUG CONFIRMED: $200 of confirmed cash could buy 6 shares ($181.13 "
    "all-in), but the resize seed subtracts the 10,000-share order's $310 "
    "cost, goes negative, and the whole buy is dropped as 'insufficient "
    "confirmed cash' — the resize logic the round-1 fix added never runs "
    "upward from an unaffordable seed"
)
print("fixed: the buy was resized to what cash supports")
