"""The 5-step scale-out exits (``ftmo_bot/scale_out.py``) and the runner's
``manage`` step, against the fake broker of test_ftmo_bot."""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ftmo_bot import fast4, scale_out  # noqa: E402
from ftmo_bot.broker import Position  # noqa: E402
from ftmo_bot.broker_sim import SimBroker  # noqa: E402
from ftmo_bot.config import FtmoConfig, load  # noqa: E402
from ftmo_bot.runner import Runner  # noqa: E402
from test_ftmo_bot import FakeBroker, cfg, history, next_day, ny  # noqa: E402

SYMS = ("US100.cash", "US500.cash", "US30.cash", "US2000.cash")
ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------- pure parts

def test_stage_needs_the_level_and_keeps_what_was_reached():
    e, r = 100.0, 10.0
    assert scale_out.stage(109.99, e, r) == 0
    assert scale_out.stage(110.0, e, r) == 1                 # +1R
    assert scale_out.stage(114.99, e, r) == 1
    assert scale_out.stage(115.0, e, r) == 2                 # +1.5R, both targets at once
    assert scale_out.stage(95.0, e, r, reached=1) == 1       # a filled target stays filled
    assert scale_out.stage(111.0, e, r, reached=2) == 2


def test_stop_floor_per_step():
    e, r = 100.0, 10.0
    assert scale_out.stop_floor(0, e, r) is None             # the first stop stands
    assert scale_out.stop_floor(1, e, r, high_close=130) == e     # break-even, no trail yet
    assert scale_out.stop_floor(2, e, r) == 110.0            # +1R
    assert scale_out.stop_floor(2, e, r, high_close=115) == 110.0
    assert scale_out.stop_floor(2, e, r, high_close=133) == 123.0  # 1R under the high close


@pytest.mark.parametrize("vol0,st,volume,step,vmin,want", [
    (0.33, 1, 0.33, 0.01, 0.01, 0.17),     # half, rounded half up
    (0.33, 2, 0.16, 0.01, 0.01, 0.08),     # then a quarter: 0.25 closed in all
    (0.33, 2, 0.33, 0.01, 0.01, 0.25),     # both targets in one move
    (0.33, 1, 0.16, 0.01, 0.01, 0.0),      # already done: nothing more
    (0.33, 0, 0.33, 0.01, 0.01, 0.0),      # before the first target
    (0.04, 2, 0.02, 0.01, 0.01, 0.01),     # the last 0.01 trails
    (0.03, 2, 0.01, 0.01, 0.01, 0.0),      # 0.02 closed at TP1 already covers 3/4
    (0.02, 2, 0.01, 0.01, 0.01, 0.0),      # a target never sells the last lot: it trails
    (0.01, 1, 0.01, 0.01, 0.01, 0.0),      # one minimum lot is never split: stops only
    (1.0, 2, 0.5, 0.1, 0.5, 0.0),          # a slice under the minimum lot is not sent
    (1.0, 2, 1.0, 0.1, 0.3, 0.7),          # leave the minimum lot open, not 0.2
    (0.33, 1, 0.33, 0.0, 0.01, 0.0),       # no volume step: symbol unavailable
])
def test_to_close(vol0, st, volume, step, vmin, want):
    assert scale_out.to_close(vol0, volume, st, step, vmin) == pytest.approx(want)


def test_plan_keeps_scale_out_positions_out_of_the_fast4_exits():
    i = {"US100": fast4.Indicators(105, 90, 101, 50, 10.0),     # close > SMA5
         "US500": fast4.Indicators(105, 90, 101, 50, 10.0),
         "US30": fast4.Indicators(100, 90, 101, 3, 10.0),
         "US2000": fast4.Indicators(100, 110, 101, 2, 10.0)}
    p = fast4.plan(i, {"US100": 1, "US500": 12}, keep={"US100"})
    assert p.exits == ["US500"]                  # US100 is the scale-out's to manage
    assert p.entries == ["US30"]                 # US100 still takes its slot


def test_shipped_configs_use_the_five_steps():
    assert FtmoConfig().exit_mode == "scale_out"
    for name in ("config.trial.yaml", "config.example.yaml"):
        assert load(ROOT / "deploy/ftmo" / name).exit_mode == "scale_out"
    with pytest.raises(ValueError, match="exit_mode"):
        FtmoConfig(exit_mode="webinar").validate()


# ---------------------------------------------------------- the runner

