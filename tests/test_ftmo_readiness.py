"""FTMO bot readiness: the server clock, one state per account, trading
days on FTMO's calendar, the target lock with its finish line, and
keep-alive on every phase."""

from __future__ import annotations

import ast
import dataclasses
import json
import logging
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_ftmo_bot import FakeBroker, cfg, history, next_day, ny, open_session, planned  # noqa: E402

from ftmo_bot import server_clock  # noqa: E402
from ftmo_bot.broker import Position  # noqa: E402
from ftmo_bot.config import FtmoConfig, load  # noqa: E402
from ftmo_bot.runner import Runner, State  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
NY = ZoneInfo("America/New_York")
PRAGUE = ZoneInfo("Europe/Prague")
UTC = timezone.utc


def prague(t: datetime) -> str:
    return t.astimezone(PRAGUE).date().isoformat()


# ------------------------------------------------------- server clock

def test_server_clock_rules_and_the_dst_mismatch_week():
    nov = datetime(2026, 11, 15, 12, tzinfo=UTC)        # both on standard time
    assert server_clock.offset_at("NY+7", nov) == timedelta(hours=2)
    assert server_clock.offset_at("EET", nov) == timedelta(hours=2)
    assert server_clock.matching(timedelta(hours=2), nov) == ["NY+7", "EET"]
    gap = datetime(2026, 10, 28, 12, tzinfo=UTC)        # US summer time, EU not
    assert server_clock.offset_at("NY+7", gap) == timedelta(hours=3)
    assert server_clock.offset_at("EET", gap) == timedelta(hours=2)
    assert server_clock.matching(timedelta(hours=3), gap) == ["NY+7"]
    assert server_clock.matching(timedelta(hours=2), gap) == ["EET"]
    assert server_clock.matching(timedelta(hours=5), gap) == []
    s = datetime(2026, 10, 5, 16, 30)                   # a naive server stamp
    assert server_clock.to_utc("NY+7", s).astimezone(NY) == datetime(2026, 10, 5, 9, 30, tzinfo=NY)
    assert server_clock.to_utc("EET", s) == datetime(2026, 10, 5, 13, 30, tzinfo=UTC)
    assert server_clock.to_utc("UTC", s) == datetime(2026, 10, 5, 16, 30, tzinfo=UTC)
    assert server_clock.describe(timedelta(hours=-5)) == "UTC-5"
    assert server_clock.describe(timedelta(hours=5, minutes=30)) == "UTC+5:30"


def test_server_clock_measure_rounds_a_fresh_tick_and_drops_a_stale_one():
    now = datetime(2026, 11, 2, 15, 0, 30, tzinfo=UTC)
    fresh = (now + timedelta(hours=2)).timestamp() - 40
    assert server_clock.measure(fresh, now) == timedelta(hours=2)
    stale = (now + timedelta(hours=2)).timestamp() - 600
    assert server_clock.measure(stale, now) is None


class ClockMT5:
    """MetaTrader5 stand-in whose ticks are stamped at UTC + ``offset``.
    ``moving``: every look sees a new tick; otherwise the last stamp stays
    (market closed). ``lag``: how old the newest tick is."""

    def __init__(self, offset: timedelta, now: datetime) -> None:
        self.offset, self.now = offset, now
        self.moving, self.lag, self.k, self.last = True, timedelta(0), 0, None

    def initialize(self, *a):
        return True

    def last_error(self):
        return (1, "Success")

    def symbol_select(self, symbol, flag):
        return True

    def symbol_info_tick(self, symbol):
        if self.moving or self.last is None:
            self.k += 1
            self.last = (self.now - self.lag + self.offset).timestamp() + self.k / 1000
        return SimpleNamespace(time=int(self.last), time_msc=int(self.last * 1000),
                               bid=1.0, ask=1.0)


@pytest.fixture
def clock_mt5(monkeypatch):
    from ftmo_bot import broker_mt5
    fake = ClockMT5(timedelta(hours=2), datetime(2026, 11, 15, 12, tzinfo=UTC))
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    monkeypatch.setattr(broker_mt5.MT5Broker, "now", lambda self: fake.now)
    monkeypatch.setattr(broker_mt5, "SLEEP", lambda s: None)
    return fake


def test_mt5_clock_fit_narrows_and_refuses_a_misfit(clock_mt5):
    from ftmo_bot.broker_mt5 import MT5Broker
    fake = clock_mt5
    b = MT5Broker(probe="US500.cash")
    assert b.rule == "NY+7" and b.candidates == ["NY+7", "EET"]
    assert "UTC+2" in b.clock_status() and "also fits EET" in b.clock_status()
    # 2027-03-20: US summer time since 03-14, the EU's starts 03-28. The
    # server stays on UTC+2, so it was EET all along: the fit narrows.
    fake.now = datetime(2027, 3, 20, 12, tzinfo=UTC)
    b.check("US500.cash", strict=True)          # first look after a gap: no reading
    assert b.rule == "NY+7"
    b.check("US500.cash", strict=True)
    assert b.rule == "EET" and b.candidates == ["EET"]
    epoch = int(datetime(2027, 3, 20, 16, 30, tzinfo=UTC).timestamp())   # server 16:30 EET
    assert b._to_utc(epoch) == datetime(2027, 3, 20, 14, 30, tzinfo=UTC)
    # a fresh reading that fits no candidate: refused in strict mode, ignored otherwise
    fake.offset = timedelta(hours=5)
    with pytest.raises(RuntimeError, match="server clock"):
        b.check("US500.cash", strict=True)
    b.check("US500.cash", strict=False)
    assert b.rule == "EET"
    with pytest.raises(ValueError, match="server_clock"):
        MT5Broker(rule="Mars")


def test_mt5_clock_ignores_stale_ticks(clock_mt5):
    from ftmo_bot.broker_mt5 import MT5Broker
    fake = clock_mt5
    fake.moving = False                         # weekend start: no moving tick
    b = MT5Broker(probe="US500.cash")
    assert b.verified_at is None and "unverified" in b.clock_status()
    with pytest.raises(RuntimeError, match="unverified"):
        b.check("US500.cash", strict=True)
    # the market opens: two looks a minute apart see a moving tick
    fake.moving, fake.now = True, fake.now + timedelta(days=1)
    with pytest.raises(RuntimeError, match="unverified"):
        b.check("US500.cash", strict=True)      # first look after the gap
    fake.now += timedelta(minutes=1)
    b.check("US500.cash", strict=True)
    assert b.verified_at == fake.now and b.candidates == ["NY+7", "EET"]
    # an early close: the last tick is exactly one hour old. It must not
    # read as UTC+1 (CET), and once verified the bot keeps serving bars.
    fake.moving = False
    fake.now += timedelta(hours=1)
    b.check("US500.cash", strict=True)
    b.check("US500.cash", strict=True)
    assert b.rule == "NY+7" and b.candidates == ["NY+7", "EET"]
    # a moving tick that is three minutes old does not date the clock either
    fake.moving, fake.lag = True, timedelta(minutes=3)
    b.check("US500.cash", strict=True)
    fake.now += timedelta(minutes=1)
    b.check("US500.cash", strict=True)
    assert b.candidates == ["NY+7", "EET"]


def test_mt5_clock_misfit_keeps_refusing_after_the_refresh_took_the_look(clock_mt5):
    from ftmo_bot.broker_mt5 import MT5Broker
    fake = clock_mt5
    b = MT5Broker(probe="US500.cash", rule="NY+7")      # verified at UTC+2 (November)
    fake.offset = timedelta(hours=5)                     # the server clock jumps
    fake.now += timedelta(seconds=60)
    b.refresh_clock()                                    # the tick's first look sees it
    assert b.misfit is not None
    fake.moving = False                                  # same tick: no newer tick yet
    with pytest.raises(RuntimeError, match="fits"):
        b.check("US500.cash", strict=True)               # the bar read still refuses
    fake.now += timedelta(hours=3)                       # an early close: market shut
    with pytest.raises(RuntimeError, match="fits"):
        b.check("US500.cash", strict=True)               # still refused hours later
    fake.moving, fake.offset = True, timedelta(hours=2)  # the market reopens and the
    fake.now += timedelta(seconds=60)                    # reading fits again: the next
    b.refresh_clock()                                    # tick's look clears the misfit
    assert b.misfit is None
    b.check("US500.cash", strict=True)                   # and bars are served again


