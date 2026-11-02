"""FTMO bot readiness: the server clock, one state per account, trading
days on FTMO's calendar, the target lock with its finish line, and
keep-alive on every phase."""

from __future__ import annotations

import dataclasses
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_ftmo_bot import FakeBroker, cfg, history, next_day, ny, open_session, planned  # noqa: E402

from ftmo_bot import server_clock  # noqa: E402
from ftmo_bot.broker import Position  # noqa: E402
from ftmo_bot.config import FtmoConfig  # noqa: E402
from ftmo_bot.runner import Runner, State  # noqa: E402

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


def test_state_load_ignores_unknown_keys(tmp_path):
    p = tmp_path / "st.json"
    p.write_text(json.dumps({"login": 7, "a_newer_field": 1, "trading_days": ["x"]}))
    st = State.load(p)
    assert st.login == 7 and st.trading_days == ["x"]


def test_initial_balance_must_be_positive():
    with pytest.raises(ValueError, match="initial_balance"):
        FtmoConfig(initial_balance=0).validate()


def test_clock_refusal_still_runs_the_planned_exits(tmp_path):
    r, b, bars, ds = planned(tmp_path, dry_run=False)
    b.pos = [Position(5, "US500.cash", 1.0, 100, 90)]
    r.st.held = {"US500": {"ticket": 5, "entry_day": ds[-1].isoformat()}}
    r.st.pending_exits = ["US500"]
    nxt = next_day(ds[-1])
    open_session(bars, nxt)
    b.clock = ny(nxt, 9, 35)

    def refuse(*a, **k):
        raise RuntimeError("server clock unverified")
    b.bars = refuse
    r.tick()
    assert ("close", "US500.cash", 1.0, "FAST4 exit") in b.sent
    assert not [x for x in b.sent if x[0] == "buy"]             # entries skipped
    assert r.st.pending_entries == [] and r.st.executed_day == nxt.isoformat()


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

    def __init__(self, path=None, probe=None, strict=True, rule=None):
        bars, ds = history()
        super().__init__(bars)
        self.clock = ny(ds[-1], 12, 0)
        self.verified_at = self.clock
        self.pos = list(MainBroker.seed)
        MainBroker.last = self

    def clock_status(self):
        return "UTC+2 (test)"


def cli_config(tmp_path, dry_run: bool) -> str:
    p = tmp_path / "c.yaml"
    p.write_text(f"dry_run: {'true' if dry_run else 'false'}\n"
                 f"state_path: {tmp_path / 'st.json'}\nlog_path: {tmp_path / 'log'}\n")
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