class Scene:
    """A runner that planned a US100 entry after the last close, the next
    session's clock, and bars set one price at a time."""

    def __init__(self, tmp_path, **kw):
        bars, ds = history()
        self.b = FakeBroker(bars)
        self.b.clock = ny(ds[-1], 16, 10)
        kw.setdefault("dry_run", False)
        self.r = Runner(cfg(tmp_path, exit_mode="scale_out", **kw), self.b)
        self.r.tick()
        assert self.r.st.pending_entries == ["US100"]
        self.day = next_day(ds[-1])
        self.px = {s: bars[s][-2][4] for s in SYMS}     # last cash-session closes

    def at(self, h, m, day=None, **px):
        """Tick at ``h:m`` New York after a bar at the given prices
        (``US100=...``; the other symbols repeat their last price)."""
        t = ny(day or self.day, h, m)
        for s in SYMS:
            p = px.get(s.split(".")[0], self.px[s])
            self.px[s] = p
            self.b.b[s].append((t, p, p, p, p))
        self.b.clock = t
        self.r.tick()

    def enter(self):
        self.at(9, 35)
        p = self.b.pos[0]
        h = self.r.st.held["US100"]
        assert (h["exit"], h["stage"], p.sl) == ("scale_out", 0, h["stop0"])
        return p, p.price_open - h["stop0"]

    def sent(self, kind):
        return [x for x in self.b.sent if x[0] == kind]


def test_the_five_steps_on_a_winning_trade(tmp_path):
    sc = Scene(tmp_path)
    p, r = sc.enter()
    e, vol = p.price_open, p.volume
    sc.at(9, 40, US100=e + 0.9 * r)                       # under +1R: nothing
    assert sc.sent("part") == [] and sc.sent("sl") == []
    sc.at(9, 45, US100=e + r + 1)                         # bid over +1R: step 3
    assert sc.sent("part") == [("part", "US100.cash", vol / 2, "FAST4 TP1")]
    assert sc.sent("sl") == [("sl", "US100.cash", e)]     # break-even
    assert sc.b.pos[0].volume == pytest.approx(vol / 2)
    sc.at(9, 50, US100=e + 1.5 * r + 1)                   # step 4
    assert sc.sent("part")[-1] == ("part", "US100.cash", vol / 4, "FAST4 TP2")
    assert sc.sent("sl")[-1] == ("sl", "US100.cash", e + r)
    assert sc.r.st.held["US100"]["stage"] == 2
    top = e + 3 * r
    sc.at(15, 30, US100=top)                              # the session closes at +3R
    n = len(sc.b.sent)
    sc.at(16, 10)                                         # plan: no FAST-4 exit for it
    assert sc.r.st.pending_exits == []
    assert sc.r.st.held["US100"]["high_close"] == top
    sc.at(16, 11)                                         # step 5: the trail
    assert sc.b.sent[n:] == [("sl", "US100.cash", pytest.approx(top - r))]
    sc.at(16, 12)                                         # set once, not again
    assert len(sc.b.sent) == n + 1
    assert sc.sent("close") == [] and sc.b.pos[0].volume == pytest.approx(vol / 4)


def test_a_refused_stop_move_waits_five_minutes_then_retries(tmp_path):
    sc = Scene(tmp_path)
    p, r = sc.enter()
    sc.b.fail_modify = True
    sc.at(9, 40, US100=p.price_open + r + 1)
    assert len(sc.sent("part")) == 1 and len(sc.sent("sl-failed")) == 1
    sc.b.fail_modify = False
    sc.at(9, 43)                                          # inside the wait
    assert sc.sent("sl") == [] and len(sc.sent("sl-failed")) == 1
    sc.at(9, 45)
    assert sc.sent("sl") == [("sl", "US100.cash", p.price_open)]
    assert len(sc.sent("part")) == 1                      # the half went once


def test_price_under_the_due_stop_closes_the_rest(tmp_path):
    sc = Scene(tmp_path)
    p, r = sc.enter()
    sc.b.fail_modify = True                               # the break-even move fails
    sc.at(9, 40, US100=p.price_open + r + 1)
    sc.at(9, 46, US100=p.price_open - 0.2 * r)            # back under the entry
    assert sc.sent("close") == [("close", "US100.cash", pytest.approx(p.volume / 2),
                                 "FAST4 stop level")]
    assert sc.b.pos == [] and sc.r.st.held == {}


