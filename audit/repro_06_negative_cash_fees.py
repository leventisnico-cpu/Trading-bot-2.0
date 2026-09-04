"""BUG: cash can go NEGATIVE through fees on a sell.

PaperBroker checks affordability on BUYS only. On a SELL it credits
proceeds - costs unconditionally. A full-exit sell whose all-in cost
exceeds its proceeds (full exits are deliberately exempt from the
min-notional AND max_cost_fraction risk filters) drives cash below zero —
i.e. margin/leverage in an account that claims 'no leverage, structurally'.
"""
import sys; sys.path.insert(0, "/home/user/Trading-bot-2.0")
from engine.broker import PaperBroker
from engine.config import load_config
from engine.costs import CostModel
from engine.execution import execute_rebalance
from engine.orders import Order, Side
from engine.risk import RiskEngine

cfg = load_config("/home/user/Trading-bot-2.0/config/engine.toml")
cm = CostModel(cfg.costs)
risk = RiskEngine(cfg.risk, cm)

# Account: $0 cash, one leftover share of a $0.50 penny position.
prices = {"XEC.TO": 0.50}
broker = PaperBroker(cash=0.0, prices=prices, cost_model=cm,
                     positions={"XEC.TO": 1.0})
exit_order = [Order(symbol="XEC.TO", side=Side.SELL, shares=1.0, is_full_exit=True)]

outcome = execute_rebalance(broker, risk, exit_order, prices)
acct = broker.get_account()
print("order results:", [(r.status.value, r.filled_shares) for r in outcome.results])
print("dropped:", outcome.dropped)
print(f"cash after full exit: {acct.cash:.4f}")
assert acct.cash >= 0, (
    f"BUG CONFIRMED: cash is {acct.cash:.4f} — the risk layer approved the order "
    "(full-exit exemption) and the broker paid a $1 min fee out of $0.50 proceeds")
