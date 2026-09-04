"""BUG: risk.max_orders_per_day is a no-op in the real execution path.

execute_rebalance() filters orders ONE AT A TIME (_submit_single calls
risk.filter_orders([order], ...)), so truncate_to_cap always sees a list of
length 1 and never truncates. The regression test (test_fm03) calls
truncate_to_cap directly and misses this.
"""
import sys; sys.path.insert(0, "/home/user/Trading-bot-2.0")
from engine.broker import PaperBroker
from engine.config import load_config
from engine.costs import CostModel
from engine.execution import execute_rebalance
from engine.orders import Order, Side
from engine.risk import RiskEngine

cfg = load_config("/home/user/Trading-bot-2.0/config/engine.toml")
cap = cfg.risk.max_orders_per_day
print("configured max_orders_per_day =", cap)

n = cap + 5
prices = {f"S{i}": 100.0 for i in range(n)}
broker = PaperBroker(cash=1_000_000.0, prices=prices,
                     cost_model=CostModel(cfg.costs))
risk = RiskEngine(cfg.risk, CostModel(cfg.costs))
orders = [Order(symbol=f"S{i}", side=Side.BUY, shares=5) for i in range(n)]

outcome = execute_rebalance(broker, risk, orders, prices)
print(f"orders submitted to broker: {len(broker.submissions)} (cap is {cap})")
print("dropped for cap:", [d.reason for d in outcome.dropped])
assert len(broker.submissions) <= cap, (
    f"BUG CONFIRMED: {len(broker.submissions)} orders reached the broker, "
    f"cap {cap} never enforced in execute_rebalance")