def test_nothing_is_sent_outside_the_window(tmp_path):
    sc = Scene(tmp_path)
    p, r = sc.enter()
    sc.at(17, 5, US100=p.price_open + 2 * r)              # after 17:00 New York
    assert sc.sent("part") == [] and sc.sent("sl") == []
    sat = sc.day + timedelta(days=(5 - sc.day.weekday()) % 7 or 7)
    sc.at(12, 0, day=sat)                                 # a Saturday
    assert sc.sent("part") == [] and sc.sent("sl") == []
    assert sc.r.st.held["US100"]["stage"] == 0            # not even marked


def test_a_losing_trade_ends_at_its_first_stop(tmp_path):
    sc = Scene(tmp_path)
    p, r = sc.enter()
    sc.at(10, 0, US100=p.price_open - 0.5 * r)
    assert sc.sent("part") == [] and sc.sent("sl") == [] and sc.sent("close") == []
    sc.b.pos = []                                         # the broker's stop filled
    sc.at(10, 30, US100=p.price_open - 1.1 * r)
    assert sc.r.st.held == {}                             # read as stopped out


def test_stops_at_or_over_the_entry_add_no_risk_room(tmp_path):
    """The combined-risk cap counts a stop at or over its entry as zero
    risk, never as negative risk that would widen the room for the next
    entry."""
    sc = Scene(tmp_path)
    sc.b.pos = [Position(9, "US500.cash", 10.0, 100.0, 105.0)]   # stop over entry
    sc.r.st.held["US500"] = {"ticket": 9, "entry_day": "2026-01-02",
                             "exit": "scale_out", "stop0": 90.0, "stage": 2}
    sc.r.st.day = sc.day.isoformat()                      # FTMO day already rolled
    sc.r.st.day_start_balance = 15000.0
    sc.b.balance = sc.b.equity = 14400.0                  # room: 14,400 - 14,280 = 120
    atr = sc.r.st.pending_atr["US100"]
    sc.at(9, 35)
    buys = [x for x in sc.b.sent if x[0] == "buy"]
    lpl = sc.r.cfg.atr_stop_mult * atr
    want = int(120 / lpl / 0.01 + 1e-9) * 0.01
    assert buys and buys[0][2] == pytest.approx(want)


def test_keepalive_runs_with_both_slots_full(tmp_path):
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 10, 15)
    held = [Position(5, "US500.cash", 1.0, 100, 101), Position(6, "US30.cash", 1.0, 100, 101)]
    b.pos = list(held)
    r = Runner(cfg(tmp_path, dry_run=False, exit_mode="scale_out"), b)
    r.roll_day(b.clock)
    r.st.last_fill = (b.clock - timedelta(days=26)).isoformat()
    r.keepalive(b.clock, held)
    assert [x[0] for x in b.sent] == ["buy", "close"] and b.pos == held


def test_adoption_under_scale_out(tmp_path):
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 12, 0)
    b.pos = [Position(5, "US500.cash", 1.0, 100, 90),     # first stop: managed
             Position(6, "US30.cash", 1.0, 100, 100)]     # stop at entry: unknown R
    r = Runner(cfg(tmp_path, dry_run=False, exit_mode="scale_out"), b)
    r.tick()
    assert r.st.held["US500"]["exit"] == "scale_out" and r.st.held["US500"]["stop0"] == 90
    assert "exit" not in r.st.held["US30"]                # FAST-4's exits manage it


def test_a_position_keeps_the_exit_rule_it_was_opened_with(tmp_path):
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 16, 10)
    b.pos = [Position(5, "US500.cash", 1.0, 100, 90), Position(6, "US30.cash", 1.0, 100, 90)]
    r = Runner(cfg(tmp_path, dry_run=False, exit_mode="scale_out"), b)
    r.st.held = {"US500": {"ticket": 5, "entry_day": ds[-12].isoformat()},   # FAST-4's
                 "US30": {"ticket": 6, "entry_day": ds[-12].isoformat(),
                          "exit": "scale_out", "stop0": 90, "stage": 0}}
    day, p = r.compute_plan(b.clock)
    assert "US500" in p.exits                             # 12 sessions: FAST-4's time exit
    assert "US30" not in p.exits                          # the 5 steps manage it
    assert set(r.highs) == {"US30"}


