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
        self.fail_close = False
        self.fail_positions = False
        self.fail_buy = False

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
        if self.fail_positions:
            raise RuntimeError("positions_get failed")
        return list(self.pos)

    def buy(self, symbol, volume, sl, magic, comment):
        if self.fail_buy:
            raise ConnectionError("terminal went away")
        t = self.next_ticket
        self.next_ticket += 1
        _, ask = self.quote(symbol)
        self.pos.append(Position(t, symbol, volume, ask, sl or 0.0))
        self.sent.append(("buy", symbol, volume, sl))
        return Fill(True, ask, t, "done")

    def close(self, position, magic, comment):
        if self.fail_close == "raise":
            raise RuntimeError("no quote")
        if self.fail_close:
            self.sent.append(("close-failed", position.symbol))
            return Fill(False, message="10004 requote")
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


def next_day(d: date) -> date:
    return d + timedelta(days=3 if d.weekday() == 4 else 1)


def open_session(bars, d: date, n: int = 3):
    """Append the first bars of session ``d`` (pre-market + 09:30 + ...)
    for every symbol, priced near each symbol's last close."""
    for sym in bars:
        last = bars[sym][-2][4]
        bars[sym] += session_bars(d, last * 0.99, last, last * 0.98,
                                  last * 1.01)[:n]


def planned(tmp_path, **kw):
    """A runner that planned after the last close (US100 entry pending)."""
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 16, 10)
    r = Runner(cfg(tmp_path, **kw), b)
    r.tick()
    assert r.st.pending_entries == ["US100"]
    return r, b, bars, ds


def cfg(tmp_path, **kw):
    c = FtmoConfig(state_path=str(tmp_path / "st.json"),
                   log_path=str(tmp_path / "log"), **kw)
    c.validate()
    return c


def test_runner_plans_after_close_and_buys_at_next_open(tmp_path):
    r, b, bars, ds = planned(tmp_path, dry_run=False)
    assert r.st.plan_day == ds[-1].isoformat()
    atr = r.st.pending_atr["US100"]
    nxt = next_day(ds[-1])
    open_session(bars, nxt)
    b.clock = ny(nxt, 9, 35)
    r.tick()
    buys = [x for x in b.sent if x[0] == "buy"]
    assert len(buys) == 1 and buys[0][1] == "US100.cash"
    vol, sl = buys[0][2], buys[0][3]
    _, ask = b.quote("US100.cash")
    assert sl == pytest.approx(ask - 3 * atr)
    assert vol * (ask - sl) <= 0.03 * 15000 + 1e-6          # risk <= 3%
    assert "US100" in r.st.held and r.st.trading_days
    assert r.st.pending_entries == [] and r.st.executed_day == nxt.isoformat()


def test_plan_executes_once_even_after_a_crash(tmp_path):
    r, b, bars, ds = planned(tmp_path, dry_run=False)
    nxt = next_day(ds[-1])
    open_session(bars, nxt)
    b.clock = ny(nxt, 9, 35)
    b.fail_buy = True
    r.tick()                                       # buy raises mid-execution
    b.fail_buy = False
    r2 = Runner(r.cfg, b)                          # restart from saved state
    for m in (36, 40, 50):
        b.clock = ny(nxt, 9, m)
        r2.tick()
        r.tick()
    assert [x for x in b.sent if x[0] == "buy"] == []    # never sent twice


def test_ticking_twice_buys_once(tmp_path):
    r, b, bars, ds = planned(tmp_path, dry_run=False)
    nxt = next_day(ds[-1])
    open_session(bars, nxt)
    for m in (35, 36, 37):
        b.clock = ny(nxt, 9, m)
        r.tick()
    assert len([x for x in b.sent if x[0] == "buy"]) == 1


def test_stale_plan_is_discarded(tmp_path):
    r, b, bars, ds = planned(tmp_path, dry_run=False)
    d1 = next_day(ds[-1])
    open_session(bars, d1, n=15)                   # a whole session the bot missed
    d2 = next_day(d1)
    open_session(bars, d2)
    b.clock = ny(d2, 9, 35)
    r.tick()
    assert b.sent == [] and r.st.pending_entries == []


@pytest.mark.parametrize("hh,mm,bought", [(9, 30, 0), (9, 31, 1), (10, 30, 1),
                                          (10, 31, 0)])
def test_entry_window(tmp_path, hh, mm, bought):
    r, b, bars, ds = planned(tmp_path, dry_run=False)
    nxt = next_day(ds[-1])
    open_session(bars, nxt)
    b.clock = ny(nxt, hh, mm)
    r.tick()
    assert len([x for x in b.sent if x[0] == "buy"]) == bought
    if (hh, mm) == (9, 30):
        assert r.st.pending_entries == ["US100"]   # not yet; still pending


def test_exits_run_while_entries_are_blocked(tmp_path):
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 9, 40)
    b.pos = [Position(7, "US30.cash", 1.0, 100, 90)]
    r = Runner(cfg(tmp_path, dry_run=False), b)
    r.st.held["US30"] = {"ticket": 7, "entry_day": ds[-3].isoformat()}
    r.st.blocked_until = "2999-01-01"
    r.st.pending_exits, r.st.pending_entries = ["US30"], ["US100"]
    r.st.pending_atr = {"US100": 1.0}
    r.execute(b.clock, b.positions(0))
    assert b.sent == [("close", "US30.cash", 1.0, "FAST4 exit")]
    assert r.st.held == {}


def test_dry_run_sends_nothing(tmp_path):
    r, b, bars, ds = planned(tmp_path)                 # dry_run default True
    nxt = next_day(ds[-1])
    open_session(bars, nxt)
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


