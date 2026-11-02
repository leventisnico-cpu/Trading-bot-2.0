"""FTMO bot settings. Credentials never appear here: the operator logs the
MT5 terminal into the FTMO account by hand and the bot attaches to that
running terminal."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

import yaml

from .server_clock import RULES

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
    notional_cap: float = 3.0             # x balance, per position (Swing leverage 1:15, US2000 1:9)
    atr_stop_mult: float = 3.0
    max_hold_sessions: int = 10
    initial_balance: Optional[float] = None   # null: a new account's balance (FTMO accounts start at their size)
    profit_target: Optional[float] = 0.10     # 0.10 phase 1, 0.05 phase 2, null funded
    min_trading_days: int = 4
    max_loss: float = 0.10
    daily_loss: float = 0.05
    guard_buffer: float = 0.002           # flatten this close to a limit
    cap_combined_risk: bool = True        # all open stops together never cross a loss line
    target_margin: float = 0.003          # lock the target this far above it (closing costs)
    keepalive_days: int = 25              # every phase (FTMO closes inactive accounts); 0 = off
    keepalive_symbol: str = "US500"
    magic: int = 404040
    dry_run: bool = True                  # orders are only logged unless False
    state_path: str = "state/ftmo_state.json"
    log_path: str = "state/ftmo_bot.log"
    mt5_path: Optional[str] = None        # terminal64.exe path if not default
    server_clock: Optional[str] = None    # NY+7, EET, CET or UTC; null = fit it to the terminal
    login: Optional[int] = None           # the only account orders may go to (its number, not a password)

    def validate(self) -> None:
        if not 0 < self.risk_per_trade <= 0.05:
            raise ValueError("risk_per_trade must be in (0, 5%]")
        if self.initial_balance is not None and not self.initial_balance > 0:
            raise ValueError("initial_balance must be positive (the account size) or null")
        if not 0 <= self.target_margin <= 0.02:
            raise ValueError("target_margin must be in [0, 2%]")
        if self.server_clock is not None and self.server_clock not in RULES:
            raise ValueError(f"server_clock must be one of {list(RULES)} or null")
        if self.max_positions < 1:
            raise ValueError("max_positions must be >= 1")
        if self.profit_target is not None and self.profit_target <= 0:
            raise ValueError("profit_target must be positive or null")
        if set(self.symbols) - set(DEFAULT_SYMBOLS):
            raise ValueError(f"unknown strategy symbols: {set(self.symbols) - set(DEFAULT_SYMBOLS)}")
        if self.keepalive_symbol not in self.symbols:
            raise ValueError("keepalive_symbol must be one of the symbols")
        if self.login is not None and (isinstance(self.login, bool)
                                       or not isinstance(self.login, int)
                                       or self.login <= 0):
            raise ValueError("login must be the account number from FTMO's email "
                             "(digits only, no quotes) or null")


SECRET_KEYS = {"password", "login_password", "investor_password", "token",
               "api_key", "secret"}


def load(path: str | Path) -> FtmoConfig:
    # utf-8-sig: Windows Notepad may save a byte-order mark
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8-sig")) or {}
    bad = SECRET_KEYS & {k.lower() for k in raw}
    if bad:
        raise ValueError(f"credentials do not belong in the config: {sorted(bad)}")
    cfg = FtmoConfig(**raw)
    cfg.validate()
    return cfg
