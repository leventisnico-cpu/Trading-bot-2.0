"""Strategy layer: abstract base class and concrete strategies."""

from .adaptive_ema import AdaptiveEmaCrossoverStrategy, VolRegime
from .base import BaseStrategy
from .ema_crossover import EmaCrossoverStrategy
from .scheduled_dca import ScheduledDcaStrategy
from .tsmom_12_1 import TimeSeriesMomentumStrategy

__all__ = ["AdaptiveEmaCrossoverStrategy", "BaseStrategy",
           "EmaCrossoverStrategy", "ScheduledDcaStrategy",
           "TimeSeriesMomentumStrategy", "VolRegime"]
