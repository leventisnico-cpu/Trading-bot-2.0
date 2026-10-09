"""MetaTrader 5 adapter. The only module that imports ``MetaTrader5``
(Windows-only package). It attaches to the terminal the operator has
already logged into; it never receives, stores or sends a password."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from .broker import Account, Bar, Fill, Position, Spec

NY = ZoneInfo("America/New_York")
#: FTMO's MT5 server clock runs 7 hours ahead of New York all year
#: (New York 17:00 = server midnight), so server time - 7 h = NY time.
SERVER_MINUS_NY = timedelta(hours=7)


class MT5Broker:
    def __init__(self, path: Optional[str] = None,
                 server_minus_ny: timedelta = SERVER_MINUS_NY) -> None:
        import MetaTrader5 as mt5   # imported here so CI never needs it
        self.mt5 = mt5
        self.offset = server_minus_ny
        ok = mt5.initialize(path) if path else mt5.initialize()
        if not ok:
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}. "
                               "Open the FTMO MT5 terminal and log in first.")

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

    def _to_utc(self, server_epoch: int) -> datetime:
        server = datetime.fromtimestamp(server_epoch, timezone.utc).replace(tzinfo=None)
        return (server - self.offset).replace(tzinfo=NY).astimezone(timezone.utc)

    def bars(self, symbol: str, minutes: int, count: int) -> List[Bar]:
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
