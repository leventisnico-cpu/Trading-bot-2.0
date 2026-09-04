"""R2 #11 — LOW: config validation accepts max_gross_exposure <= 0 (even
negative) whenever allow_leverage=true — and clamp_weights then emits
NEGATIVE target weights with allow_short=false.

validate_config: `_check(0 < r.max_gross_exposure <= 1 or r.allow_leverage, ...)`
— the disjunction was written for "leverage may exceed 1" but it also waves
through 0 and negative values. clamp_weights applies the no-short clamp
per-symbol FIRST, then scales by cap/gross; a negative cap makes the scale
negative and flips every long into a short AFTER the no-short clamp ran.
Two structural invariants (§3.4 no shorts, validated config) fail together
on a config the validator was built to refuse.
"""
import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.config import load_config, validate_config
from engine.costs import CostModel
from engine.errors import ConfigError
from engine.risk import RiskEngine

REPO = Path(__file__).resolve().parents[1]
cfg = load_config(REPO / "config" / "engine.toml")
bad = dataclasses.replace(cfg, risk=dataclasses.replace(
    cfg.risk, allow_leverage=True, max_gross_exposure=-1.0))

try:
    validate_config(bad)
    accepted = True
    print("validate_config ACCEPTED allow_leverage=true, max_gross_exposure=-1.0")
except ConfigError as exc:
    accepted = False
    print(f"validate_config rejected it: {exc}")

weights = {}
if accepted:
    risk = RiskEngine(bad.risk, CostModel(cfg.costs))
    weights = risk.clamp_weights({"XUU.TO": 0.5, "XEF.TO": 0.5})
    print(f"clamp_weights output with allow_short=False: {weights}")

assert not accepted or all(w >= 0 for w in weights.values()), (
    f"BUG CONFIRMED: validate_config accepted max_gross_exposure=-1.0 (any "
    f"value passes once allow_leverage=true) and clamp_weights turned long "
    f"targets into SHORTS {weights} despite allow_short=false — the gross-"
    "exposure scale is applied after the no-short clamp with an unvalidated, "
    "negative cap"
)
print("fixed: non-positive gross exposure is refused / shorts cannot emerge")
