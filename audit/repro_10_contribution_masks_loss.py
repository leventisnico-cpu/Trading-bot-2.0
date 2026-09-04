"""BUG (FM#1 variant): the daily-loss and drawdown checks compare raw
equities across days, but scripts/daily_run.py deposits the weekly $100
contribution into the broker BEFORE run_cycle evaluates pre_trade. The
deposit is counted as 'return': a market loss well beyond max_daily_loss_pct
is invisible whenever a contribution lands the same day. On the small
accounts this engine is built for ($100/week from $0), $100 is a huge
fraction of equity, so the soft halt is systematically blinded exactly when
it matters most.
"""
import sys; sys.path.insert(0, "/home/user/Trading-bot-2.0")
from datetime import date
from engine.config import load_config
from engine.costs import CostModel
from engine.risk import PreTradeDecision, RiskEngine
from engine.state import EngineState

cfg = load_config("/home/user/Trading-bot-2.0/config/engine.toml")
risk = RiskEngine(cfg.risk, CostModel(cfg.costs))
print("max_daily_loss_pct =", cfg.risk.max_daily_loss_pct)

# Yesterday: equity $1,000 (all in one ETF). Overnight the ETF drops 15%
# (about twice the 8% stand-down limit). This morning is Monday, so
# daily_run credits +$100 into the broker before run_cycle runs.
prior = EngineState(peak_equity=1_000.0, last_equity=1_000.0,
                    last_equity_date="2026-08-28")
market_value_after_crash = 850.0             # -15% true market move
equity_seen_by_pre_trade = market_value_after_crash + 100.0   # + contribution

# FIX (audit round 1): pre_trade grew a net_flows parameter and
# scripts/daily_run.py passes the day's contribution through it — the
# call below mirrors the fixed integration path. The original repro
# called pre_trade without flows, which the API then had no way to learn.
res = risk.pre_trade(prior, equity_seen_by_pre_trade, date(2026, 8, 31),
                     net_flows=100.0)
print(f"true market return: -15.0% | measured daily_return: {res.daily_return:.1%}")
print("decision:", res.decision.value)
assert res.decision is PreTradeDecision.STAND_DOWN, (
    "BUG CONFIRMED: a -15% market day (vs the 8% stand-down limit) was scored "
    f"as {res.daily_return:.1%} because the $100 deposit is mixed into equity; "
    "the engine traded straight through its own daily-loss limit")
