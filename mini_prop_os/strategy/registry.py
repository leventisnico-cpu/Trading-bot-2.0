"""Strategy registry + the deployability marker every strategy must carry.

Every concrete strategy module declares, in its module docstring, a line::

    DEPLOYABLE: yes
    DEPLOYABLE: no

``yes`` may only be written after ``scripts/expectancy.py`` passes for the
strategy; ``.github/workflows/expectancy.yml`` re-runs the gate on every
push and fails the build if a strategy marked ``yes`` no longer beats
buy-and-hold. ``main.py`` refuses to start on a live port unless the
configured strategy is marked ``yes`` (see :func:`refuse_live_reason`).

A missing marker counts as **not** deployable.
"""

from __future__ import annotations

import importlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from ..core.config import is_live_port
from .base import BaseStrategy

_MARKER = re.compile(r"^\s*DEPLOYABLE:\s*(yes|no)\s*$",
                     re.IGNORECASE | re.MULTILINE)

#: Modules in this package that are infrastructure, not strategies.
NON_STRATEGY_MODULES = frozenset({"__init__", "base", "registry", "ensemble"})

#: Factory signature: (symbol, lot size, contract multiplier) -> strategy.
Factory = Callable[[str, int, float], BaseStrategy]


@dataclass(frozen=True)
class StrategySpec:
    name: str
    module: str
    factory: Factory
    #: True for strategies that only ever add exposure (never sell). The
    #: expectancy gate funds such an account for every scheduled lot so
    #: the measurement is not an artifact of running out of cash.
    accumulates: bool = False


def _ema(symbol: str, lot: int, multiplier: float) -> BaseStrategy:
    from .ema_crossover import EmaCrossoverStrategy
    return EmaCrossoverStrategy(symbol, fast_period=9, slow_period=21,
                                order_quantity=lot)


def _adaptive(symbol: str, lot: int, multiplier: float) -> BaseStrategy:
    from .adaptive_ema import AdaptiveEmaCrossoverStrategy
    return AdaptiveEmaCrossoverStrategy(
        symbol, fast_period=9, slow_period=21, base_quantity=lot,
        multiplier=multiplier)


def _dca(symbol: str, lot: int, multiplier: float) -> BaseStrategy:
    from .scheduled_dca import ScheduledDcaStrategy
    # Daily replay bars are stamped at 00:00 UTC, so the schedule is
    # evaluated in UTC at midnight; state stays in memory for measurement.
    return ScheduledDcaStrategy(symbol, quantity=lot, schedule="weekly",
                                weekday="Monday", time_of_day="00:00",
                                timezone="UTC", state_path=None)


STRATEGIES: Dict[str, StrategySpec] = {
    "ema_crossover": StrategySpec("ema_crossover",
                                  "mini_prop_os.strategy.ema_crossover", _ema),
    "adaptive_ema": StrategySpec("adaptive_ema",
                                 "mini_prop_os.strategy.adaptive_ema",
                                 _adaptive),
    "scheduled_dca": StrategySpec("scheduled_dca",
                                  "mini_prop_os.strategy.scheduled_dca", _dca,
                                  accumulates=True),
}


def strategy_names() -> Tuple[str, ...]:
    return tuple(STRATEGIES)


def get_spec(name: str) -> StrategySpec:
    try:
        return STRATEGIES[name]
    except KeyError:
        raise KeyError(f"unknown strategy {name!r}; known: "
                       f"{sorted(STRATEGIES)}") from None


def deployable_marker(doc: Optional[str]) -> Optional[bool]:
    """Parse the ``DEPLOYABLE:`` line; None if the marker is absent."""
    if not doc:
        return None
    m = _MARKER.search(doc)
    if m is None:
        return None
    return m.group(1).lower() == "yes"


def is_deployable(name: str) -> bool:
    """True only if the strategy's module docstring says ``DEPLOYABLE: yes``."""
    spec = get_spec(name)
    module = importlib.import_module(spec.module)
    return deployable_marker(module.__doc__) is True


def unregistered_strategy_modules() -> Tuple[str, ...]:
    """Strategy modules on disk that the registry does not know — CI fails
    on these so no strategy can dodge the gate by not registering."""
    pkg = Path(__file__).resolve().parent
    known = {spec.module.rsplit(".", 1)[1] for spec in STRATEGIES.values()}
    return tuple(sorted(
        p.stem for p in pkg.glob("*.py")
        if p.stem not in NON_STRATEGY_MODULES and p.stem not in known))


def refuse_live_reason(strategy_name: str, port: int) -> Optional[str]:
    """Why the bot must not start with ``strategy_name`` on ``port``, or
    None if starting is allowed. Paper ports are always allowed."""
    if not is_live_port(port):
        return None
    try:
        ok = is_deployable(strategy_name)
    except KeyError as exc:
        return str(exc)
    if not ok:
        return (f"strategy {strategy_name!r} is not marked DEPLOYABLE: yes "
                f"(it has not beaten buy-and-hold under "
                f"scripts/expectancy.py); refusing to start on LIVE port "
                f"{port}. Use a paper port (7497/4002).")
    return None
