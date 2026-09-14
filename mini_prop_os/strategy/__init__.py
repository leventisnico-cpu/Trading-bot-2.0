"""Strategy layer: abstract base class and concrete strategies."""

from .base import BaseStrategy
from .ema_crossover import EmaCrossoverStrategy

__all__ = ["BaseStrategy", "EmaCrossoverStrategy"]
