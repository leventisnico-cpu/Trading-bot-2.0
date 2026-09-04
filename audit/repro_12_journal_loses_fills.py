"""BUG: execute_rebalance journals order_result lines only AFTER the whole
rebalance loop completes. If the venue dies mid-flight (ExecutionError from
a later order), the fills that ALREADY HAPPENED are never journaled — the
'append-only evidence' (§11) is silent about real executed trades, and
run_cycle/daily_run let the exception erase the cycle's state save too.
"""
import sys, tempfile; sys.path.insert(0, "/home/user/Trading-bot-2.0")
import json
from pathlib import Path
from engine.broker import PaperBroker, PaperBrokerKnobs
from engine.config import load_config
from engine.costs import CostModel
from engine.errors import ExecutionError
from engine.execution import execute_rebalance
from engine.journal import Journal
from engine.orders import Order, Side
from engine.risk import RiskEngine

cfg = load_config("/home/user/Trading-bot-2.0/config/engine.toml")
cm = CostModel(cfg.costs)
risk = RiskEngine(cfg.risk, cm)
tmp = Path(tempfile.mkdtemp())
journal = Journal(tmp / "journal.jsonl")

prices = {"A": 100.0, "B": 100.0}
broker = PaperBroker(cash=0.0, prices=prices, cost_model=cm,
                     positions={"A": 50.0, "B": 50.0},
                     knobs=PaperBrokerKnobs(outage_after_n_orders=1))
orders = [Order(symbol="A", side=Side.SELL, shares=50, is_full_exit=True),
          Order(symbol="B", side=Side.SELL, shares=50, is_full_exit=True)]
try:
    execute_rebalance(broker, risk, orders, prices, journal=journal)
except ExecutionError as exc:
    print("mid-flight outage:", exc)

acct = broker.get_account()
print(f"broker reality: cash={acct.cash:.2f}, positions={acct.positions} "
      "(the sell of A REALLY filled)")
jpath = tmp / "journal.jsonl"
events = ([json.loads(l) for l in jpath.read_text().splitlines()]
          if jpath.exists() else [])   # file may not even exist: nothing was ever recorded
print("journal events recorded:", len(events))
fills_logged = [e for e in events if e["type"] == "order_result"]
print("order_result lines in journal:", fills_logged)
assert fills_logged, (
    "BUG CONFIRMED: 50 shares of A were actually sold (cash went from 0 to "
    f"{acct.cash:.2f}) but the journal contains ZERO order_result entries — "
    "the evidence log has no record that the trade happened")
