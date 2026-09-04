"""BUG (FM#4 variant): an order that sells the ENTIRE position is not
flagged is_full_exit when the target weight is small-but-nonzero and
floors to 0 shares. compute_orders only sets is_full_exit when
tgt_w == 0.0 exactly; tgt_shares == 0 with cur_shares > 0 produces a
plain SELL of every share, which the min_order_notional filter (or the
no-trade band) then eats. The position can never close — precisely the
ratchet §5.4 claims is impossible.
"""
import sys; sys.path.insert(0, "/home/user/Trading-bot-2.0")
from engine.config import load_config
from engine.costs import CostModel
from engine.portfolio import compute_orders
from engine.risk import RiskEngine

cfg = load_config("/home/user/Trading-bot-2.0/config/engine.toml")
risk = RiskEngine(cfg.risk, CostModel(cfg.costs))

# Held: 3 shares @ $30 = $90. Target weight 0.4% of $5,000 = $20 -> floor 0 shares.
orders = compute_orders({"A": 3.0}, {"A": 0.004}, {"A": 30.0}, 5000.0,
                        no_trade_band=0.0)
print("orders:", [(o.side.value, o.shares, o.is_full_exit) for o in orders])
assert orders and orders[0].shares == 3.0, "expected a sell of the whole position"

approved, dropped = risk.filter_orders(orders, {"A": 30.0})
print("kept:", approved.orders)
print("dropped:", [(d.order.symbol, d.reason) for d in dropped])
assert approved.orders, (
    "BUG CONFIRMED: the order that would close the ENTIRE position was dropped "
    f"({dropped[0].reason}) because is_full_exit was False — every future "
    "rebalance regenerates and re-drops the same order; the position never closes")