def test_mt5_clock_pinned_rule(clock_mt5):
    from ftmo_bot.broker_mt5 import MT5Broker
    fake = clock_mt5
    pinned = MT5Broker(probe="US500.cash", rule="EET")
    assert pinned.pinned and pinned.rule == "EET" and pinned.verified_at is not None
    fake.offset = timedelta(hours=3)            # a reading EET cannot have in November
    fake.now += timedelta(seconds=30)
    with pytest.raises(RuntimeError, match="fits"):
        pinned.check("US500.cash", strict=True)
    assert pinned.rule == "EET"


# --------------------------------------------------------- the runner

class Switchable(FakeBroker):
    login = 1

    def account(self):
        return dataclasses.replace(super().account(), login=self.login)


def test_state_belongs_to_one_account(tmp_path):
    bars, ds = history()
    b = Switchable(bars)
    b.clock = ny(ds[-1], 12, 0)
    c = cfg(tmp_path, dry_run=False)
    r = Runner(c, b)
    r.st.trading_days = ["2026-10-01"]
    r.st.last_fill = "2026-10-01T10:00:00-04:00"
    r.save()
    assert Runner(c, b).st.trading_days == ["2026-10-01"]      # same login: kept
    b.login = 2                                                 # the next phase
    r2 = Runner(c, b)
    assert r2.st.trading_days == [] and r2.st.login == 2
    r2.save()
    assert (tmp_path / "st.1.json").exists()
    b.login = 1                                                 # back to account 1
    r3 = Runner(c, b)
    assert r3.st.login == 1 and r3.st.trading_days == ["2026-10-01"]
    assert r3.st.last_fill == "2026-10-01T10:00:00-04:00"      # inactivity clock kept
    assert (tmp_path / "st.2.json").exists() and not (tmp_path / "st.1.json").exists()


def test_readonly_runner_never_moves_state(tmp_path):
    bars, ds = history()
    b = Switchable(bars)
    b.clock = ny(ds[-1], 12, 0)
    c = cfg(tmp_path, dry_run=False)
    r = Runner(c, b)
    r.st.trading_days = ["2026-10-01"]
    r.save()
    before = (tmp_path / "st.json").read_text()
    b.login = 2                                                 # `plan` on another account
    ro = Runner(c, b, readonly=True)
    assert ro.st.login == 2 and ro.st.trading_days == []
    assert (tmp_path / "st.json").read_text() == before
    assert not (tmp_path / "st.1.json").exists()


def test_trading_days_count_opened_positions_on_ftmo_dates(tmp_path):
    r, b, bars, ds = planned(tmp_path, dry_run=False)
    nxt = next_day(ds[-1])
    open_session(bars, nxt)
    b.clock = ny(nxt, 9, 35)
    r.tick()                                                    # buys US100
    assert len(b.pos) == 1 and r.st.trading_days == [prague(b.clock)]
    assert r.st.last_fill == b.clock.isoformat()
    b.pos = []                                                  # stopped out overnight
    b.clock = ny(next_day(nxt), 9, 35)
    r.tick()
    assert r.st.held == {} and r.st.trading_days == [prague(ny(nxt, 9, 35))]
    assert r.st.last_fill == ny(nxt, 9, 35).isoformat()         # a close is not activity


def locked_runner(tmp_path, **kw):
    bars, ds = history()
    b = FakeBroker(bars)
    d0 = ds[-1]
    b.clock = ny(d0, 10, 15)                # inside the round-trip window
    b.pos = [Position(5, "US500.cash", 1.0, 100, 90)]
    r = Runner(cfg(tmp_path, dry_run=False, **kw), b)
    r.st.held = {"US500": {"ticket": 5, "entry_day": d0.isoformat()}}
    r.st.trading_days = ["2026-10-01", "2026-10-02"]
    r.st.last_fill = (b.clock - timedelta(days=1)).isoformat()   # no keep-alive due
    return r, b, d0


def test_target_lock_finish_line_and_halt(tmp_path):
    r, b, d0 = locked_runner(tmp_path)
    b.equity = 16520                        # +10.1%: under target + margin (16,545)
    r.tick()
    assert r.st.target_locked is None and b.pos and not r.st.halted
    b.balance = b.equity = 16560            # over it (the fake realises on close)
    r.tick()                                # flatten, lock, first round trip
    assert b.pos == [] and r.st.target_locked == prague(b.clock) and not r.st.halted
    assert [x[0] for x in b.sent] == ["close", "buy", "close"]
    assert len(r.st.trading_days) == 3 and r.st.last_roundtrip == prague(b.clock)
    b.sent.clear()
    r.tick()                                # same FTMO day: nothing more
    assert b.sent == [] and not r.st.halted
    b.clock = ny(next_day(d0), 10, 15)      # day 4 of 4
    r.tick()
    assert [x[0] for x in b.sent] == ["buy", "close"]
    assert len(r.st.trading_days) == 4 and not r.st.halted
    r.tick()
    assert r.st.halted and "target" in r.st.halted


def test_target_lock_halts_at_once_with_enough_days_and_releases_on_a_dip(tmp_path):
    r, b, d0 = locked_runner(tmp_path)
    r.st.trading_days = ["a", "b", "c", "d"]
    b.balance = b.equity = 16560
    r.tick()
    assert b.pos == [] and r.st.halted and [x[0] for x in b.sent] == ["close"]
    r2, b2, _ = locked_runner(tmp_path / "dip")
    b2.balance = b2.equity = 16560
    r2.tick()
    assert r2.st.target_locked
    b2.balance = b2.equity = 16480          # under the target: trading resumes
    r2.tick()
    assert r2.st.target_locked is None and not r2.st.halted


def test_target_lock_judges_only_a_flat_account(tmp_path):
    r, b, d0 = locked_runner(tmp_path)
    r.st.trading_days = ["a", "b", "c", "d"]
    b.fail_close = True                     # the flatten is rejected
    b.equity = 16560                        # the gain is still floating
    r.tick()
    assert r.st.target_locked and b.pos and not r.st.halted
    b.fail_close = False
    b.balance = b.equity = 16560            # the retried close realises it
    r.tick()
    assert b.pos == [] and r.st.halted


def test_no_target_on_the_funded_account(tmp_path):
    r, b, d0 = locked_runner(tmp_path, profit_target=None)
    b.equity = 30000
    r.tick()
    assert b.pos and r.st.target_locked is None and not r.st.halted


def test_keepalive_runs_on_the_funded_account_and_retries_next_day(tmp_path):
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 10, 15)
    r = Runner(cfg(tmp_path, dry_run=False, profit_target=None), b)
    r.roll_day(b.clock)
    r.st.last_fill = (b.clock - timedelta(days=26)).isoformat()
    b.fail_buy = True
    r.keepalive(b.clock, [])
    assert b.sent == [] and r.st.last_roundtrip == prague(b.clock)
    assert r.st.last_fill != b.clock.isoformat()               # not counted as activity
    b.fail_buy = False
    r.keepalive(b.clock + timedelta(minutes=1), [])            # same day: no retry
    assert b.sent == []
    nxt = ny(next_day(ds[-1]), 10, 15)
    r.keepalive(nxt, [])
    assert [x[0] for x in b.sent] == ["buy", "close"] and r.st.last_fill == nxt.isoformat()
    assert r.st.trading_days == [prague(nxt)]


def test_stand_down_closes_everything_and_drops_the_plan(tmp_path):
    r, b, bars, ds = planned(tmp_path, dry_run=False)
    b.pos = [Position(5, "US500.cash", 1.0, 100, 90)]
    r.st.held = {"US500": {"ticket": 5, "entry_day": ds[-1].isoformat()}}
    r.stand_down(b.clock, b.pos)
    assert b.pos == [] and r.st.held == {} and r.st.pending_entries == []
    assert Runner(cfg(tmp_path, dry_run=False), b).st.pending_entries == []   # saved


def test_keepalive_off_when_days_is_zero(tmp_path):
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 10, 15)
    r = Runner(cfg(tmp_path, dry_run=False, keepalive_days=0), b)
    r.roll_day(b.clock)
    r.st.last_fill = (b.clock - timedelta(days=90)).isoformat()
    r.keepalive(b.clock, [])
    assert b.sent == []


def test_new_account_gets_a_round_trip_in_its_first_session(tmp_path):
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 10, 15)
    r = Runner(cfg(tmp_path, dry_run=False), b)
    assert r.st.last_fill is None
    r.tick()
    assert [x[0] for x in b.sent] == ["buy", "close"]
    assert r.st.trading_days == [prague(b.clock)] and r.st.last_fill == b.clock.isoformat()


