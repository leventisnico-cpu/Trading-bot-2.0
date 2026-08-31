"""Engine error hierarchy.

HaltError and its subclasses mean "refuse to trade". They must never be
caught-and-continued on the trading path: the runner lets them propagate,
journals them, and exits without placing orders.
"""


class EngineError(Exception):
    """Base for all engine errors."""


class ConfigError(EngineError):
    """Configuration is missing, malformed, or out of range."""


class HaltError(EngineError):
    """The system must not trade. Manual attention required."""


class StateError(HaltError):
    """Durable state is unreadable or invalid. Never reset to defaults."""


class DataError(HaltError):
    """Price data is missing, stale, or NaN for a required symbol."""


class ExecutionError(EngineError):
    """An order-execution step failed in a way that needs attention."""