def test_dry_run_sends_nothing_and_records_no_step(tmp_path):
    """A position held from a live run, then a dry run: nothing is sent and
    no step is recorded as done (so a later live run still sends it)."""
    sc = Scene(tmp_path)
    p, r = sc.enter()
    sc.r.cfg.dry_run = True
    before = dict(sc.r.st.held["US100"])
    n = len(sc.b.sent)
    sc.at(9, 40, US100=p.price_open + 2 * r)              # over both targets
    assert sc.b.sent[n:] == [] and sc.r.st.held["US100"] == before
    sc.r.cfg.dry_run = False
    sc.at(9, 41)
    assert sc.sent("part") and sc.sent("sl")              # done for real now


class RoundingBroker(FakeBroker):
    """MT5 rounds a stop to the tick: this one stores it a tick under."""

    def modify_sl(self, position, sl, magic):
        return super().modify_sl(position, sl - 0.25, magic)


def test_a_stop_rounded_under_the_floor_is_not_resent(tmp_path):
    sc = Scene(tmp_path)
    sc.b.__class__ = RoundingBroker
    p, r = sc.enter()
    sc.at(9, 40, US100=p.price_open + r + 1)
    assert sc.b.pos[0].sl == pytest.approx(p.price_open - 0.25)   # under the floor
    for m in range(41, 50):
        sc.at(9, m)
    assert len(sc.sent("sl")) == 1                        # sl_set: sent once


def test_a_failed_part_close_is_redone_from_the_broker_volume(tmp_path):
    sc = Scene(tmp_path)
    p, r = sc.enter()
    vol = p.volume
    sc.b.fail_close = True
    sc.at(9, 40, US100=p.price_open + r + 1)
    assert sc.sent("close-failed") and sc.sent("part") == []
    assert sc.sent("sl") == [("sl", "US100.cash", p.price_open)]  # the stop still moved
    sc.b.fail_close = False
    sc.at(9, 42)                                          # inside the 5-minute wait
    assert sc.sent("part") == []
    sc.at(9, 45)
    assert sc.sent("part") == [("part", "US100.cash", vol / 2, "FAST4 TP1")]


class FilledThenRaised(FakeBroker):
    """The part close fills at the broker, then the reply is lost."""

    def close(self, position, magic, comment, volume=None):
        f = super().close(position, magic, comment, volume)
        if volume is not None:
            raise ConnectionError("terminal went away")
        return f


def test_a_part_close_that_filled_but_raised_is_not_sold_twice(tmp_path):
    sc = Scene(tmp_path)
    sc.b.__class__ = FilledThenRaised
    p, r = sc.enter()
    sc.at(9, 40, US100=p.price_open + r + 1)
    assert len(sc.sent("part")) == 1 and sc.b.pos[0].volume == pytest.approx(p.volume / 2)
    sc.at(9, 46)                                          # after the wait
    assert len(sc.sent("part")) == 1                      # the broker shows it done


def test_the_first_volume_follows_the_position_until_the_first_target(tmp_path):
    sc = Scene(tmp_path)
    p, r = sc.enter()
    sc.at(9, 40)
    sc.b.pos = [Position(p.ticket, p.symbol, 20.0, p.price_open, p.sl)]   # cut to 20
    sc.at(9, 45)
    assert sc.r.st.held["US100"]["vol0"] == 20.0
    sc.at(9, 50, US100=p.price_open + r + 1)
    assert sc.sent("part") == [("part", "US100.cash", 10.0, "FAST4 TP1")]


def test_the_stop_never_moves_down(tmp_path):
    sc = Scene(tmp_path)
    p, r = sc.enter()
    sc.at(9, 40, US100=p.price_open + 1.5 * r + 1)        # both targets: stop at +1R
    assert sc.sent("sl") == [("sl", "US100.cash", p.price_open + r)]
    sc.r.st.held["US100"]["high_close"] = p.price_open + 1.2 * r   # trail level under it
    sc.at(9, 45)
    sc.b.pos = [Position(p.ticket, p.symbol, sc.b.pos[0].volume, p.price_open,
                         p.price_open + 2 * r)]           # raised by hand
    sc.r.st.held["US100"]["high_close"] = p.price_open + 2.5 * r   # trail = +1.5R < +2R
    sc.at(9, 50, US100=p.price_open + 3 * r)
    assert sc.sent("sl") == [("sl", "US100.cash", p.price_open + r)]


def test_the_guard_flattens_before_any_step(tmp_path):
    sc = Scene(tmp_path)
    p, r = sc.enter()
    sc.b.equity = 14270.0                                 # within 0.2% of the daily line
    sc.at(9, 40, US100=p.price_open + r + 1)
    assert sc.sent("part") == [] and sc.sent("sl") == []
    assert sc.sent("close") and sc.b.pos == []