@pytest.mark.parametrize("hh,mm,ok", [(9, 59, False), (10, 0, True), (10, 45, True),
                                      (10, 46, False), (15, 0, False)])
def test_round_trips_open_only_early_in_the_session(tmp_path, hh, mm, ok):
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], hh, mm)
    r = Runner(cfg(tmp_path, dry_run=False), b)
    r.roll_day(b.clock)
    r.keepalive(b.clock, [])
    assert bool(b.sent) == ok


def test_round_trip_attempt_is_saved_before_the_buy(tmp_path):
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 10, 15)
    c = cfg(tmp_path, dry_run=False)
    r = Runner(c, b)
    r.roll_day(b.clock)
    r.st.last_fill = (b.clock - timedelta(days=26)).isoformat()
    b.fail_buy = True                       # the buy dies mid-flight
    r.keepalive(b.clock, [])
    restarted = Runner(c, b)                # what is on disk survives a crash
    assert restarted.st.last_roundtrip == prague(b.clock)
    b.fail_buy = False
    restarted.keepalive(b.clock + timedelta(minutes=5), [])
    assert b.sent == []                     # no second attempt the same day


def test_legacy_state_without_a_login(tmp_path):
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 12, 0)
    (tmp_path / "st.json").write_text(json.dumps(
        {"trading_days": ["2026-10-01"], "halted": "profit target reached"}))
    r = Runner(cfg(tmp_path, dry_run=False), b)
    assert r.st.halted is None and r.st.trading_days == [] and r.st.login == 1
    assert (tmp_path / "st.legacy.json").exists()
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "st.json").write_text(json.dumps(
        {"trading_days": ["2026-10-01"], "pending_entries": ["US100"]}))
    r2 = Runner(cfg(plain, dry_run=False), b)          # e.g. the shadow's state
    assert r2.st.pending_entries == ["US100"] and r2.st.login == 1
    assert r2.st.trading_days == []                    # counted by the older rule: dropped


def test_state_load_ignores_unknown_keys(tmp_path):
    p = tmp_path / "st.json"
    p.write_text(json.dumps({"login": 7, "a_newer_field": 1, "trading_days": ["x"]}))
    st = State.load(p)
    assert st.login == 7 and st.trading_days == ["x"]


def test_initial_balance_must_be_positive():
    with pytest.raises(ValueError, match="initial_balance"):
        FtmoConfig(initial_balance=0).validate()


def clock_refusing(tmp_path):
    """A plan with one exit (US500) and one entry (US100), the next open,
    and a broker whose bars are refused (the server clock is unverified)."""
    r, b, bars, ds = planned(tmp_path, dry_run=False)
    b.pos = [Position(5, "US500.cash", 1.0, 100, 90)]
    r.st.held = {"US500": {"ticket": 5, "entry_day": ds[-1].isoformat()}}
    r.st.pending_exits = ["US500"]
    nxt = next_day(ds[-1])
    open_session(bars, nxt)
    working = b.bars

    def refuse(*a, **k):
        raise RuntimeError("server clock unverified")
    b.bars = refuse
    return r, b, nxt, working


def test_clock_refusal_runs_the_exits_and_entries_wait_for_the_clock(tmp_path):
    r, b, nxt, working = clock_refusing(tmp_path)
    b.clock = ny(nxt, 9, 35)
    r.tick()
    assert ("close", "US500.cash", 1.0, "FAST4 exit") in b.sent
    assert not [x for x in b.sent if x[0] == "buy"]             # entries wait
    assert r.st.pending_exits == [] and r.st.pending_entries == ["US100"]
    assert r.st.executed_day != nxt.isoformat()
    b.bars = working                                            # the clock verifies
    b.clock = ny(nxt, 9, 36)
    r.tick()
    assert [x[1] for x in b.sent if x[0] == "buy" and x[3]] == ["US100.cash"]
    assert len([x for x in b.sent if x[0] == "close"]) == 1     # the exit went once


def test_clock_refusal_past_the_entry_deadline_drops_the_entries(tmp_path):
    r, b, nxt, _ = clock_refusing(tmp_path)
    b.clock = ny(nxt, 10, 31)
    r.tick()
    assert ("close", "US500.cash", 1.0, "FAST4 exit") in b.sent
    assert not [x for x in b.sent if x[0] == "buy" and x[3]]
    assert r.st.pending_entries == [] and r.st.executed_day == nxt.isoformat()


def test_tick_refuses_after_the_terminal_switches_account(tmp_path):
    bars, ds = history()
    b = Switchable(bars)
    b.clock = ny(ds[-1], 12, 0)
    b.pos = [Position(5, "US500.cash", 1.0, 100, 90)]
    r = Runner(cfg(tmp_path, dry_run=False), b)
    r.st.held = {"US500": {"ticket": 5, "entry_day": ds[-1].isoformat()}}
    r.save()
    b.login = 2                                         # re-logged mid-run
    b.equity = 10000                                    # would trip every guard
    with pytest.raises(RuntimeError, match="switched"):
        r.tick()
    assert b.sent == [] and b.pos
    assert State.load(tmp_path / "st.json").held == {"US500": {"ticket": 5,
                                                               "entry_day": ds[-1].isoformat()}}


def test_target_lock_closes_a_position_adopted_after_it(tmp_path):
    r, b, d0 = locked_runner(tmp_path)
    r.st.trading_days = ["a", "b", "c"]
    b.balance = b.equity = 16560
    r.tick()                                            # lock + finish-line trade
    assert r.st.target_locked and b.pos == []
    b.pos = [Position(9, "US100.cash", 1.0, 100, 95)]   # a late fill turns up
    b.sent.clear()
    r.tick()
    assert ("close", "US100.cash", 1.0, "FAST4 target") in b.sent and b.pos == []


def test_dry_run_round_trip_leaves_the_inactivity_clock_alone(tmp_path):
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 10, 15)
    r = Runner(cfg(tmp_path), b)                        # dry run (the default)
    r.tick()
    assert b.sent == [] and r.st.last_fill is None and r.st.trading_days == []


def test_funded_config_clears_a_stale_target_lock(tmp_path):
    r, b, d0 = locked_runner(tmp_path, profit_target=None)
    r.st.target_locked = "2026-10-01"
    r.tick()
    assert r.st.target_locked is None


def test_windows_lock_branch(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from ftmo_bot import lock
    held = set()

    def locking(fd, mode, nbytes):
        assert mode == 2 and nbytes == 1
        key = __import__("os").fstat(fd).st_ino
        if key in held:
            raise OSError(36, "Resource deadlock avoided")
        held.add(key)
    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(LK_NBLCK=2, locking=locking))
    with open(tmp_path / "x.lock", "a+", encoding="utf-8") as f1, \
            open(tmp_path / "x.lock", "a+", encoding="utf-8") as f2:
        f1.write("x")
        lock._lock_nt(f1)
        assert f1.tell() == 0                           # locks from the first byte
        with pytest.raises(OSError):
            lock._lock_nt(f2)


class RuleFlip(FakeBroker):
    """The server-clock fit narrows while the planning pass reads bars."""
    rule = "NY+7"
    calls = 0

    def bars(self, symbol, minutes, count):
        self.calls += 1
        if self.calls == 2:
            self.rule = "EET"
        return super().bars(symbol, minutes, count)


def test_plan_is_recomputed_when_the_clock_rule_changes_mid_pass(tmp_path):
    bars, ds = history()
    b = RuleFlip(bars)
    b.clock = ny(ds[-1], 16, 10)
    r = Runner(cfg(tmp_path), b)
    day, p = r.compute_plan(b.clock)
    assert b.calls == 8 and day == ds[-1] and p.entries == ["US100"]


# ------------------------------------------------- the CLI and the lock

class MainBroker(FakeBroker):
    """Stands in for MT5Broker inside ``ftmo_bot.__main__.main``."""
    seed: list = []
    last = None

    def __init__(self, path=None, probe=None, strict=True, rule=None, login=None):
        bars, ds = history()
        super().__init__(bars)
        self.clock = ny(ds[-1], 12, 0)
        self.verified_at = self.clock
        self.pos = list(MainBroker.seed)
        MainBroker.last = self

    def clock_status(self):
        return "UTC+2 (test)"


def cli_config(tmp_path, dry_run: bool, login=1, extra: str = "") -> str:
    """``login=1``: the account MainBroker's terminal is on."""
    p = tmp_path / "c.yaml"
    p.write_text(f"dry_run: {'true' if dry_run else 'false'}\n"
                 f"state_path: {tmp_path / 'st.json'}\nlog_path: {tmp_path / 'log'}\n"
                 + (f"login: {login}\n" if login is not None else "") + extra,
                 encoding="utf-8")
    return str(p)


