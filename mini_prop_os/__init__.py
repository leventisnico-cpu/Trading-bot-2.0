"""Mini-Prop OS — an autonomous, risk-gated live/paper trading system for IBKR.

Layered architecture (dependencies point downward only):

    main.py / app.py          asyncio lifecycle, wiring, signal handling
        core/connection.py    IBKR socket, heartbeat, auto-reconnect   (ib_insync)
        execution/oms.py      order state machine, fills, exec log     (pure)
        risk/guardrails.py    pre-trade checks, daily-loss kill switch (pure)
        strategy/             BaseStrategy + concrete strategies       (pure)
        core/config.py        typed config loaded from config.yaml     (pure)

"pure" modules import no broker library so they are unit-testable without a
TWS/Gateway instance and run in CI with only the standard library + PyYAML.
"""

from __future__ import annotations

__version__ = "1.0.0"