def test_window_opens_at_0931(tmp_path):
    sc = Scene(tmp_path)
    p, r = sc.enter()
    day2 = next_day(sc.day)
    sc.at(9, 30, day=day2, US100=p.price_open + r + 1)
    assert sc.sent("part") == []
    sc.at(9, 31, day=day2)
    assert len(sc.sent("part")) == 1


def test_window_closes_at_1700(tmp_path):
    sc = Scene(tmp_path)
    p, r = sc.enter()
    sc.at(16, 59, US100=p.price_open + 0.5 * r)
    sc.at(17, 0, US100=p.price_open + r + 1)
    assert sc.sent("part") == [] and sc.r.st.held["US100"]["stage"] == 0


def test_a_late_plan_still_raises_the_trail(tmp_path):
    """The bot was down from the close until 18:00: the plan made then
    raises the trail at once, not the next morning."""
    sc = Scene(tmp_path)
    p, r = sc.enter()
    sc.at(9, 40, US100=p.price_open + 1.5 * r + 1)        # steps 3 and 4
    top = p.price_open + 3 * r
    sc.at(15, 30, US100=top)
    n = len(sc.b.sent)
    sc.at(18, 0)
    assert sc.b.sent[n:] == [("sl", "US100.cash", pytest.approx(top - r))]


class NoQuote(FakeBroker):
    def quote(self, symbol):
        if symbol == "US500.cash":
            raise RuntimeError("no quote for US500.cash")
        return super().quote(symbol)


def test_one_symbol_without_a_quote_stops_nothing_else(tmp_path):
    sc = Scene(tmp_path)
    p, r = sc.enter()
    sc.b.__class__ = NoQuote
    sc.b.pos.append(Position(9, "US500.cash", 1.0, 100.0, 90.0))
    sc.r.st.held["US500"] = {"ticket": 9, "entry_day": sc.day.isoformat(),
                             "exit": "scale_out", "stop0": 90.0, "stage": 0}
    sc.at(9, 40, US100=p.price_open + r + 1)              # US500 raises, US100 goes on
    assert len(sc.sent("part")) == 1 and sc.sent("part")[0][1] == "US100.cash"
    sc.at(16, 10)                                         # and the plan is still made
    assert sc.r.st.plan_checked == sc.day.isoformat()


def test_a_failed_target_close_is_retried_every_tick(tmp_path):
    """The back-off never slows a close that locks the target in."""
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 12, 0)
    b.pos = [Position(5, "US500.cash", 1.0, 100, 90)]
    r = Runner(cfg(tmp_path, dry_run=False), b)
    r.st.trading_days = ["a", "b", "c", "d"]
    b.balance = b.equity = 16600                           # over the 10% target
    b.fail_close = True
    for m in range(4):
        b.clock = ny(ds[-1], 12, m)
        r.tick()
    assert r.st.target_locked
    assert len([x for x in b.sent if x[0] == "close-failed"]) == 4   # one per tick
    b.fail_close = False
    b.clock = ny(ds[-1], 12, 4)
    r.tick()
    assert b.pos == []


def test_a_failed_close_after_a_guard_is_retried_every_tick(tmp_path):
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 12, 0)
    b.pos = [Position(5, "US500.cash", 1.0, 100, 90)]
    r = Runner(cfg(tmp_path, dry_run=False), b)
    b.fail_close = True
    b.equity = 14270.0                                     # trips the daily guard
    r.tick()
    b.equity = 14600.0                                     # recovers over the buffer
    for m in range(1, 4):
        b.clock = ny(ds[-1], 12, m)
        r.tick()
    assert r.st.blocked_until
    assert len([x for x in b.sent if x[0] == "close-failed"]) == 4   # one per tick


def test_a_guard_close_stays_on_every_tick_past_the_ftmo_day(tmp_path):
    """The guard's block ends at Prague midnight; a close it queued that is
    still failing then keeps retrying every tick."""
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 12, 0)
    b.pos = [Position(5, "US500.cash", 1.0, 100, 90)]
    r = Runner(cfg(tmp_path, dry_run=False), b)
    b.fail_close = True
    b.equity = 14270.0                                     # trips the daily guard
    r.tick()
    b.equity = 14600.0
    for h, m in ((17, 58), (17, 59), (18, 0), (18, 1), (18, 2)):   # Prague midnight at 18:00
        b.clock = ny(ds[-1], h, m)
        r.tick()
    assert not r.st.blocked_until                          # the block has ended
    assert len([x for x in b.sent if x[0] == "close-failed"]) == 6   # still one per tick