def seeded(tmp_path, monkeypatch) -> str:
    from ftmo_bot import broker_mt5
    monkeypatch.setattr(broker_mt5, "MT5Broker", MainBroker)
    MainBroker.seed = [Position(5, "US500.cash", 1.0, 100, 90)]
    State(login=1, plan_day="2026-10-30", pending_exits=["US500"],
          pending_entries=["US100"], pending_atr={"US100": 1.0},
          held={"US500": {"ticket": 5, "entry_day": "2026-10-29"}}
          ).save(tmp_path / "st.json")
    return (tmp_path / "st.json").read_text()


@pytest.mark.parametrize("dry_run,execute", [(True, False), (True, True), (False, False)])
def test_flat_without_both_opt_ins_sends_nothing_and_keeps_the_plan(
        tmp_path, monkeypatch, dry_run, execute):
    from ftmo_bot import __main__ as cli
    before = seeded(tmp_path, monkeypatch)
    argv = ["flat", "--config", cli_config(tmp_path, dry_run)] + (["--execute"] if execute else [])
    assert cli.main(argv) == 1                              # positions remain: not flat
    assert MainBroker.last.sent == [] and MainBroker.last.pos
    assert (tmp_path / "st.json").read_text() == before


def test_flat_with_both_opt_ins_closes_everything(tmp_path, monkeypatch):
    from ftmo_bot import __main__ as cli
    seeded(tmp_path, monkeypatch)
    assert cli.main(["flat", "--config", cli_config(tmp_path, False), "--execute"]) == 0
    assert MainBroker.last.pos == []
    st = State.load(tmp_path / "st.json")
    assert st.pending_exits == [] and st.pending_entries == [] and st.held == {}


def test_flat_refuses_while_another_process_holds_the_state(tmp_path, monkeypatch):
    from ftmo_bot import __main__ as cli, lock
    seeded(tmp_path, monkeypatch)
    held = lock.for_state(str(tmp_path / "st.json"))
    assert held.acquire()
    try:
        assert cli.main(["flat", "--config", cli_config(tmp_path, False), "--execute"]) == 1
        assert MainBroker.last.sent == []
    finally:
        held.release()
    assert cli.main(["flat", "--config", cli_config(tmp_path, False), "--execute"]) == 0


def test_instance_lock_is_exclusive(tmp_path):
    from ftmo_bot import lock
    a, b = lock.InstanceLock(tmp_path / "x.lock"), lock.InstanceLock(tmp_path / "x.lock")
    assert a.acquire() and not b.acquire()
    a.release()
    assert b.acquire()
    b.release()


def test_mt5_clock_reports_a_skewed_pc_clock(clock_mt5):
    from ftmo_bot.broker_mt5 import MT5Broker
    clock_mt5.lag = timedelta(minutes=5)    # moving ticks, 5 minutes off the grid
    b = MT5Broker(probe="US500.cash")
    assert b.verified_at is None and "PC clock" in b.clock_status()


# ------------------------------------------ end to end: a weekend start

class WeekendMT5:
    """MetaTrader5 stand-in for the whole MT5Broker + Runner path. The
    server runs New York + 7 h (UTC+3 in August); ticks move only while
    the CFDs trade (closed Friday 22:00 to Sunday 23:00 UTC and 22:00-23:00
    UTC daily); bars come from ``history()``."""
    TRADE_RETCODE_DONE = 10009
    TIMEFRAME_M30, TIMEFRAME_M15, TIMEFRAME_H1 = 30, 15, 60
    ORDER_TYPE_BUY, ORDER_TYPE_SELL, TRADE_ACTION_DEAL, ORDER_TIME_GTC = 0, 1, 1, 0
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2

    def __init__(self, bars, now):
        self.bars, self.now, self.k, self.orders, self.ps = bars, now, 0, [], []

    @staticmethod
    def trading(t):
        wd, h = t.weekday(), t.hour
        return not (wd == 5 or (wd == 4 and h >= 22) or (wd == 6 and h < 23) or h == 22)

    def initialize(self, *a):
        return True

    def last_error(self):
        return (1, "ok")

    def symbol_select(self, s, f):
        return True

    def symbol_info_tick(self, s):
        if self.trading(self.now):
            self.k += 1
            t = self.now - timedelta(milliseconds=50)
        else:                                       # frozen at the last close
            t = self.now.replace(second=0, microsecond=0)
            while not self.trading(t):
                t -= timedelta(minutes=1)
        stamp = (t + timedelta(hours=3)).timestamp() + self.k / 1e6
        last = [b for b in self.bars[s] if b[0] <= self.now][-1][4]
        return SimpleNamespace(time=int(stamp), time_msc=int(stamp * 1000),
                               bid=last - 0.5, ask=last + 0.5)

    def account_info(self):
        return SimpleNamespace(login=77, server="T", currency="USD", balance=15000.0,
                               equity=15000.0, trade_allowed=True)

    def terminal_info(self):
        return SimpleNamespace(trade_allowed=True)

    def positions_get(self):
        return tuple(self.ps)

    def symbol_info(self, s):
        return SimpleNamespace(filling_mode=1, trade_tick_size=0.01, digits=2,
                               volume_min=0.01, volume_step=0.01, volume_max=500)

    def order_calc_profit(self, typ, s, vol, entry, stop):
        return (stop - entry) * vol

    def copy_rates_from_pos(self, s, tf, pos, n):
        out = []
        for t, o, h, l, c in [b for b in self.bars[s] if b[0] <= self.now][-n:]:
            wall = t.astimezone(NY).replace(tzinfo=UTC)          # NY wall clock as if UTC
            out.append({"time": int((wall + timedelta(hours=7)).timestamp()),
                        "open": o, "high": h, "low": l, "close": c})
        return out

    def order_send(self, req):
        self.orders.append(req)
        if "position" in req:
            self.ps = [p for p in self.ps if p.ticket != req["position"]]
        else:
            self.ps.append(SimpleNamespace(ticket=len(self.orders), symbol=req["symbol"],
                                           volume=req["volume"], price_open=req["price"],
                                           sl=req.get("sl", 0.0), magic=req["magic"]))
        return SimpleNamespace(retcode=10009, price=req["price"], order=len(self.orders),
                               comment="done")


@pytest.mark.parametrize("rule", ["NY+7", None])
def test_weekend_start_still_trades_the_monday_plan(tmp_path, monkeypatch, rule):
    from ftmo_bot import broker_mt5
    bars, ds = history()
    fri, mon = ds[-1], next_day(ds[-1])
    open_session(bars, mon, n=3)
    start = datetime(fri.year, fri.month, fri.day, tzinfo=UTC) + timedelta(days=1, hours=12)
    fake = WeekendMT5(bars, start)                       # Saturday noon UTC
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    monkeypatch.setattr(broker_mt5, "SLEEP",
                        lambda s: setattr(fake, "now", fake.now + timedelta(seconds=s)))
    monkeypatch.setattr(broker_mt5.MT5Broker, "now", lambda self: fake.now)
    c = cfg(tmp_path, dry_run=False, initial_balance=15000, server_clock=rule)
    State(login=77, plan_day=fri.isoformat(), plan_checked=fri.isoformat(),
          pending_entries=["US100"], pending_atr={"US100": 5.0}, initial_balance=15000.0,
          last_fill=(start - timedelta(days=2)).isoformat()).save(tmp_path / "st.json")
    b = broker_mt5.MT5Broker(probe="US500.cash", strict=True, rule=rule)
    assert b.verified_at is None                         # closed market: unverified
    r = Runner(c, b)
    t, end = start, ny(mon, 9, 40).astimezone(UTC)
    while t <= end:                                      # like run(): one tick a minute
        fake.now = t
        try:
            r.tick(t)
        except RuntimeError:
            pass                                         # run() logs and carries on
        t += timedelta(minutes=1 if t.astimezone(NY).date() == mon else 30)
    entries = [o for o in fake.orders if o["type"] == 0 and o.get("sl")]
    assert [o["symbol"] for o in entries] == ["US100.cash"]
    assert r.st.pending_entries == [] and b.verified_at is not None


# ---------------------------------------- the account size, and Windows