def test_failed_close_is_kept_and_retried(tmp_path):
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 12, 0)
    b.pos = [Position(5, "US100.cash", 1.0, 100, 90)]
    r = Runner(cfg(tmp_path, dry_run=False), b)
    r.tick()
    assert r.st.held["US100"]["ticket"] == 5          # adopted
    b.equity, b.fail_close = 14260, True
    r.tick()                                           # guard close fails
    assert r.st.to_close == [5] and "US100" in r.st.held and b.pos
    b.fail_close = False
    b.clock = ny(ds[-1], 12, 1)
    r.tick()                                           # retried
    assert b.pos == [] and r.st.to_close == [] and r.st.held == {}


def test_close_exception_is_queued_like_a_failure(tmp_path):
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 12, 0)
    b.pos = [Position(5, "US100.cash", 1.0, 100, 90),
             Position(6, "US30.cash", 1.0, 100, 90)]
    r = Runner(cfg(tmp_path, dry_run=False), b)
    r.tick()
    b.equity, b.fail_close = 14260, "raise"
    r.tick()                                           # no exception escapes
    assert sorted(r.st.to_close) == [5, 6] and len(r.st.held) == 2


def test_holiday_keeps_the_plan_until_the_next_session(tmp_path):
    r, b, bars, ds = planned(tmp_path, dry_run=False)
    holiday = next_day(ds[-1])                         # no bars that day
    b.clock = ny(holiday, 9, 45)
    r.tick()
    b.clock = ny(holiday, 16, 10)
    r.tick()
    assert r.st.pending_entries == ["US100"] and b.sent == []
    nxt = next_day(holiday)
    open_session(bars, nxt)
    b.clock = ny(nxt, 9, 35)
    r.tick()
    assert [x[1] for x in b.sent if x[0] == "buy"] == ["US100.cash"]


def test_bars_error_at_the_close_retries_planning(tmp_path):
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 16, 6)
    r = Runner(cfg(tmp_path), b)
    good = b.bars
    b.bars = lambda *a: (_ for _ in ()).throw(RuntimeError("no bars"))
    with pytest.raises(RuntimeError):
        r.tick()
    b.bars = good
    b.clock = ny(ds[-1], 16, 7)
    r.tick()
    assert r.st.pending_entries == ["US100"]


def test_positions_error_aborts_tick_and_keeps_state(tmp_path):
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 12, 0)
    r = Runner(cfg(tmp_path, dry_run=False), b)
    r.st.held["US100"] = {"ticket": 99, "entry_day": ds[-2].isoformat()}
    b.fail_positions = True
    with pytest.raises(RuntimeError):
        r.tick()
    assert "US100" in r.st.held                        # not read as "stopped out"


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
    r.roll_day(b.clock)
    r.st.last_fill = (b.clock - timedelta(days=26)).isoformat()
    r.keepalive(b.clock, [])
    assert [x[0] for x in b.sent] == ["buy", "close"] and b.pos == []
    b.sent.clear()
    r2 = Runner(cfg(tmp_path / "f", dry_run=False, profit_target=None), b)
    r2.roll_day(b.clock)
    r2.st.last_fill = (b.clock - timedelta(days=60)).isoformat()
    r2.keepalive(b.clock, [])
    assert b.sent == []


def test_keepalive_refused_while_blocked(tmp_path):
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 11, 0)
    r = Runner(cfg(tmp_path, dry_run=False), b)
    r.roll_day(b.clock)
    r.st.blocked_until = "2999-01-01"
    r.st.last_fill = (b.clock - timedelta(days=26)).isoformat()
    r.keepalive(b.clock, [])
    assert b.sent == []


def test_compute_plan_is_read_only(tmp_path):
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 20, 0)
    r = Runner(cfg(tmp_path), b)
    day, p = r.compute_plan(b.clock)
    assert day == ds[-1] and p.entries == ["US100"]
    assert r.st.pending_entries == [] and not (tmp_path / "st.json").exists()


def test_mt5_adapter_is_the_only_metatrader_import():
    import pathlib
    hits = [p.name for p in pathlib.Path("ftmo_bot").glob("*.py")
            if "import MetaTrader5" in p.read_text()]
    assert hits == ["broker_mt5.py"]


# ------------------------------------------------------- MT5 adapter

class FakeMT5:
    RES_S_OK = 1

    def __init__(self):
        self.ps, self.err = (), (1, "Success")

    def initialize(self, *a):
        return True

    def last_error(self):
        return self.err

    def positions_get(self):
        return self.ps

    def symbol_info(self, symbol):
        from types import SimpleNamespace
        return SimpleNamespace(trade_tick_size=0.25, digits=2)


def test_mt5_adapter_positions_rounding_and_clock(monkeypatch):
    import sys
    from types import SimpleNamespace
    fake = FakeMT5()
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    from ftmo_bot.broker_mt5 import MT5Broker
    b = MT5Broker()
    P = lambda t, m: SimpleNamespace(ticket=t, symbol="US100.cash", volume=1.0,
                                     price_open=1.0, sl=0.0, magic=m)
    fake.ps = (P(1, 404040), P(2, 7))
    assert [p.ticket for p in b.positions(404040)] == [1]     # other magic ignored
    fake.ps = None                                            # no positions, no error
    assert b.positions(404040) == []
    fake.err = (-10004, "No IPC connection")                  # an error is not "none"
    with pytest.raises(RuntimeError):
        b.positions(404040)
    assert b._round("US100.cash", 19876.137) == 19876.25
    # server 2026-10-05 16:30 (= NY 09:30, EDT) -> 13:30 UTC
    epoch = int(datetime(2026, 10, 5, 16, 30, tzinfo=ZoneInfo("UTC")).timestamp())
    got = b._to_utc(epoch)
    assert got.astimezone(NY) == datetime(2026, 10, 5, 9, 30, tzinfo=NY)
