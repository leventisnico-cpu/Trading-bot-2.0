"""Market-data-type selection, kept broker-agnostic for testing.

IBKR serves one *market data type* per API session: real-time (needs a
paid subscription), frozen, or delayed (free, 15-20 minutes behind). An
unfunded paper account gets nothing unless ``delayed`` is requested
explicitly, so the app issues ``reqMarketDataType`` right after every
connect — before any bar request — with the code configured under
``connection.market_data_type``.
"""

from __future__ import annotations

import logging
from typing import Any

from .config import MARKET_DATA_TYPE_CODES

log = logging.getLogger(__name__)


def request_market_data_type(ib: Any, mode: str) -> int:
    """Issue ``ib.reqMarketDataType`` for ``mode``; returns the code sent.

    ``ib`` only needs a ``reqMarketDataType(int)`` method, so a stub works
    in tests. Raises ``ValueError`` for an unknown mode (config validation
    makes that unreachable in production).
    """
    try:
        code = MARKET_DATA_TYPE_CODES[mode]
    except KeyError:
        raise ValueError(f"unknown market data type {mode!r}") from None
    ib.reqMarketDataType(code)
    log.info("requested %s market data (reqMarketDataType %d)", mode, code)
    return code
