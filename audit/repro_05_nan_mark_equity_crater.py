"""BUG: on a FILL day, run_backtest re-marks equity from the PaperBroker
account, which prices any held symbol whose close is NaN that day at $0.
The top-of-loop mark correctly carries the last known price for NaN closes,
but the fill leg overwrites `equity = account.equity` computed from
fill_prices that EXCLUDE NaN symbols. The equity curve craters by the whole
value of the untouched position, corrupting the curve, maxDD, vol, and
state.last_equity for that bar.
"""
import sys, dataclasses; sys.path.insert(0, "/home/user/Trading-bot-2.0")
import numpy as np
import pandas as pd
from engine.backtest import run_backtest
from engine.config import load_config
from tests.conftest import ConstWeights, with_costs

cfg = load_config("/home/user/Trading-bot-2.0/config/engine.toml")
cfg = with_costs(cfg, fixed_min_fee=0.0, per_share_fee=0.0, spread_bps=0.0, slippage_bps=0.0)
cfg = dataclasses.replace(cfg, universe=("XUU.TO", "ZAG.TO"))

idx = pd.bdate_range("2026-01-05", periods=40)
a = pd.Series(100.0, index=idx)
b = pd.Series(100.0, index=idx)
b.iloc[21] = np.nan          # symbol B has one missing close on the FILL day

prices = pd.DataFrame({"XUU.TO": a, "ZAG.TO": b})

# Decision day 0: buy 50/50 A and B (fills day 1).
# Decision day 20: nudge A's weight (sized so B is untouched); fills day 21,
# the day B's close is NaN.
class Switcher:
    def target_weights(self, prices, today):
        if len(prices) <= 1:
            return {"XUU.TO": 0.45, "ZAG.TO": 0.45}
        return {"XUU.TO": 0.55, "ZAG.TO": 0.45}

res = run_backtest(prices, Switcher(), cfg, initial_equity=10_000.0,
                   is_decision_day=lambda i: i in (0, 20))

eq = res.equity
print(eq.iloc[19:24])
drop = eq.iloc[21] - eq.iloc[20]
print(f"equity change on the NaN day: {drop:,.2f} (nothing was sold; prices flat)")
assert abs(drop) < 100, (
    f"BUG CONFIRMED: equity craters by {drop:,.2f} on a flat-price day because "
    "the held ZAG.TO position was marked at $0 when its close was NaN on a fill day")
