"""FTMO bot settings. Credentials never appear here: the operator logs the
MT5 terminal into the FTMO account by hand and the bot attaches to that
running terminal."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

import yaml

#: FAST-4 universe: strategy name -> default FTMO MT5 symbol. Check the
#: names in the terminal's Market Watch; `python -m ftmo_bot preflight`
#: reports any that do not exist.
DEFAULT_SYMBOLS = {
    "US100": "US100.cash",
    "US500": "US500.cash",
    "US30": "US30.cash",
    "US2000": "US2000.cash",
}


@dataclass
class FtmoConfig:
    symbols: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SYMBOLS))
    risk_per_trade: float = 0.03          # operator's order: 3%
    max_positions: int = 2
    notional_cap: float = 5.0             # x balance, per position
    atr_stop_mult: float = 3.0
    max_hold_sessions: int = 10
    initial_balance: Optional[float] = None   # set at first start, in account currency
    profit_target: Optional[float] = 0.10     # 0.10 phase 1, 0.05 phase 2, null funded
    min_trading_days: int = 4
    max_loss: float = 0.10
    daily_loss: float = 0.05
    guard_buffer: float = 0.002           # flatten this close to a limit
    keepalive_days: int = 25              # evaluation only; null-equivalent: 0
    keepalive_symbol: str = "US500"
    magic: int = 404040
    dry_run: bool = True                  # orders are only logged unless False
    state_path: str = "state/ftmo_state.json"
    log_path: str = "state/ftmo_bot.log"
    mt5_path: Optional[str] = None        # terminal64.exe path if not default

    def validate(self) -> None:
        if not 0 < self.risk_per_trade <= 0.05:
            raise ValueError("risk_per_trade must be in (0, 5%]")
        if self.max_positions < 1:
            raise ValueError("max_positions must be >= 1")
        if self.profit_target is not None and self.profit_target <= 0:
            raise ValueError("profit_target must be positive or null")
        if set(self.symbols) - set(DEFAULT_SYMBOLS):
            raise ValueError(f"unknown strategy symbols: {set(self.symbols) - set(DEFAULT_SYMBOLS)}")
        if self.keepalive_symbol not in self.symbols:
            raise ValueError("keepalive_symbol must be one of the symbols")


SECRET_KEYS = {"password", "login_password", "investor_password", "token",
               "api_key", "secret"}


def load(path: str | Path) -> FtmoConfig:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    bad = SECRET_KEYS & {k.lower() for k in raw}
    if bad:
        raise ValueError(f"credentials do not belong in the config: {sorted(bad)}")
    cfg = FtmoConfig(**raw)
    cfg.validate()
    return cfg
