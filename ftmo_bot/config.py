"""FTMO bot settings. Credentials never appear here: the operator logs the
MT5 terminal into the FTMO account by hand and the bot attaches to that
running terminal."""

# Keep: FtmoConfig._check_types reads the field annotations as strings.
from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
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

#: exit rules a new position can get (``exit_mode``); see scale_out.py and fast4.py
EXIT_MODES = ("scale_out", "fast4")

#: annotation -> (accepted Python types, what to write in the YAML)
TYPE_KINDS = {
    "bool": ((bool,), "true or false"),
    "int": ((int,), "a whole number"),
    "float": ((int, float), "a number"),
    "str": ((str,), "text"),
    "Dict[str, str]": ((dict,), "name: symbol lines"),
}


def field_kind(annotation) -> tuple:
    """('float', True) for 'Optional[float]': the TYPE_KINDS key and
    whether null is allowed."""
    t = str(annotation)
    if t.startswith("Optional[") and t.endswith("]"):
        return t[len("Optional["):-1], True
    return t, False


@dataclass
class FtmoConfig:
    symbols: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SYMBOLS))
    risk_per_trade: float = 0.03          # operator's order: 3%
    max_positions: int = 2
    notional_cap: float = 3.0             # x balance, per position (Swing leverage 1:15, US2000 1:9)
    atr_stop_mult: float = 3.0
    # operator's order (2026-11-08): the 5-step trade management. A position
    # keeps the exit rule it was opened with, so switching never strands one.
    exit_mode: str = "scale_out"          # scale_out (the 5 steps) or fast4 (SMA5 / 10 sessions)
    max_hold_sessions: int = 10           # fast4 exits only
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
        self._check_types()
        if not 0 < self.risk_per_trade <= 0.05:
            raise ValueError("risk_per_trade must be in (0, 5%]")
        if self.initial_balance is not None and not 0 < self.initial_balance < 1e12:
            raise ValueError("initial_balance must be positive (the account size) or null")
        if not 0 <= self.target_margin <= 0.02:
            raise ValueError("target_margin must be in [0, 2%]")
        if self.server_clock is not None and self.server_clock not in RULES:
            raise ValueError(f"server_clock must be one of {list(RULES)} or null")
        if self.max_positions < 1:
            raise ValueError("max_positions must be >= 1")
        if self.profit_target is not None and not 0 < self.profit_target <= 1:
            raise ValueError("profit_target must be in (0, 100%] or null")
        if set(self.symbols) - set(DEFAULT_SYMBOLS):
            raise ValueError(f"unknown strategy symbols: {set(self.symbols) - set(DEFAULT_SYMBOLS)}")
        if self.keepalive_symbol not in self.symbols:
            raise ValueError("keepalive_symbol must be one of the symbols")
        if self.login is not None and (isinstance(self.login, bool)
                                       or not isinstance(self.login, int)
                                       or self.login <= 0):
            raise ValueError("login must be the account number from FTMO's email "
                             "(digits only) or null")
        if not 0 < self.max_loss <= 0.20:
            raise ValueError("max_loss must be in (0, 20%] (FTMO: 0.10)")
        if not 0 < self.daily_loss <= self.max_loss:
            raise ValueError("daily_loss must be in (0, max_loss] (FTMO: 0.05)")
        if not 0 <= self.guard_buffer < self.daily_loss:
            raise ValueError("guard_buffer must be in [0, daily_loss)")
        if not 0 < self.notional_cap <= 30:
            raise ValueError("notional_cap must be in (0, 30] x balance")
        if not 0 < self.atr_stop_mult <= 10:
            raise ValueError("atr_stop_mult must be in (0, 10]")
        if self.exit_mode not in EXIT_MODES:
            raise ValueError("exit_mode must be scale_out (the 5-step exits) or fast4 "
                             "(close over SMA5 or 10 sessions)")
        if self.max_hold_sessions < 1 or self.magic <= 0:
            raise ValueError("max_hold_sessions must be >= 1 and magic positive")
        if self.min_trading_days < 0 or self.keepalive_days < 0:
            raise ValueError("min_trading_days and keepalive_days must be >= 0")

    def _check_types(self) -> None:
        """Every setting has its declared type. A key left blank in YAML is
        null, not its default: `cap_combined_risk:` would turn the cap off
        and `dry_run:` would count as live, so both refuse to load."""
        for f in fields(self):
            v = getattr(self, f.name)
            kind, optional = field_kind(f.type)
            accepted, want = TYPE_KINDS[kind]
            if f.name == "login":
                want = "the account number from FTMO's email (digits only)"
            if v is None:
                if optional:
                    continue
                raise ValueError(f"{f.name} must be {want}, not blank")
            ok = isinstance(v, accepted) and (kind == "bool" or not isinstance(v, bool))
            if ok and isinstance(v, dict):
                ok = all(isinstance(k, str) and isinstance(x, str) for k, x in v.items())
            if not ok:
                # a password pasted into login: must never be printed back
                shown = ({"str": "text", "float": "a decimal number", "bool": "a yes/no value",
                          "list": "a list", "dict": "a mapping"}.get(type(v).__name__,
                                                                     "another kind of value")
                         if f.name == "login" else repr(v))
                raise ValueError(f"{f.name} must be {want}, not {shown}")


SECRET_KEYS = {"password", "login_password", "investor_password", "token",
               "api_key", "secret"}


def load(path: str | Path) -> FtmoConfig:
    # utf-8-sig: Windows Notepad may save a byte-order mark
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8-sig"))
    except yaml.YAMLError as e:
        # never str(e) or the chained error: YAML quotes the bad line, which
        # may hold a pasted password (setup.ps1 prints tracebacks as they are)
        mark = getattr(e, "problem_mark", None)
        where = f" at line {mark.line + 1}" if mark is not None else ""
        raise ValueError(f"not valid YAML{where}; check that line in Notepad") from None
    if raw is None:                                  # an empty file: the defaults
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("the config must be `key: value` lines")
    bad = SECRET_KEYS & {str(k).lower() for k in raw}
    if bad:
        raise ValueError(f"credentials do not belong in the config: {sorted(bad)}")
    unknown = sorted(str(k) for k in set(raw) - {f.name for f in fields(FtmoConfig)})
    if unknown:
        raise ValueError(f"unknown settings {unknown}: check the spelling")
    login = raw.get("login")
    if isinstance(login, str) and re.fullmatch(r"[0-9]{1,20}", login.strip()):
        raw["login"] = int(login.strip())                    # login: "1234567"
    cfg = FtmoConfig(**raw)
    cfg.validate()
    return cfg