@pytest.mark.parametrize("size,balance,target,fits", [
    (15000, 15000, 0.10, True),
    (15000, 15100, 0.10, True),          # within 1%: quiet
    (15000, 15300, 0.10, True),          # 2% off: a warning, and it starts
    (15000, 10000, 0.10, False),         # a $10k account under a $15k config
    (15000, 13500, 0.10, False),         # on the max-loss line: an instant halt
    (15000, 16500, 0.10, False),         # on the target: "reached" at the first tick
    (10000, 15000, 0.05, False),         # a $15k account under a $10k config
    (15000, 16600, None, True),          # funded: no target, so no upper bound
])
def test_a_configured_size_the_account_cannot_have_is_refused(
        tmp_path, caplog, size, balance, target, fits):
    bars, ds = history()
    b = FakeBroker(bars, balance=balance)
    b.clock = ny(ds[-1], 12, 0)
    c = cfg(tmp_path, initial_balance=size, profit_target=target)
    if not fits:
        with pytest.raises(RuntimeError, match="does not fit account 1"):
            Runner(c, b)
        return
    with caplog.at_level(logging.WARNING, logger="ftmo_bot"):
        assert Runner(c, b).st.initial_balance == size
    assert ("check the account size" in caplog.text) == (abs(balance / size - 1) > 0.01)


def test_null_initial_balance_is_taken_from_a_new_account(tmp_path):
    bars, ds = history()
    b = FakeBroker(bars, balance=10000)
    b.clock = ny(ds[-1], 12, 0)
    assert Runner(cfg(tmp_path), b).st.initial_balance == 10000


def test_a_started_account_keeps_its_initial_balance(tmp_path):
    """The size check is for a new account only: after losses the balance
    may sit far from any configured size, and the state's value rules."""
    bars, ds = history()
    b = FakeBroker(bars, balance=13600)
    b.clock = ny(ds[-1], 12, 0)
    State(login=1, initial_balance=15000.0).save(tmp_path / "st.json")
    assert Runner(cfg(tmp_path, initial_balance=10000), b).st.initial_balance == 15000.0


def test_trial_and_challenge_configs_differ_only_in_the_trial_rules():
    trial = load(ROOT / "deploy/ftmo/config.trial.yaml")
    chal = load(ROOT / "deploy/ftmo/config.example.yaml")
    assert (trial.profit_target, trial.min_trading_days, trial.keepalive_days,
            trial.dry_run) == (0.05, 2, 5, False)
    assert (chal.profit_target, chal.min_trading_days, chal.keepalive_days,
            chal.dry_run) == (0.10, 4, 25, True)
    for c in (trial, chal):
        assert c.initial_balance is None and c.server_clock == "NY+7" and c.login is None
        assert c.risk_per_trade == 0.03 and c.cap_combined_risk is True
    t, ch = dataclasses.asdict(trial), dataclasses.asdict(chal)
    assert {k for k in t if t[k] != ch[k]} == {
        "profit_target", "min_trading_days", "keepalive_days", "dry_run"}


def test_config_edited_in_notepad_loads_on_windows(tmp_path, monkeypatch):
    """Windows reads a text file without an explicit encoding as cp1252,
    and Notepad may save a byte-order mark: both broke the config."""
    real = pathlib.Path.read_text

    def windows(self, encoding=None, *a, **k):
        return real(self, encoding or "cp1252", *a, **k)
    monkeypatch.setattr(pathlib.Path, "read_text", windows)
    p = tmp_path / "c.yaml"
    p.write_bytes("\ufeff# trial \u2014 my notes\nrisk_per_trade: 0.02\n".encode("utf-8"))
    assert load(p).risk_per_trade == 0.02


