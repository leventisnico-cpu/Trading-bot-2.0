"""R2 #5 — MEDIUM: escalation resends are not counted against
max_orders_per_day — cap N can put 2N orders on the wire.

The round-1 #1 fix caps the batch BEFORE submission, but each unfilled limit
order then escalates to a NEW market order via _submit_single, which passes
through risk.filter_orders as a single-order batch (where the cap can never
bite, the original round-1 finding). With cap=2 and two unfilled limit
sells, FOUR orders reach the venue. The §7 backstop "max orders per day" is
enforced on intentions, not on what is actually submitted.

(Reachable whenever limit orders are used — the escalation feature §5.10
exists exactly for them; compute_orders currently emits market orders only,
so today's paper pipeline does not hit it, but execute_rebalance is the
documented boundary that claims the cap.)
"""
import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.broker import PaperBroker, PaperBrokerKnobs
from engine.config import load_config
from engine.costs import CostModel
from engine.execution import execute_rebalance
from engine.orders import Order, OrderStatus, Side
from engine.risk import RiskEngine

REPO = Path(__file__).resolve().parents[1]
cfg = load_config(REPO / "config" / "engine.toml")
risk_cfg = dataclasses.replace(cfg.risk, max_orders_per_day=2)
cm = CostModel(cfg.costs)
risk = RiskEngine(risk_cfg, cm)

prices = {"A": 50.0, "B": 50.0, "C": 50.0}
# Both submitted limit sells expire unfilled -> both escalate to market.
knobs = PaperBrokerKnobs(scripted_status_by_symbol={
    "A": OrderStatus.EXPIRED, "B": OrderStatus.EXPIRED})
broker = PaperBroker(cash=0.0, prices=prices, cost_model=cm,
                     positions={"A": 10.0, "B": 10.0, "C": 10.0}, knobs=knobs)
orders = [Order(symbol=s, side=Side.SELL, shares=10.0, limit_price=50.0)
          for s in ("A", "B", "C")]
out = execute_rebalance(broker, risk, orders, prices,
                        escalation_max_hops=cfg.execution.escalation_max_hops)

print(f"configured max_orders_per_day = {risk_cfg.max_orders_per_day}")
print(f"orders submitted to the broker: {len(broker.submissions)} "
      f"({[(o.symbol, 'LMT' if o.limit_price else 'MKT') for o in broker.submissions]})")
print(f"escalations: {out.escalations}")

assert len(broker.submissions) <= risk_cfg.max_orders_per_day, (
    f"BUG CONFIRMED: cap is {risk_cfg.max_orders_per_day} but "
    f"{len(broker.submissions)} orders reached the venue — escalated resends "
    "bypass the batch-level cap (and the per-order filter_orders cap is still "
    "the round-1 no-op for a single order)"
)
print("fixed: escalations are counted against the daily cap")
