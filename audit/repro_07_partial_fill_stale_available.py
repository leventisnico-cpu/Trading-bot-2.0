"""BUG: execute_rebalance only debits `available` for is_success (FILLED)
results. A PARTIALLY_FILLED buy consumed real cash at the broker but leaves
`available` untouched, so the next buy is sized against cash that no longer
exists — the very thing §5.2 claims cannot happen. The oversized order is
then REJECTED outright by the broker instead of being resized down, so a
buy that was perfectly affordable at reduced size is lost.
"""
import sys; sys.path.insert(0, "/home/user/Trading-bot-2.0")
from engine.broker import PaperBroker, PaperBrokerKnobs
from engine.config import load_config
from engine.costs import CostModel
from engine.execution import execute_rebalance
from engine.orders import Order, OrderStatus, Side
from engine.risk import RiskEngine

cfg = load_config("/home/user/Trading-bot-2.0/config/engine.toml")
cm = CostModel(cfg.costs)
risk = RiskEngine(cfg.risk, cm)

prices = {"A": 100.0, "B": 100.0}
knobs = PaperBrokerKnobs(fill_fraction={"A": 0.6})     # IOC-style partial fill
broker = PaperBroker(cash=1_000.0, prices=prices, cost_model=cm, knobs=knobs)

orders = [Order(symbol="A", side=Side.BUY, shares=10),   # partial: 6 fill, ~$603 spent
          Order(symbol="B", side=Side.BUY, shares=5)]    # $502 needed; only ~$396 left

outcome = execute_rebalance(broker, risk, orders, prices)
for r in outcome.results:
    print(f"{r.order.symbol}: {r.status.value}, filled {r.filled_shares}")
print("dropped:", [(d.order.symbol, d.reason) for d in outcome.dropped])
print(f"broker cash now: {broker.get_account().cash:.2f}")

b = [r for r in outcome.results if r.order.symbol == "B"]
assert b and b[0].status is not OrderStatus.REJECTED, (
    "BUG CONFIRMED: buy B was submitted for the full 5 shares against stale "
    "`available` ($1000) although only ~$396 remained after A's partial fill; "
    "the broker rejected it wholesale — the resize-to-cash logic never ran, "
    "and 3 affordable shares of B were never bought")