def test_bot_never_opens_a_text_file_without_an_encoding():
    """The config, the state, the log and the instance lock all name their
    encoding, so Windows' cp1252 default is never used."""
    calls = ("open", "read_text", "write_text", "FileHandler")
    found = 0
    for src in sorted((ROOT / "ftmo_bot").glob("*.py")):
        for node in ast.walk(ast.parse(src.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if name not in calls:
                continue
            modes = [a.value for a in node.args
                     if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            if any(set(m) <= set("rwaxbt+") and "b" in m for m in modes):
                continue                                    # binary: no encoding
            found += 1
            assert any(k.arg == "encoding" for k in node.keywords), \
                f"{src.name}:{node.lineno}: {name}() without encoding="
    assert found >= 6


def test_powershell_scripts_are_plain_ascii():
    """Windows PowerShell 5.1 reads a .ps1 without a byte-order mark as
    ANSI: one em dash becomes three characters and can break a string."""
    scripts = sorted((ROOT / "deploy").rglob("*.ps1"))
    assert len(scripts) >= 4
    for p in scripts:
        bad = [i for i, ch in enumerate(p.read_bytes()) if ch > 127]
        assert not bad, f"{p.relative_to(ROOT)}: non-ASCII byte at offset {bad[0]}"


def test_ftmo_scripts_point_at_files_that_exist():
    for script in ("setup.ps1", "run.ps1"):
        text = (ROOT / "deploy/ftmo" / script).read_text(encoding="ascii")
        refs = set(re.findall(r"deploy\\ftmo\\[\w.]+", text))
        assert refs
        for ref in refs:
            assert (ROOT / ref.replace("\\", "/")).is_file(), f"{script}: {ref}"


def test_cli_preflight_prints_the_rules_and_passes(tmp_path, monkeypatch, capsys):
    from ftmo_bot import __main__ as cli
    before = seeded(tmp_path, monkeypatch)
    assert cli.main(["preflight", "--config", cli_config(tmp_path, False)]) == 0
    out = capsys.readouterr().out
    assert ("rules: initial balance 15,000.00 (from the account), max-loss line "
            "13,500.00, profit target 16,500.00, trading days 0 of 4\n") in out
    assert out.count("PASS ") == 4 and "FAIL" not in out and "WARN" not in out
    assert MainBroker.last.sent == [] and (tmp_path / "st.json").read_text() == before


@pytest.mark.parametrize("state,cfg_extra,expect", [
    (dict(initial_balance=15000.0, halted="profit target reached"), "profit_target: null\n",
     "initial balance 15,000.00 (from the bot's state), max-loss line 13,500.00, "
     "no profit target (funded), trading days 0 of 4; HALTED: profit target reached\n"),
    (dict(initial_balance=15000.0, target_locked="2026-10-30", trading_days=["2026-10-29"]),
     "", "profit target 16,500.00, trading days 1 of 4; target locked\n"),
])
def test_cli_preflight_rules_line_shows_funded_halted_and_locked(
        tmp_path, monkeypatch, capsys, state, cfg_extra, expect):
    from ftmo_bot import __main__ as cli, broker_mt5
    monkeypatch.setattr(broker_mt5, "MT5Broker", MainBroker)
    MainBroker.seed = []
    State(login=1, **state).save(tmp_path / "st.json")
    assert cli.main(["preflight", "--config", cli_config(tmp_path, False, extra=cfg_extra)]) == 0
    assert expect in capsys.readouterr().out


def snapshot(d: pathlib.Path) -> dict:
    return {f.name: f.read_bytes() for f in sorted(d.iterdir()) if f.name != "log"}


@pytest.mark.parametrize("files", [
    {"st.json": State(login=2, halted="max loss", trading_days=["2026-10-01"]),
     "st.1.json": State(login=1, initial_balance=15000.0, trading_days=["2026-10-02"])},
    {"st.json": State(login=2, initial_balance=15000.0, halted="max loss")},
    {"st.json": State(login=None, halted="profit target reached")},
    {},
], ids=["foreign-login-with-parked", "foreign-login", "legacy-halted", "no-state"])
@pytest.mark.parametrize("command", ["preflight", "plan"])
def test_cli_read_only_commands_never_move_or_write_state(
        tmp_path, monkeypatch, capsys, files, command):
    from ftmo_bot import __main__ as cli, broker_mt5
    monkeypatch.setattr(broker_mt5, "MT5Broker", MainBroker)
    MainBroker.seed = []
    for name, st in files.items():
        st.save(tmp_path / name)
    config = cli_config(tmp_path, False)
    before = snapshot(tmp_path)
    assert cli.main([command, "--config", config]) == 0
    assert snapshot(tmp_path) == before and MainBroker.last.sent == []


def test_a_refused_start_on_a_new_account_moves_no_state(tmp_path):
    """The size check runs before the old account's state is parked, so a
    refused start strands nothing: back on the old account, its halt and
    trading days are still there."""
    bars, ds = history()
    b = Switchable(bars)
    b.clock = ny(ds[-1], 12, 0)
    State(login=1, initial_balance=15000.0, halted="max loss",
          trading_days=["2026-10-01"]).save(tmp_path / "st.json")
    before = snapshot(tmp_path)
    c = cfg(tmp_path, initial_balance=10000)                    # misfit for a 15,000 balance
    b.login = 2
    with pytest.raises(RuntimeError, match="does not fit account 2"):
        Runner(c, b)
    assert snapshot(tmp_path) == before
    b.login = 1
    r = Runner(c, b)
    assert r.st.halted == "max loss" and r.st.trading_days == ["2026-10-01"]


def test_state_saved_by_notepad_with_a_byte_order_mark_loads(tmp_path):
    p = tmp_path / "st.json"
    p.write_text("\ufeff" + json.dumps({"login": 7, "halted": None}), encoding="utf-8")
    assert State.load(p).login == 7


@pytest.mark.parametrize("text,msg", [
    ('{"login": 7, "halted": null,}', "could not be read"),
    ("[1, 2]", "does not hold a state"),
])
def test_unreadable_state_is_a_clear_refusal(tmp_path, monkeypatch, capsys, text, msg):
    p = tmp_path / "st.json"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(RuntimeError, match=msg):
        State.load(p)
    from ftmo_bot import __main__ as cli, broker_mt5
    monkeypatch.setattr(broker_mt5, "MT5Broker", MainBroker)
    MainBroker.seed = []
    assert cli.main(["preflight", "--config", cli_config(tmp_path, False)]) == 1
    assert f"FAIL state file {p}" in capsys.readouterr().out
    assert p.read_text(encoding="utf-8") == text


@pytest.mark.parametrize("balance,warns", [(10000, False), (10003.21, True)])
def test_a_new_account_that_already_traded_is_flagged(tmp_path, caplog, balance, warns):
    bars, ds = history()
    b = FakeBroker(bars, balance=balance)
    b.clock = ny(ds[-1], 12, 0)
    with caplog.at_level(logging.INFO, logger="ftmo_bot"):
        r = Runner(cfg(tmp_path), b)
    assert r.st.initial_balance == balance and r.balance_source == "the account"
    assert ("starts at a round size" in caplog.text) == warns


def test_cli_preflight_fails_on_a_size_the_account_cannot_have(tmp_path, monkeypatch, capsys):
    from ftmo_bot import __main__ as cli
    seeded(tmp_path, monkeypatch)
    p = cli_config(tmp_path, False, extra="initial_balance: 10000\n")
    assert cli.main(["preflight", "--config", p]) == 1
    out = capsys.readouterr().out
    assert "FAIL initial_balance 10,000.00 in the config does not fit account 1" in out
    assert "rules:" not in out


def test_cli_plan_and_flat_refuse_a_misfit_size_without_a_traceback(
        tmp_path, monkeypatch, capsys):
    from ftmo_bot import __main__ as cli
    before = seeded(tmp_path, monkeypatch)                     # a state without a size
    p = cli_config(tmp_path, False, extra="initial_balance: 10000\n")
    assert cli.main(["plan", "--config", p]) == 1
    assert "FAIL initial_balance 10,000.00" in capsys.readouterr().out
    assert cli.main(["flat", "--config", p, "--execute"]) == 1
    out = capsys.readouterr().out
    assert "FAIL initial_balance 10,000.00" in out and "nothing was closed" in out
    assert MainBroker.last.sent == [] and MainBroker.last.pos
    assert (tmp_path / "st.json").read_text() == before


def test_cli_plan_reads_only(tmp_path, monkeypatch, capsys):
    from ftmo_bot import __main__ as cli
    before = seeded(tmp_path, monkeypatch)
    assert cli.main(["plan", "--config", cli_config(tmp_path, False)]) == 0
    out = capsys.readouterr().out
    assert "held by the bot: {'US500'" in out and "plan from the" in out
    assert MainBroker.last.sent == [] and (tmp_path / "st.json").read_text() == before


# ------------------------------------------- orders go to one account only

@pytest.fixture
def started(monkeypatch):
    """Runner.run replaced by a recorder (the real one never returns)."""
    calls = []
    monkeypatch.setattr(Runner, "run", lambda self: calls.append(self.cfg.dry_run))
    return calls


@pytest.mark.parametrize("command", ["run", "flat"])
def test_orders_need_the_account_named_in_the_config(
        tmp_path, monkeypatch, capsys, started, command):
    from ftmo_bot import __main__ as cli
    before = seeded(tmp_path, monkeypatch)
    p = cli_config(tmp_path, False, login=None)
    assert cli.main([command, "--config", p, "--execute"]) == 1
    out = capsys.readouterr().out
    assert "REFUSED" in out and "`login: 1`" in out
    assert started == [] and MainBroker.last.sent == [] and MainBroker.last.pos
    assert (tmp_path / "st.json").read_text() == before


@pytest.mark.parametrize("command,args", [
    ("run", ["--execute"]), ("flat", ["--execute"]), ("preflight", []), ("plan", []),
])
def test_a_terminal_on_another_account_is_refused(
        tmp_path, monkeypatch, capsys, started, command, args):
    from ftmo_bot import __main__ as cli
    before = seeded(tmp_path, monkeypatch)
    assert cli.main([command, "--config", cli_config(tmp_path, False, login=2)] + args) == 1
    assert "FAIL the terminal is on account 1" in capsys.readouterr().out
    assert started == [] and MainBroker.last.sent == []
    assert (tmp_path / "st.json").read_text() == before


def test_run_starts_on_the_named_account_and_prints_the_rules(
        tmp_path, monkeypatch, capsys, started):
    from ftmo_bot import __main__ as cli
    seeded(tmp_path, monkeypatch)
    assert cli.main(["run", "--config", cli_config(tmp_path, False), "--execute"]) == 0
    assert started == [False]                                   # live: both opt-ins and the login
    assert "rules: initial balance 15,000.00 (from the account)" in capsys.readouterr().out


def test_dry_run_needs_no_login(tmp_path, monkeypatch, capsys, started):
    from ftmo_bot import __main__ as cli
    seeded(tmp_path, monkeypatch)
    assert cli.main(["run", "--config", cli_config(tmp_path, False, login=None)]) == 0
    assert started == [True]                                    # no --execute: dry run
    assert cli.main(["preflight", "--config", cli_config(tmp_path, False, login=None)]) == 0
    assert "WARN: login not set" in capsys.readouterr().out


@pytest.mark.parametrize("login", ["12345", True, 0, -5, 12.5])
def test_login_must_be_an_account_number(login):
    with pytest.raises(ValueError, match="login"):
        FtmoConfig(login=login).validate()


def test_run_ps1_sends_orders_only_for_live_and_flat():
    text = (ROOT / "deploy/ftmo/run.ps1").read_text(encoding="ascii")
    cmds = dict(re.findall(r'^(?:if|elseif) \(\$(\w+)\) \{ \$cmd = @\(([^)]*)\) \}', text, re.M))
    default = re.search(r'^else \{ \$cmd = @\(([^)]*)\) \}', text, re.M).group(1)
    assert set(cmds) == {"Plan", "DryRun", "Live", "Flat"}
    assert {k for k, v in cmds.items() if "--execute" in v} == {"Live", "Flat"}
    assert '"preflight"' in default and "--execute" not in default
    code = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    assert sum(line.count("--execute") for line in code) == 2       # nowhere else


def test_setup_ps1_installs_the_trial_config_by_default():
    text = (ROOT / "deploy/ftmo/setup.ps1").read_text(encoding="ascii")
    assert re.search(r'\[string\]\$Account = "trial"', text)
    assert re.search(r'if \(\$Account -eq "trial"\) \{ \$source = "deploy\\ftmo\\config\.trial\.yaml" \}', text)
    assert re.search(r'else \{ \$source = "deploy\\ftmo\\config\.example\.yaml" \}', text)


# ------------------------------------- second review: the edges of the CLI

class FlipBroker(MainBroker):
    """Its terminal switches from account 1 to 2 right after the first read."""
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.reads = 0

    def account(self):
        self.reads += 1
        return dataclasses.replace(super().account(), login=1 if self.reads == 1 else 2)


@pytest.mark.parametrize("command", ["run", "flat"])
def test_a_switch_between_the_two_account_reads_is_refused(
        tmp_path, monkeypatch, capsys, started, command):
    from ftmo_bot import __main__ as cli, broker_mt5
    before = seeded(tmp_path, monkeypatch)
    monkeypatch.setattr(broker_mt5, "MT5Broker", FlipBroker)
    assert cli.main([command, "--config", cli_config(tmp_path, False), "--execute"]) == 1
    assert "FAIL the terminal is on account 2" in capsys.readouterr().out
    assert started == [] and MainBroker.last.sent == [] and MainBroker.last.pos
    assert (tmp_path / "st.json").read_text() == before
    assert not (tmp_path / "st.1.json").exists()


@pytest.mark.parametrize("command,args", [
    ("preflight", []), ("plan", []), ("run", ["--execute"]), ("flat", ["--execute"]),
])
def test_every_command_refuses_an_unreadable_state_cleanly(
        tmp_path, monkeypatch, capsys, started, command, args):
    from ftmo_bot import __main__ as cli, broker_mt5
    monkeypatch.setattr(broker_mt5, "MT5Broker", MainBroker)
    MainBroker.seed = [Position(5, "US500.cash", 1.0, 100, 90)]
    p = tmp_path / "st.json"
    p.write_text('{"login": 1,', encoding="utf-8")
    assert cli.main([command, "--config", cli_config(tmp_path, False)] + args) == 1
    assert f"FAIL state file {p}" in capsys.readouterr().out
    assert started == [] and MainBroker.last.sent == [] and MainBroker.last.pos
    assert p.read_text(encoding="utf-8") == '{"login": 1,'


def test_run_refuses_a_misfit_size_without_a_traceback(tmp_path, monkeypatch, capsys, started):
    from ftmo_bot import __main__ as cli
    before = seeded(tmp_path, monkeypatch)
    p = cli_config(tmp_path, False, extra="initial_balance: 10000\n")
    assert cli.main(["run", "--config", p, "--execute"]) == 1
    assert "FAIL initial_balance 10,000.00" in capsys.readouterr().out
    assert started == [] and MainBroker.last.sent == []
    assert (tmp_path / "st.json").read_text() == before


@pytest.mark.parametrize("extra,msg", [
    ("login: 1.5\n", "login must be the account number"),
    ("logn: 1\n", "unknown settings ['logn']: check the spelling"),
    ("dry_run:\n", "dry_run must be true or false"),         # the later key wins
    ("dry_run: 0\n", "dry_run must be true or false"),
    ("risk_per_trade: [0.03\n", ""),                          # not YAML
    ("password: hunter2\n", "credentials do not belong in the config"),
])
def test_a_config_mistake_is_one_fail_line(tmp_path, monkeypatch, capsys, extra, msg):
    from ftmo_bot import __main__ as cli, broker_mt5
    monkeypatch.setattr(broker_mt5, "MT5Broker", MainBroker)
    p = cli_config(tmp_path, False, extra=extra)
    assert cli.main(["preflight", "--config", p]) == 1
    out = capsys.readouterr().out
    assert out.startswith(f"FAIL config {p}: ") and msg in out


def test_a_missing_config_is_one_fail_line(tmp_path, capsys):
    from ftmo_bot import __main__ as cli
    assert cli.main(["preflight", "--config", str(tmp_path / "nope.yaml")]) == 1
    assert capsys.readouterr().out.startswith("FAIL config ")


def test_a_quoted_login_is_read_as_the_number(tmp_path, monkeypatch, capsys):
    from ftmo_bot import __main__ as cli
    seeded(tmp_path, monkeypatch)
    p = cli_config(tmp_path, False, login='"1"')
    assert load(p).login == 1
    assert cli.main(["preflight", "--config", p]) == 0
    assert "login not set" not in capsys.readouterr().out


def test_an_unreachable_terminal_is_one_fail_line(tmp_path, monkeypatch, capsys):
    from ftmo_bot import __main__ as cli, broker_mt5

    class Down:
        def __init__(self, *a, **k):
            raise RuntimeError("MT5 initialize failed: (-6, 'Authorization failed'). "
                               "Open the FTMO MT5 terminal and log in first.")
    monkeypatch.setattr(broker_mt5, "MT5Broker", Down)
    assert cli.main(["preflight", "--config", cli_config(tmp_path, False)]) == 1
    out = capsys.readouterr().out
    assert out.startswith("FAIL cannot reach the MT5 terminal: MT5 initialize failed")
    assert "mt5_path" in out


def test_refusals_say_to_replace_the_null_login_line(tmp_path, monkeypatch, capsys, started):
    """PyYAML keeps the last of two keys: a second login line above the
    shipped `login: null` would be ignored, so the messages say replace."""
    from ftmo_bot import __main__ as cli
    seeded(tmp_path, monkeypatch)
    assert cli.main(["run", "--config", cli_config(tmp_path, False, login=None), "--execute"]) == 1
    assert "(replace the `login: null` line)" in capsys.readouterr().out
    assert cli.main(["preflight", "--config", cli_config(tmp_path, False, login=None)]) == 0
    assert "(replace the `login: null` line;" in capsys.readouterr().out


# -------------------------------------- third review: config types, the pin

@pytest.mark.parametrize("text", ["[]\n", "- a\n", "0\n", "false\n", '""\n'])
def test_a_config_that_is_not_key_value_lines_is_refused(tmp_path, text):
    p = tmp_path / "c.yaml"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="key: value"):
        load(p)


def test_an_empty_config_file_means_the_defaults(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("", encoding="utf-8")
    c = load(p)
    assert c.dry_run is True and c.login is None


@pytest.mark.parametrize("login,ok", [
    ("1234567", True), (" 1234567 ", True),
    (chr(0xFF11) * 3, False),                 # fullwidth digits
    (chr(0xB2), False),                       # a superscript two
    ("+5", False), ("1_000", False), ("12.5", False), ("0", False), ("", False),
])
def test_a_quoted_login_must_be_plain_digits(tmp_path, login, ok):
    p = tmp_path / "c.yaml"
    p.write_text(f"login: {json.dumps(login)}\n", encoding="utf-8")
    if ok:
        assert load(p).login == 1234567
    else:
        with pytest.raises(ValueError, match="login must be the account number"):
            load(p)


@pytest.mark.parametrize("line,msg", [
    ("cap_combined_risk:", "cap_combined_risk must be true or false, not blank"),
    ("cap_combined_risk: 1", "cap_combined_risk must be true or false, not 1"),
    ("keepalive_days:", "keepalive_days must be a whole number, not blank"),
    ("keepalive_days: 2.5", "keepalive_days must be a whole number, not 2.5"),
    ("risk_per_trade: 3%", "risk_per_trade must be a number, not '3%'"),
    ("risk_per_trade: true", "risk_per_trade must be a number, not True"),
    ("dry_run:", "dry_run must be true or false, not blank"),
    ("symbols: {US500: null}", "symbols must be name: symbol lines"),
    ("state_path:", "state_path must be text, not blank"),
])
def test_every_setting_has_its_type(tmp_path, line, msg):
    p = tmp_path / "c.yaml"
    p.write_text(line + "\n", encoding="utf-8")
    with pytest.raises(ValueError) as e:
        load(p)
    assert msg in str(e.value)


def test_both_shipped_configs_pass_the_type_checks():
    for name in ("config.trial.yaml", "config.example.yaml"):
        load(ROOT / "deploy/ftmo" / name)            # raises on any bad type


def test_a_missing_metatrader5_package_says_to_run_setup(tmp_path, monkeypatch, capsys):
    from ftmo_bot import __main__ as cli, broker_mt5

    class NoPackage:
        def __init__(self, *a, **k):
            raise ImportError("No module named 'MetaTrader5'")
    monkeypatch.setattr(broker_mt5, "MT5Broker", NoPackage)
    assert cli.main(["preflight", "--config", cli_config(tmp_path, False)]) == 1
    out = capsys.readouterr().out
    assert out.startswith("FAIL the MetaTrader5 package is missing") and "setup.ps1" in out
    assert "cannot reach" not in out and "mt5_path" not in out


def test_an_unreachable_terminal_message_has_one_full_stop(tmp_path, monkeypatch, capsys):
    from ftmo_bot import __main__ as cli, broker_mt5

    class Down:
        def __init__(self, *a, **k):
            raise RuntimeError("MT5 initialize failed: (-6, 'x'). Open the terminal first.")
    monkeypatch.setattr(broker_mt5, "MT5Broker", Down)
    assert cli.main(["preflight", "--config", cli_config(tmp_path, False)]) == 1
    out = capsys.readouterr().out
    assert "Open the terminal first. With several" in out and ".." not in out


def pinned_mt5(monkeypatch, login):
    """An MT5Broker on WeekendMT5 at a trading moment, pinned to ``login``."""
    from ftmo_bot import broker_mt5
    bars, ds = history()
    fake = WeekendMT5(bars, ny(ds[-1], 12, 0).astimezone(UTC))
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    return fake, broker_mt5.MT5Broker(probe=None, strict=False, rule="NY+7", login=login)


def test_every_order_is_checked_against_the_pinned_account(monkeypatch):
    fake, b = pinned_mt5(monkeypatch, login=77)          # WeekendMT5 is account 77
    assert b.buy("US500.cash", 0.01, None, 404040, "t").ok
    pos = Position(len(fake.orders), "US500.cash", 0.01, 100.0, 0.0)
    fake.account_info = lambda: SimpleNamespace(login=78, server="T", currency="USD",
                                                balance=15000.0, equity=15000.0,
                                                trade_allowed=True)
    sent = len(fake.orders)
    for f in (b.buy("US500.cash", 0.01, None, 404040, "t"), b.close(pos, 404040, "t")):
        assert not f.ok and "refused: the terminal is on account 78, not 77" in f.message
    assert len(fake.orders) == sent                      # nothing reached account 78
    fake.account_info = lambda: None                     # terminal gone: refused too
    assert not b.buy("US500.cash", 0.01, None, 404040, "t").ok and len(fake.orders) == sent


def test_an_unpinned_broker_sends_as_before(monkeypatch):
    fake, b = pinned_mt5(monkeypatch, login=None)
    fake.account_info = lambda: None                     # never consulted
    assert b.buy("US500.cash", 0.01, None, 404040, "t").ok and len(fake.orders) == 1


def test_main_pins_the_broker_to_the_configured_login(tmp_path, monkeypatch, started):
    from ftmo_bot import __main__ as cli
    seeded(tmp_path, monkeypatch)
    seen = {}
    real = MainBroker.__init__

    def spy(self, *a, **k):
        seen.update(k)
        real(self, *a, **k)
    monkeypatch.setattr(MainBroker, "__init__", spy)
    assert cli.main(["run", "--config", cli_config(tmp_path, False), "--execute"]) == 0
    assert seen.get("login") == 1


# ------------------------------------------- fourth review: the last edges

def test_a_password_pasted_into_login_is_never_printed(tmp_path, monkeypatch, capsys):
    from ftmo_bot import __main__ as cli, broker_mt5
    monkeypatch.setattr(broker_mt5, "MT5Broker", MainBroker)
    secret = "Tr0ub4dor&3"
    p = tmp_path / "c.yaml"
    p.write_text(f"login: {secret}\n", encoding="utf-8")
    with pytest.raises(ValueError) as e:
        load(p)
    assert secret not in str(e.value) and "login must be the account number" in str(e.value)
    assert str(e.value).endswith("not text")
    assert cli.main(["preflight", "--config", str(p)]) == 1
    assert secret not in capsys.readouterr().out


def test_every_config_field_has_a_known_type():
    from ftmo_bot.config import TYPE_KINDS, field_kind
    for f in dataclasses.fields(FtmoConfig):
        kind, _ = field_kind(f.type)
        assert kind in TYPE_KINDS, f"{f.name}: {f.type!r}"


@pytest.mark.parametrize("kw", [
    dict(max_loss=0.5), dict(daily_loss=0.2), dict(guard_buffer=-1.0),
    dict(guard_buffer=0.05), dict(notional_cap=-3.0), dict(atr_stop_mult=0.0),
    dict(max_hold_sessions=0), dict(magic=0), dict(keepalive_days=-1),
    dict(min_trading_days=-1),
])
def test_settings_out_of_range_are_refused(kw):
    with pytest.raises(ValueError):
        FtmoConfig(**kw).validate()


def test_a_close_refused_by_the_pin_stays_queued_and_closes_later(tmp_path, monkeypatch):
    """Through the real MT5Broker and Runner: the terminal shows another
    account at the moment of the close, so nothing is sent and the ticket
    waits in to_close; back on the pinned account, the retry closes it."""
    fake, b = pinned_mt5(monkeypatch, login=77)
    fake.ps = [SimpleNamespace(ticket=9, symbol="US500.cash", volume=0.01,
                               price_open=100.0, sl=90.0, magic=404040)]
    r = Runner(cfg(tmp_path, dry_run=False, login=77, server_clock="NY+7"), b)
    live = b.positions(404040)
    assert [x.ticket for x in live] == [9]
    real = fake.account_info
    fake.account_info = lambda: SimpleNamespace(login=78, server="T", currency="USD",
                                                balance=15000.0, equity=15000.0,
                                                trade_allowed=True)
    assert r._close(live[0], "test", fake.now) is False
    assert r.st.to_close == [9] and fake.orders == []
    fake.account_info = real                             # back on account 77
    r.retry_closes(fake.now, b.positions(404040))
    assert r.st.to_close == [] and fake.ps == [] and len(fake.orders) == 1


def test_holding_counts_a_terminal_on_another_account_as_holding(tmp_path):
    bars, ds = history()
    b = Switchable(bars)
    b.clock = ny(ds[-1], 12, 0)
    r = Runner(cfg(tmp_path, dry_run=False), b)
    assert r.holding() is False                          # its own account, nothing open
    b.login = 2
    assert r.holding() is True                           # it cannot see its own book



# ------------------------------------------------ fifth review: the edges

@pytest.mark.parametrize("line", [
    "login: @Tr0ub4dor3", "login: *Tr0ub4dor3", "login: Tr0ub4dor3: x", "login: {Tr0ub4dor3",
])
def test_a_yaml_error_never_prints_the_line(tmp_path, monkeypatch, capsys, line):
    """A password pasted into the config can make it invalid YAML, and
    YAML's own message quotes the line: only the line number is shown."""
    from ftmo_bot import __main__ as cli, broker_mt5
    monkeypatch.setattr(broker_mt5, "MT5Broker", MainBroker)
    p = tmp_path / "c.yaml"
    p.write_text("dry_run: true\n" + line + "\n", encoding="utf-8")
    assert cli.main(["preflight", "--config", str(p)]) == 1
    out = capsys.readouterr().out
    assert "Tr0ub4dor3" not in out
    assert out.startswith(f"FAIL config {p}: not valid YAML at line ")   # 2, or 3 for `{`


def test_a_refused_order_is_logged_with_its_cause(monkeypatch, caplog):
    fake, b = pinned_mt5(monkeypatch, login=77)
    fake.account_info = lambda: None
    with caplog.at_level(logging.WARNING):
        f = b.buy("US500.cash", 0.01, None, 404040, "t")
    assert not f.ok and "cannot be read" in f.message and "(1, 'ok')" in f.message
    assert "order refused" in caplog.text and "pinned account 77" in caplog.text
    assert fake.orders == []


@pytest.mark.parametrize("kw", [
    dict(notional_cap=30.01), dict(atr_stop_mult=10.01), dict(max_loss=0.2001),
    dict(profit_target=float("nan")), dict(profit_target=float("inf")),
    dict(profit_target=1.5), dict(initial_balance=float("inf")),
    dict(initial_balance=float("nan")),
])
def test_settings_past_the_upper_bounds_are_refused(kw):
    with pytest.raises(ValueError):
        FtmoConfig(**kw).validate()


def test_settings_on_the_bounds_are_accepted():
    FtmoConfig(max_loss=0.20, daily_loss=0.20, guard_buffer=0.0, notional_cap=30.0,
               atr_stop_mult=10.0, max_hold_sessions=1, keepalive_days=0,
               min_trading_days=0, profit_target=1.0).validate()


@pytest.mark.parametrize("value,shown", [
    ("true", "not a yes/no value"), ("2026-11-02", "not another kind of value"),
    ("[1]", "not a list"), ("12.5", "not a decimal number"),
])
def test_a_wrong_login_is_described_not_echoed(tmp_path, value, shown):
    p = tmp_path / "c.yaml"
    p.write_text(f"login: {value}\n", encoding="utf-8")
    with pytest.raises(ValueError) as e:
        load(p)
    assert str(e.value).endswith(shown)


def test_a_bare_load_traceback_never_quotes_the_line(tmp_path):
    """setup.ps1's check calls load() directly, so Python prints the whole
    traceback: the YAML error (which quotes the line) must not be in it."""
    import subprocess
    p = tmp_path / "c.yaml"
    p.write_text("dry_run: true\nlogin: @Tr0ub4dor3\n", encoding="utf-8")
    r = subprocess.run([sys.executable, "-c", "import sys; from ftmo_bot.config import load; "
                        "load(sys.argv[1])", str(p)],
                       cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert r.returncode != 0
    assert "ValueError: not valid YAML at line 2" in r.stderr
    assert "Tr0ub4dor3" not in r.stderr + r.stdout
