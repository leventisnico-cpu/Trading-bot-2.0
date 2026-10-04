"""A simulated FTMO account for shadow runs: the real ``Runner`` trades it
against recorded or live intraday bars (e.g. ETF proxies of the index
CFDs), so every order, stop, guard and limit path runs on market data
without MetaTrader.

Time only moves forward through ``advance_to``. A bar is visible once it
has ended, quotes are the last visible close (with a small spread), and a
resting stop fills at the stop price, or at the bar's open if the bar
opens through it. Account currency is treated as the instruments'
currency (no FX)."""

from __future__ import annotations

import csv
import json
from bisect import bisect_right
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .broker import Account, Bar, Fill, Position, Spec

BAR = timedelta(minutes=30)


def load_csv(path: Path) -> List[Bar]:
    """Astral price export: timestamp (bar start, UTC), open, high, low, close."""
    out = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            t = datetime.strptime(r["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
            out.append((t.astimezone(timezone.utc), float(r["open"]),
                        float(r["high"]), float(r["low"]), float(r["close"])))
    out.sort()
    return out


class SimBroker:
    def __init__(self, bars: Dict[str, List[Bar]], state: Optional[dict] = None,
                 balance: float = 15000.0, half_spread: float = 0.00005) -> None:
        self.data = bars
        self.ends = {s: [b[0] + BAR for b in bs] for s, bs in bars.items()}
        st = state or {}
        self.balance = st.get("balance", balance)
        self.pos = [Position(**p) for p in st.get("positions", [])]
        self.next_ticket = st.get("next_ticket", 1)
        self.deals: List[dict] = st.get("deals", [])
        t = st.get("clock")
        self.clock = datetime.fromisoformat(t) if t else None
        self.half_spread = half_spread

    def state(self) -> dict:
        return {"balance": self.balance,
                "positions": [p.__dict__ for p in self.pos],
                "next_ticket": self.next_ticket, "deals": self.deals,
                "clock": self.clock.isoformat() if self.clock else None}

    # ----------------------------------------------------------- time
    def _visible(self, symbol: str, at: datetime) -> List[Bar]:
        return self.data[symbol][:bisect_right(self.ends[symbol], at)]

    def advance_to(self, t: datetime) -> None:
        """Move the clock to ``t``, filling resting stops on every bar that
        ended in between."""
        if self.clock is not None and t < self.clock:
            raise ValueError("time only moves forward")
        start = self.clock
        for p in list(self.pos):
            if not p.sl:
                continue
            for b in self._visible(p.symbol, t):
                if start is not None and b[0] + BAR <= start:
                    continue
                if b[3] <= p.sl:
                    self._settle(p, min(b[1], p.sl), "stop",
                                 (b[0] + BAR).astimezone(t.tzinfo))
                    break
        self.clock = t

    # --------------------------------------------------- Broker protocol
    def now(self) -> datetime:
        return self.clock

    def _last(self, symbol: str) -> float:
        v = self._visible(symbol, self.clock)
        if not v:
            raise RuntimeError(f"no bars for {symbol} at {self.clock}")
        return v[-1][4]

    def account(self) -> Account:
        eq = self.balance + sum((self._last(p.symbol) - p.price_open) * p.volume
                                for p in self.pos)
        return Account(0, "SIM-FTMO", "CAD", self.balance, eq, True)

    def bars(self, symbol: str, minutes: int, count: int) -> List[Bar]:
        if minutes != 30:
            raise ValueError("the simulated broker only has 30-minute bars")
        return self._visible(symbol, self.clock)[-count:]

    def low_equity(self, since: Optional[datetime]) -> float:
        """Equity with every open position marked at its lowest low over
        the bars that ended after ``since`` (worst case inside the bars)."""
        eq = self.balance
        for p in self.pos:
            lows = [b[3] for b in self._visible(p.symbol, self.clock)
                    if since is None or b[0] + BAR > since]
            px = min(lows) if lows else self._last(p.symbol)
            eq += (min(px, self._last(p.symbol)) - p.price_open) * p.volume
        return eq

    def quote(self, symbol: str) -> Tuple[float, float]:
        c = self._last(symbol)
        return c * (1 - self.half_spread), c * (1 + self.half_spread)

    def spec(self, symbol: str) -> Spec:
        return Spec(symbol in self.data, 0.01, 0.01, 1000.0)

    def loss_per_lot(self, symbol: str, entry: float, stop: float) -> float:
        return entry - stop                      # 1 lot = 1 unit of the proxy

    def positions(self, magic: int) -> List[Position]:
        return list(self.pos)

    def buy(self, symbol: str, volume: float, sl: Optional[float],
            magic: int, comment: str) -> Fill:
        _, ask = self.quote(symbol)
        t = self.next_ticket
        self.next_ticket += 1
        self.pos.append(Position(t, symbol, volume, ask, sl or 0.0))
        self.deals.append({"time": self.clock.isoformat(), "ticket": t,
                           "side": "buy", "symbol": symbol, "volume": volume,
                           "price": round(ask, 4), "sl": sl, "why": comment})
        return Fill(True, ask, t, "done")

    def close(self, position: Position, magic: int, comment: str) -> Fill:
        bid, _ = self.quote(position.symbol)
        self._settle(position, bid, comment, self.clock)
        return Fill(True, bid, position.ticket, "done")

    def _settle(self, p: Position, price: float, why: str, when: datetime) -> None:
        pnl = (price - p.price_open) * p.volume
        self.balance += pnl
        self.pos = [x for x in self.pos if x.ticket != p.ticket]
        self.deals.append({"time": when.isoformat(), "ticket": p.ticket,
                           "side": "sell", "symbol": p.symbol, "volume": p.volume,
                           "price": round(price, 4), "pnl": round(pnl, 2),
                           "why": why})


def save_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2))
    tmp.replace(path)
