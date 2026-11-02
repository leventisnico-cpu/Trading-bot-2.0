"""MetaTrader 5 adapter. The only module that imports ``MetaTrader5``
(Windows-only package). It attaches to the terminal the operator has
already logged into; it never receives, stores or sends a password.

Bar stamps are in the server's local time (``server_clock``). The rule
that converts them is fitted to the clock reading of a fresh tick and
checked again before every bar read. A tick counts as fresh only if it
moved since a look taken at most two minutes earlier, so a stale stamp
(market closed, daily break, holiday) can never date the clock; it just
leaves the last verified rule in place. In strict mode (the trading
loop) the bot refuses to serve bars before a first verification, and
whenever a fresh reading fits no candidate rule, so a wrong session
boundary can never turn into a plan; the planning tick simply retries."""

from __future__ import annotations

import logging
import time as _time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from . import server_clock
from .broker import Account, Bar, Fill, Position, Spec

log = logging.getLogger("ftmo_bot")
#: patched in tests; the start-up verification polls for a moving tick
SLEEP = _time.sleep


class MT5Broker:
    def __init__(self, path: Optional[str] = None, probe: Optional[str] = None,
                 strict: bool = True, rule: Optional[str] = None) -> None:
        """``probe``: a liquid symbol whose ticks date the server clock.
        ``rule``: pin a ``server_clock.RULES`` entry instead of fitting one."""
        import MetaTrader5 as mt5   # imported here so CI never needs it
        self.mt5 = mt5
        self.probe = probe
        self.strict = strict
        if rule is not None and rule not in server_clock.RULES:
            raise ValueError(f"unknown server_clock {rule!r}; "
                             f"one of {list(server_clock.RULES)}")
        self.pinned = rule is not None
        self.rule = rule or "NY+7"
        self.candidates = [self.rule] if self.pinned else list(server_clock.ORDER)
        self.offset: Optional[timedelta] = None
        self.verified_at: Optional[datetime] = None
        self._looks: Dict[str, Tuple[float, datetime]] = {}
        ok = mt5.initialize(path) if path else mt5.initialize()
        if not ok:
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}. "
                               "Open the FTMO MT5 terminal and log in first.")
        if probe:
            self.verify(probe)                   # a weekend start just warns

    # ------------------------------------------------------------ clock
    def _measure(self, symbol: str) -> Optional[timedelta]:
        """The server offset from ``symbol``'s last tick, or None unless
        that tick moved since a look taken at most ``TOLERANCE`` seconds
        ago (then it is at most that old, and the stamp dates the clock)."""
        self.mt5.symbol_select(symbol, True)
        t = self.mt5.symbol_info_tick(symbol)
        if t is None:
            return None
        msc = getattr(t, "time_msc", None)
        stamp = msc / 1000 if msc else float(t.time)
        now = self.now()
        prev = self._looks.get(symbol)
        self._looks[symbol] = (stamp, now)
        if prev is None or stamp <= prev[0]:
            return None
        if (now - prev[1]).total_seconds() > server_clock.TOLERANCE:
            return None
        return server_clock.measure(stamp, now)

    def verify(self, symbol: str, tries: int = 10) -> None:
        """Start-up: poll ``symbol`` about once a second for a moving tick."""
        for _ in range(tries):
            self.check(symbol, strict=False, quiet=True)
            if self.verified_at is not None:
                return
            SLEEP(1)
        log.warning("server clock unverified: no moving %s tick (market closed, "
                    "or the PC clock is more than 2 minutes off); assuming rule %s",
                    symbol, self.rule)

    def check(self, symbol: str, strict: bool, quiet: bool = False) -> None:
        """Fit the clock rule to a fresh tick of ``symbol`` (or the probe).
        Several rules can fit for most of the year; the first time they
        disagree the fit narrows to the ones that still hold. Without a
        fresh tick nothing changes; strict mode raises if the clock has
        never been verified, or if a fresh reading fits no candidate."""
        now = self.now()
        off = self._measure(symbol)
        if off is None and self.probe and symbol != self.probe:
            off = self._measure(self.probe)
        if off is None:
            if strict and self.verified_at is None:
                raise RuntimeError(
                    f"server clock unverified: no moving {symbol} tick yet "
                    f"(market closed, or the PC clock is off); retrying")
            return
        fits = server_clock.matching(off, now)
        common = [r for r in self.candidates if r in fits]
        if not common:
            msg = (f"server clock reads {server_clock.describe(off)} now, which "
                   f"fits {fits or 'no known rule'}, not {self.candidates}; set "
                   "server_clock in the config to the right rule")
            if strict:
                raise RuntimeError(msg)
            if not quiet:
                log.warning(msg)
            return
        if common[0] != self.rule:
            log.warning("server clock rule %s -> %s (reads %s now)", self.rule,
                        common[0], server_clock.describe(off))
        self.rule, self.candidates = common[0], common
        self.offset, self.verified_at = off, now

    def clock_status(self) -> str:
        if self.verified_at is None or self.offset is None:
            return f"unverified (no fresh tick); assuming rule {self.rule}"
        also = [r for r in self.candidates if r != self.rule]
        return (f"{server_clock.describe(self.offset)} at "
                f"{self.verified_at:%Y-%m-%d %H:%M} UTC, rule {self.rule}"
                + (f" (also fits {', '.join(also)})" if also else "")
                + (" [pinned]" if self.pinned else ""))

    def _to_utc(self, server_epoch: int) -> datetime:
        server = datetime.fromtimestamp(server_epoch, timezone.utc).replace(tzinfo=None)
        return server_clock.to_utc(self.rule, server)

    # ------------------------------------------------------------ reads
    def account(self) -> Account:
        a = self.mt5.account_info()
        t = self.mt5.terminal_info()
        if a is None or t is None:
            raise RuntimeError(f"no account: {self.mt5.last_error()}")
        return Account(a.login, a.server, a.currency, a.balance, a.equity,
                       bool(t.trade_allowed and a.trade_allowed))

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def bars(self, symbol: str, minutes: int, count: int) -> List[Bar]:
        self.check(symbol, self.strict)
        tf = {30: self.mt5.TIMEFRAME_M30, 15: self.mt5.TIMEFRAME_M15,
              60: self.mt5.TIMEFRAME_H1}[minutes]
        self.mt5.symbol_select(symbol, True)
        rates = self.mt5.copy_rates_from_pos(symbol, tf, 0, count)
        if rates is None:
            raise RuntimeError(f"no bars for {symbol}: {self.mt5.last_error()}")
        return [(self._to_utc(int(r["time"])), float(r["open"]), float(r["high"]),
                 float(r["low"]), float(r["close"])) for r in rates]

    def quote(self, symbol: str) -> Tuple[float, float]:
        t = self.mt5.symbol_info_tick(symbol)
        if t is None:
            raise RuntimeError(f"no quote for {symbol}")
        return t.bid, t.ask

    def spec(self, symbol: str) -> Spec:
        i = self.mt5.symbol_info(symbol)
        if i is None:
            return Spec(False)
        return Spec(True, i.volume_min, i.volume_step, i.volume_max)

    def loss_per_lot(self, symbol: str, entry: float, stop: float) -> float:
        p = self.mt5.order_calc_profit(self.mt5.ORDER_TYPE_BUY, symbol, 1.0,
                                       entry, stop)
        if p is None:
            raise RuntimeError(f"order_calc_profit failed: {self.mt5.last_error()}")
        return -float(p)

    def positions(self, magic: int) -> List[Position]:
        ps = self.mt5.positions_get()
        if ps is None:                      # an error, not "no positions"
            code = self.mt5.last_error()
            if code and code[0] != 1:       # 1 = RES_S_OK
                raise RuntimeError(f"positions_get failed: {code}")
            ps = ()
        return [Position(p.ticket, p.symbol, p.volume, p.price_open, p.sl)
                for p in ps if p.magic == magic]

    # ----------------------------------------------------------- orders
    def _filling(self, symbol: str) -> int:
        mode = self.mt5.symbol_info(symbol).filling_mode
        if mode & 1:
            return self.mt5.ORDER_FILLING_FOK
        if mode & 2:
            return self.mt5.ORDER_FILLING_IOC
        return self.mt5.ORDER_FILLING_RETURN

    def _send(self, req: dict) -> Fill:
        r = self.mt5.order_send(req)
        if r is None:
            return Fill(False, message=str(self.mt5.last_error()))
        ok = r.retcode == self.mt5.TRADE_RETCODE_DONE
        return Fill(ok, r.price, r.order, f"{r.retcode} {r.comment}")

    def _round(self, symbol: str, price: float) -> float:
        i = self.mt5.symbol_info(symbol)
        tick = i.trade_tick_size or 10 ** -i.digits
        return round(round(price / tick) * tick, i.digits)

    def buy(self, symbol: str, volume: float, sl: Optional[float],
            magic: int, comment: str) -> Fill:
        _, ask = self.quote(symbol)
        req = dict(action=self.mt5.TRADE_ACTION_DEAL, symbol=symbol,
                   volume=volume, type=self.mt5.ORDER_TYPE_BUY, price=ask,
                   deviation=20, magic=magic, comment=comment[:31],
                   type_time=self.mt5.ORDER_TIME_GTC,
                   type_filling=self._filling(symbol))
        if sl:
            req["sl"] = self._round(symbol, sl)
        return self._send(req)

    def close(self, position: Position, magic: int, comment: str) -> Fill:
        bid, _ = self.quote(position.symbol)
        req = dict(action=self.mt5.TRADE_ACTION_DEAL, symbol=position.symbol,
                   volume=position.volume, type=self.mt5.ORDER_TYPE_SELL,
                   position=position.ticket, price=bid, deviation=20,
                   magic=magic, comment=comment[:31],
                   type_time=self.mt5.ORDER_TIME_GTC,
                   type_filling=self._filling(position.symbol))
        return self._send(req)