def test_a_queued_close_backs_off_to_every_15_minutes(tmp_path):
    bars, ds = history()
    b = FakeBroker(bars)
    b.clock = ny(ds[-1], 11, 0)
    b.pos = [Position(5, "US500.cash", 1.0, 100, 90)]
    r = Runner(cfg(tmp_path, dry_run=False), b)
    r.st.held = {"US500": {"ticket": 5, "entry_day": ds[-1].isoformat()}}
    r.st.to_close = [5]
    b.fail_close = True
    for m in range(21):                                   # 11:00 ... 11:20
        b.clock = ny(ds[-1], 11, m)
        r.tick()
    assert len([x for x in b.sent if x[0] == "close-failed"]) == 5   # 0, 1, 3, 7, 15
    b.fail_close = False
    b.clock = ny(ds[-1], 11, 30)
    r.tick()
    assert b.pos == [] and r.st.to_close == []


# ------------------------------------------------------ broker adapters

class OrderMT5:
    TRADE_RETCODE_DONE = 10009
    ORDER_TYPE_BUY, ORDER_TYPE_SELL, TRADE_ACTION_DEAL, TRADE_ACTION_SLTP = 0, 1, 1, 6
    ORDER_TIME_GTC, ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 0, 1, 2

    def __init__(self):
        self.orders, self.login = [], 77

    def initialize(self, *a):
        return True

    def last_error(self):
        return (1, "ok")

    def account_info(self):
        return SimpleNamespace(login=self.login)

    def symbol_info(self, s):
        return SimpleNamespace(filling_mode=1, trade_tick_size=0.25, digits=2)

    def symbol_info_tick(self, s):
        return SimpleNamespace(bid=100.0, ask=100.5)

    def order_send(self, req):
        self.orders.append(req)
        return SimpleNamespace(retcode=10009, price=100.0, order=1, comment="done")


def test_mt5_part_close_and_stop_move_requests(monkeypatch):
    fake = OrderMT5()
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    from ftmo_bot.broker_mt5 import MT5Broker
    b = MT5Broker(login=77)
    pos = Position(42, "US100.cash", 0.33, 90.0, 80.0)
    assert b.close(pos, 404040, "FAST4 TP1", volume=0.17).ok
    req = fake.orders[-1]
    assert (req["volume"], req["position"], req["type"]) == (0.17, 42, fake.ORDER_TYPE_SELL)
    assert b.close(pos, 404040, "FAST4 exit").ok
    assert fake.orders[-1]["volume"] == 0.33                 # None: the whole position
    assert b.modify_sl(pos, 90.13, 404040).ok
    req = fake.orders[-1]
    assert (req["action"], req["position"], req["sl"], req["tp"]) == (
        fake.TRADE_ACTION_SLTP, 42, 90.25, 0.0)             # rounded to the tick
    fake.login = 78                                          # another account: refused
    assert not b.modify_sl(pos, 95.0, 404040).ok and len(fake.orders) == 3


def test_sim_broker_part_close_and_stop_move():
    from datetime import datetime, timezone
    t0 = datetime(2026, 10, 5, 14, 0, tzinfo=timezone.utc)
    bars = {"QQQ": [(t0, 100.0, 100.0, 100.0, 100.0),
                    (t0 + timedelta(minutes=30), 110.0, 110.0, 110.0, 110.0),
                    (t0 + timedelta(minutes=60), 110.0, 110.0, 104.0, 105.0)]}
    sim = SimBroker(bars, half_spread=0.0)
    sim.clock = t0 + timedelta(minutes=31)
    sim.pos = [Position(1, "QQQ", 10.0, 100.0, 90.0)]
    sim.advance_to(t0 + timedelta(minutes=60))
    f = sim.close(sim.pos[0], 0, "FAST4 TP1", volume=4.0)
    assert f.ok and sim.pos[0].volume == 6.0 and sim.balance == pytest.approx(15040.0)
    assert not sim.modify_sl(sim.pos[0], 111.0, 0).ok        # over the price: refused
    assert sim.modify_sl(sim.pos[0], 105.0, 0).ok and sim.pos[0].sl == 105.0
    sim.advance_to(t0 + timedelta(minutes=95))               # the next bar's low 104 hits it
    assert sim.pos == [] and sim.balance == pytest.approx(15040.0 + 6 * 5.0)
