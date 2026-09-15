"""Strategy layer: abstract base class and concrete strategies."""

from .adaptive_ema import AdaptiveEmaCrossoverStrategy, VolRegime
from .base import BaseStrategy
from .ema_crossover import EmaCrossoverStrategy

__all__ = ["AdaptiveEmaCrossoverStrategy", "BaseStrategy",
           "EmaCrossoverStrategy", "VolRegime"]
