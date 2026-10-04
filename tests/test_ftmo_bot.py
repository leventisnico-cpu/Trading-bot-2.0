"""FTMO bot (FAST-4 on MT5): pure parts and the runner against a fake broker."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from ftmo_bot import fast4, rules, sessions
from ftmo_bot.broker import Account, Fill, Position, Spec
from ftmo_bot.config import FtmoConfig, load
from ftmo_bot.runner import Runner

NY = ZoneInfo("America/New_York")


# ------------------------------------------------------------- config

def test_config_refuses_credentials(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("risk_per_trade: 0.03\npassword: hunter2\n")
    with pytest.raises(ValueError, match="credentials"):
        load(p)


def test_example_config_loads_dry_run_at_3pct():
    cfg = load("deploy/ftmo/config.example.yaml")
    assert cfg.dry_run is True and cfg.risk_per_trade == 0.03
    assert cfg.max_positions == 2 and set(cfg.symbols) == {"US100", "US500", "US30", "US2000"}


def test_config_validation():
    with pytest.raises(ValueError):
        FtmoConfig(risk_per_trade=0.2).validate()
    with pytest.raises(ValueError):
        FtmoConfig(keepalive_symbol="DAX").validate()


# ----------------------------------------------------------- sessions

def ny(d: date, h: int, m: int) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, tzinfo=NY)


def session_bars(d: date, o: float, c: float, lo: float, hi: float):
    """13 half-hour bars 09:30-16:00 plus one pre-market and one after-hours
    bar that must be ignored."""
    out = [(ny(d, 8, 0), 999, 999, 1, 999)]
    steps = 13
    for k in range(steps):
        t = ny(d, 9, 30) + timedelta(minutes=30 * k)
        p0 = o + (c - o) * k / steps
        p1 = o + (c - o) * (k + 1) / steps
        out.append((t, p0, max(p0, p1), min(p0, p1), p1))
    out[3] = (out[3][0], out[3][1], hi, out[3][3], out[3][4])
    out[5] = (out[5][0], out[5][1], out[5][2], lo, out[5][4])
    out.append((ny(d, 16, 30), 1, 1, 1, 1))
    return out


def test_session_build_uses_cash_hours_only():
    d = date(2026, 9, 28)
    ss = sessions.build(session_bars(d, 100, 110, 95, 115), 30, ny(d, 17, 0))
    assert len(ss) == 1
    s = ss[0]
    assert (s.open, s.close, s.low, s.high, s.complete) == (100, 110, 95, 115, True)
    assert sessions.build(session_bars(d, 100, 110, 95, 115), 30,
                          ny(d, 15, 0))[0].complete is False


# ---------------------------------------------------------- indicators

def test_indicators_match_the_research_formulas():
    import random
    rnd = random.Random(7)
    closes = [100.0]
    for _ in range(259):
        closes.append(closes[-1] * (1 + rnd.uniform(-0.02, 0.021)))
    days = pd.bdate_range("2025-01-01", periods=260)
    ss = [sessions.Session(d.date(), c, c * 1.01, c * 0.99, c, True)
          for d, c in zip(days, closes)]
    got = fast4.indicators(ss)
    c = pd.Series(closes)
    d = c.diff()
    g = d.clip(lower=0).ewm(alpha=0.5, adjust=False).mean()
    lo = (-d.clip(upper=0)).ewm(alpha=0.5, adjust=False).mean()
    rsi = (100 - 100 / (1 + g / lo)).iloc[-1]
    h, l = c * 1.01, c * 0.99
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()],
                   axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]
    assert got.rsi2 == pytest.approx(rsi, rel=1e-9)
    assert got.atr14 == pytest.approx(atr, rel=1e-9)
    assert got.sma200 == pytest.approx(c.iloc[-200:].mean())
    assert got.sma5 == pytest.approx(c.iloc[-5:].mean())


def ind(close, sma200, sma5, rsi, atr=10.0):
    return fast4.Indicators(close, sma200, sma5, rsi, atr)


def test_plan_entries_exits_slots_and_priority():
    i = {"US100": ind(100, 90, 101, 5), "US500": ind(100, 90, 101, 8),
         "US30": ind(100, 90, 101, 3), "US2000": ind(100, 110, 101, 2)}
    p = fast4.plan(i, {})
    assert p.entries == ["US30", "US100"]          # lowest RSI first, 2 slots
    assert "US2000" not in p.entries               # below its SMA200
    p = fast4.plan(i, {"US30": 1})                 # held, not exiting
    assert p.entries == ["US100"] and p.exits == []
    i["US30"] = ind(105, 90, 101, 50)              # close > SMA5 -> exit
    p = fast4.plan(i, {"US30": 1})
    assert p.exits == ["US30"] and p.entries == ["US100", "US500"]
    i["US30"] = ind(95, 90, 101, 50)
    assert fast4.plan(i, {"US30": 10}).exits == ["US30"]   # 10 sessions


# --------------------------------------------------------------- rules

def test_lots_risk_cap_step_and_min():
    # 3% of 15,000 = 450; 1 lot loses 1,000 from entry to stop -> 0.45 lots
    assert rules.lots(15000, 0.03, 20000, 19000, 1000, 5, 0.01, 0.01, 50) == 0.45
    # notional cap: 1 lot = 20,000 notional; 5 x 15,000 = 75,000 -> 3.75 lots
    assert rules.lots(15000, 0.03, 20000, 19990, 10, 5, 0.01, 0.01, 50) == 3.75
    assert rules.lots(15000, 0.03, 20000, 19000, 1000, 5, 0.5, 0.5, 50) == 0.0
    assert rules.lots(15000, 0.03, 20000, 20000, 1000, 5, 0.01, 0.01, 50) == 0.0


def test_guard_and_entry_check():
    lim = rules.Limits(15000)
    assert lim.guard(14500, 15000) is None
    assert "daily-loss" in lim.guard(14270, 15000)       # floor 14,250 + 30
    assert "max-loss" in lim.guard(13520, 14000)         # floor 13,500 + 30
    assert rules.check_entry(15000, 15000, lim, 2, 2, False)
    assert rules.check_entry(15000, 15000, lim, 0, 2, True)
    assert rules.check_entry(15000, 15000, lim, 1, 2, False) is None
    assert rules.target_reached(16500, 15000, 0.10, 4, 4)
    assert not rules.target_reached(16500, 15000, 0.10, 3, 4)
    assert not rules.target_reached(16500, 15000, None, 9, 4)


# -------------------------------------------------------- fake broker

class FakeBroker:
    def __init__(self, bars, balance=15000.0):
        self.b = bars
        self.balance = balance
        self.equity = balance
        self.pos = []
        self.sent = []
        self.clock = None
        self.next_ticket = 1

    def account(self):
        return Account(1, "FTMO-Demo", "CAD", self.balance, self.equity, True)

    def now(self):
        return self.clock

    def bars(self, symbol, minutes, count):
        return [x for x in self.b[symbol] if x[0] <= self.clock][-count:]

    def quote(self, symbol):
        last = self.bars(symbol, 30, 1)[-1][4]
        return last - 0.5, last + 0.5

    def spec(self, symbol):
        return Spec(True, 0.01, 0.01, 50)

    def loss_per_lot(self, symbol, entry, stop):
        return entry - stop            # 1 lot = 1 unit, account ccy = quote ccy

    def positions(self, magic):
        return list(self.pos)

    def buy(self, symbol, volume, sl, magic, comment):
        t = self.next_ticket
        self.next_ticket += 1
        _, ask = self.quote(symbol)
        self.pos.append(Position(t, symbol, volume, ask, sl or 0.0))
        self.sent.append(("buy", symbol, volume, sl))
        return Fill(True, ask, t, "done")

    def close(self, position, magic, comment):
        self.pos = [p for p in self.pos if p.ticket != position.ticket]
        self.sent.append(("close", position.symbol, position.volume, comment))
        return Fill(True, 0, position.ticket, "done")


def history(dip_symbol="US100.cash", days=260):
    """Rising markets; on the last day ``dip_symbol`` falls three sessions
    in a row so RSI(2) < 10 while staying above its 200-day average."""
    out = {}
    start = date(2025, 9, 1)
    ds = [d.date() for d in pd.bdate_range(start, periods=days)]
    for sym in ("US100.cash", "US500.cash", "US30.cash", "US2000.cash"):
        bars, price = [], 100.0
        for k, d in enumerate(ds):
            o = price
            if sym == dip_symbol and k >= days - 3:
                c = o * 0.985
            else:
                c = o * (1.004 if k % 3 else 0.998)
            bars += session_bars(d, o, c, min(o, c) * 0.997, max(o, c) * 1.003)
            price = c
        out[sym] = bars
    return out, ds


def cfg(tmp_path, **kw):
    c = FtmoConfig(state_path=str(tmp_path / "st.json"),
                   log_path=str(tmp_path / "log"), **kw)
    c.validate()
    return c


def test_runner_plans_after_close_and_buys_at_next_open(tmp_path):
    bars, ds = history()
    b = FakeBroker(bars)
    last = ds[-1]
    b.clock = ny(last, 16, 10)
    r = Runner(cfg(tmp_path, dry_run=False), b)
    r.tick()
    assert r.st.pending_entries == ["US100"] and r.st.plan_day == last.isoformat()
    # next morning: a 09:30 bar appears, the bot buys at 09:35
    nxt = last + timedelta(days=3 if last.weekday() == 4 else 1)
    bars["US100.cash"] += session_bars(nxt, 90, 91, 89, 92)[:3]
    b.clock = ny(nxt, 9, 35)
    r.tick()
    buys = [x for x in b.sent if x[0] == "buy"]
    assert len(buys) == 1 and buys[0][1] == "US100.cash"
    vol, sl = buys[0][2], buys[0][3]
    _, ask = b.quote("US100.cash")
    assert sl == pytest.approx(ask - 3 * r.st.pending_atr["US100"])
    assert vol * (ask - sl) <= 0.03 * 15000 + 1e-6          # risk ≤ 3%
    assert "US100" in r.st.held and r.st.trading_days


def test_dry_run_sends_nothing(tmp_path):
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 16, 10)
    r = Runner(cfg(tmp_path), b)                       # dry_run default True
    r.tick()
    nxt = ds[-1] + timedelta(days=3 if ds[-1].weekday() == 4 else 1)
    bars["US100.cash"] += session_bars(nxt, 90, 91, 89, 92)[:3]
    b.clock = ny(nxt, 9, 35)
    r.tick()
    assert b.sent == []


def test_stopped_position_is_reconciled(tmp_path):
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 12, 0)
    r = Runner(cfg(tmp_path, dry_run=False), b)
    r.st.held["US100"] = {"ticket": 99, "entry_day": ds[-2].isoformat()}
    r.tick()                                           # no broker position
    assert "US100" not in r.st.held


def test_guard_flattens_and_blocks_entries(tmp_path):
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 12, 0)
    b.pos = [Position(5, "US100.cash", 1.0, 100, 90)]
    r = Runner(cfg(tmp_path, dry_run=False), b)
    r.tick()                                           # day-start 15,000
    b.equity = 14260                                   # within 0.2% of 14,250
    r.tick()
    assert b.pos == [] and ("close", "US100.cash", 1.0, "FAST4 guard") in b.sent
    assert r.st.blocked_until is not None and r.st.halted is None


def test_target_flattens_and_halts(tmp_path):
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 12, 0)
    b.pos = [Position(5, "US500.cash", 1.0, 100, 90)]
    r = Runner(cfg(tmp_path, dry_run=False), b)
    r.st.trading_days = ["a", "b", "c", "d"]
    b.equity = 16600
    r.tick()
    assert b.pos == [] and r.st.halted


def test_keepalive_after_25_days_in_evaluation_only(tmp_path):
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 11, 0)
    r = Runner(cfg(tmp_path, dry_run=False), b)
    r.st.last_fill = (b.clock - timedelta(days=26)).isoformat()
    r.keepalive(b.clock)
    assert [x[0] for x in b.sent] == ["buy", "close"] and b.pos == []
    b.sent.clear()
    r2 = Runner(cfg(tmp_path / "f", dry_run=False, profit_target=None), b)
    r2.st.last_fill = (b.clock - timedelta(days=60)).isoformat()
    r2.keepalive(b.clock)
    assert b.sent == []


def test_mt5_adapter_is_the_only_metatrader_import():
    import pathlib
    hits = [p.name for p in pathlib.Path("ftmo_bot").glob("*.py")
            if "import MetaTrader5" in p.read_text()]
    assert hits == ["broker_mt5.py"]
