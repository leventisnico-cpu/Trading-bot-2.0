"""R2 #15 — LOW: strategy params are never validated — skip_months >
lookback_months makes DualMomentum crash with a raw IndexError.

_momentum takes a window of lookback*21 + 1 bars and then indexes
`window.iloc[-1 - skip*21]`. Nothing checks skip_months <= lookback_months
(DualMomentum.__init__ validates only top_n; [strategy] is "opaque to the
engine" so validate_config never sees it). The IndexError is not a
HaltError, so on the live path it would escape daily_run's refusal handler
as a traceback — a config typo becomes a crash instead of a ConfigError at
startup or a refusal.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from datetime import date

from engine.errors import EngineError
from engine.strategies import DualMomentum

idx = pd.bdate_range("2020-01-01", periods=600)
prices = pd.DataFrame(100.0, index=idx, columns=["A", "B", "D"])

try:
    dm = DualMomentum(("A", "B", "D"),
                      {"lookback_months": 3, "skip_months": 6,
                       "top_n": 1, "defensive_symbol": "D"})
    w = dm.target_weights(prices, date(2022, 1, 3))
    print(f"weights: {w}")
    outcome = "no error"
except EngineError as exc:
    outcome = f"engine-typed refusal: {type(exc).__name__}: {exc}"
except (ValueError,) as exc:
    outcome = f"validated at construction: {exc}"
except IndexError as exc:
    outcome = f"raw IndexError: {exc}"
print(outcome)

assert not outcome.startswith("raw IndexError"), (
    "BUG CONFIRMED: skip_months=6 with lookback_months=3 crashes "
    f"_momentum with a bare '{outcome}' — strategy params are validated "
    "nowhere (not in validate_config, not in DualMomentum.__init__ beyond "
    "top_n), and IndexError is not a HaltError so the live daily job would "
    "die with a traceback instead of refusing"
)
print("fixed: inconsistent lookback/skip is refused cleanly")
