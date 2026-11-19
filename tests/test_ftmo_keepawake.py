"""ftmo_bot/keepawake.py: the bot keeps a Windows PC awake while it runs
(plugged in: no sleep on its own, the lid does nothing), keeps its window
from pausing on a click, and says so in the log when it stood still.

Windows itself is not here: its three calls (``_set_state``, ``_ac_line``,
``_powercfg``) and the console call are replaced by stand-ins."""

from __future__ import annotations

import logging
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_ftmo_bot import FakeBroker, cfg, history  # noqa: E402
from test_ftmo_readiness import MainBroker, cli_config, seeded  # noqa: E402

from ftmo_bot import keepawake, runner as runner_mod  # noqa: E402
from ftmo_bot.config import FtmoConfig, load  # noqa: E402
from ftmo_bot.keepawake import Power  # noqa: E402
from ftmo_bot.runner import Runner  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent

ENGLISH = """Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)
  Subgroup GUID: 238c9fa8-0aad-41ed-83f4-97be242c8f20  (Sleep)
    GUID Alias: SUB_SLEEP
    Power Setting GUID: 29f6c1db-86da-48c5-9fdb-f2b67b1f44da  (Sleep after)
      GUID Alias: STANDBYIDLE
      Minimum Possible Setting: 0x00000000
      Maximum Possible Setting: 0xffffffff
      Possible Settings increment: 0x00000001
      Possible Settings units: Seconds
    Current AC Power Setting Index: 0x{ac:08x}
    Current DC Power Setting Index: 0x{dc:08x}
"""
FRENCH = """GUID du mode de gestion de l'alimentation : 381b4222-f694-41f0-9685-ff5bb260df2e  (Utilisation normale)
  GUID du sous-groupe : 4f971e89-eebd-4455-a8de-9e59040e7347  (Boutons d'alimentation et capot)
    Alias GUID : SUB_BUTTONS
    GUID du parametre d'alimentation : 5ca83367-6e45-459f-a27b-476b1d01c936  (Action de fermeture du capot)
      Alias GUID : LIDACTION
      Index de parametre possible : 000
      Nom convivial de parametre possible : Ne rien faire
      Index de parametre possible : 001
      Nom convivial de parametre possible : Veille
    Index du parametre actuel en courant alternatif : 0x{ac:08x}
    Index du parametre actuel en courant continu : 0x{dc:08x}
"""


class FakeWindows:
    """Windows' power plan and wake request, as far as the bot touches them."""

    def __init__(self, sleep=1800, hibernate=10800, lid=1, line=1, refuse=()):
        self.values = {"STANDBYIDLE": sleep, "HIBERNATEIDLE": hibernate, "LIDACTION": lid}
        self.battery = {"STANDBYIDLE": 900, "HIBERNATEIDLE": 3600, "LIDACTION": 1}
        self.line, self.refuse = line, set(refuse)
        self.calls, self.states = [], []
        self.state_before = keepawake.ES_CONTINUOUS

    def powercfg(self, *args):
        self.calls.append(args)
        if args[0] == "/query":
            assert args[1] == "SCHEME_CURRENT"
            value = self.values[args[3]]
            if value is None:                    # e.g. a PC without hibernation
                return 1, "The power scheme, subgroup or setting specified does not exist."
            text = FRENCH if args[3] == "LIDACTION" else ENGLISH
            return 0, text.format(ac=value, dc=self.battery[args[3]])
        if args[0] == "/change":
            key = {"standby-timeout-ac": "STANDBYIDLE",
                   "hibernate-timeout-ac": "HIBERNATEIDLE"}[args[1]]
            if key in self.refuse or self.values[key] is None:
                return 1, "refused"
            self.values[key] = int(args[2]) * 60
            return 0, ""
        if args[0] == "/setacvalueindex":
            assert args[1:3] == ("SCHEME_CURRENT", "SUB_BUTTONS")
            if args[3] in self.refuse:
                return 1, "refused"
            self.values[args[3]] = int(args[4])
            return 0, ""
        assert args == ("/setactive", "SCHEME_CURRENT"), args
        return 0, ""

    def set_state(self, flags):
        self.states.append(flags)
        return self.state_before

    def sets(self):
        return [c for c in self.calls if c[0] != "/query"]


@pytest.fixture
def windows(monkeypatch):
    def make(**kw):
        w = FakeWindows(**kw)
        monkeypatch.setattr(keepawake, "_on_windows", lambda: True)
        monkeypatch.setattr(keepawake, "_powercfg", w.powercfg)
        monkeypatch.setattr(keepawake, "_ac_line", lambda: w.line)
        monkeypatch.setattr(keepawake, "_set_state", w.set_state)
        monkeypatch.setattr(keepawake, "_console_mode", lambda new=None: None)
        return w
    return make


# ------------------------------------------------------------ not on Windows

def test_anywhere_but_windows_nothing_is_touched(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a Windows call was made")
    for name in ("_set_state", "_ac_line", "_powercfg", "_console_mode"):
        monkeypatch.setattr(keepawake, name, boom)
    assert not keepawake._on_windows()           # the tests run on Linux
    assert keepawake.hold() is False and keepawake.no_quick_edit() is None
    assert keepawake.read() is None and keepawake.apply() is None
    keepawake.release()
    keepawake.restore_console(0x1F7)
    assert keepawake.report(None) == [(True, "power: not Windows, nothing to set")]
    assert keepawake.guard_lines(False, False) == [(True, "awake: not Windows, nothing to hold")]


# ----------------------------------------------------------- the wake request

def test_the_wake_request_is_continuous_and_system_required(windows):
    w = windows()
    assert keepawake.hold() is True
    assert w.states == [0x80000001]              # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    keepawake.release()
    assert w.states == [0x80000001, 0x80000000]  # ES_CONTINUOUS alone: given back


def test_a_refused_or_failing_wake_request_is_reported_not_raised(windows, monkeypatch, caplog):
    w = windows()
    w.state_before = 0                           # Windows' answer for "failed"
    assert keepawake.hold() is False

    def broken(flags):
        raise OSError("no such entry point")
    monkeypatch.setattr(keepawake, "_set_state", broken)
    with caplog.at_level(logging.WARNING, logger="ftmo_bot"):
        assert keepawake.hold() is False
    assert "could not ask Windows to stay awake (no such entry point)" in caplog.text
    keepawake.release()                          # stopping: a failure here is swallowed
    assert keepawake.guard_lines(False, False) == [
        (False, "awake: Windows did not take the stay-awake request; if this PC sleeps, "
                "the bot stops until it wakes")]
    lines = keepawake.guard_lines(True, True)
    assert [fine for fine, _ in lines] == [True, True]
    assert "will not go to sleep on its own" in lines[0][1] and "click" in lines[1][1]


# ---------------------------------------------------------- the console window

def test_click_to_select_is_switched_off_and_given_back(windows, monkeypatch):
    windows()
    modes = []

    def console(new=None, before=0x01F7):        # QUICK_EDIT (0x40) is on
        modes.append(new)
        return before
    monkeypatch.setattr(keepawake, "_console_mode", console)
    assert keepawake.no_quick_edit() == 0x01F7
    assert modes == [None, 0x01B7]               # read, then the same mode without 0x40
    assert modes[1] & keepawake.EXTENDED_FLAGS and not modes[1] & keepawake.QUICK_EDIT
    keepawake.restore_console(0x01F7)
    assert modes[-1] == 0x01F7
    keepawake.restore_console(None)              # nothing was changed: nothing to restore
    assert len(modes) == 3


@pytest.mark.parametrize("before", [None, 0x0187])     # no console; already off
def test_a_window_without_click_to_select_is_left_alone(windows, monkeypatch, before):
    windows()
    modes = []

    def console(new=None):
        modes.append(new)
        return before
    monkeypatch.setattr(keepawake, "_console_mode", console)
    assert keepawake.no_quick_edit() is None and modes == [None]


def test_a_failing_console_call_is_reported_not_raised(windows, monkeypatch, caplog):
    windows()

    def broken(new=None):
        raise OSError("access denied")
    monkeypatch.setattr(keepawake, "_console_mode", broken)
    with caplog.at_level(logging.WARNING, logger="ftmo_bot"):
        assert keepawake.no_quick_edit() is None
    assert "could not switch off click-to-select" in caplog.text
    keepawake.restore_console(0x01F7)            # swallowed


# ------------------------------------------------------------ the power settings

def test_the_plugged_in_value_is_read_in_any_language(windows):
    w = windows(sleep=1800, hibernate=0, lid=2)
    assert keepawake._index(*keepawake.SLEEP_AFTER) == 1800      # English text
    assert keepawake._index(*keepawake.LID_ACTION) == 2          # French text
    assert w.battery["STANDBYIDLE"] == 900                       # not the battery value
    assert keepawake.read() == Power(True, 1800, 0, 2)
    assert w.sets() == []                                        # reading sets nothing


@pytest.mark.parametrize("answer", [(1, ENGLISH.format(ac=0, dc=0)), (0, "nothing useful"),
                                    (0, "one number only: 0x00000000")])
def test_an_answer_that_cannot_be_read_is_none(windows, monkeypatch, answer):
    windows()
    monkeypatch.setattr(keepawake, "_powercfg", lambda *a: answer)
    assert keepawake._index(*keepawake.SLEEP_AFTER) is None

    def broken(*a):
        raise FileNotFoundError("powercfg")
    monkeypatch.setattr(keepawake, "_powercfg", broken)
    assert keepawake._index(*keepawake.SLEEP_AFTER) is None
    monkeypatch.setattr(keepawake, "_ac_line", broken)
    assert keepawake.read() == Power(None, None, None, None)


@pytest.mark.parametrize("line,plugged", [(1, True), (0, False), (255, None), (7, None)])
def test_plugged_in_or_on_battery(windows, line, plugged):
    windows(line=line)
    assert keepawake.read().plugged is plugged


def test_apply_sets_only_the_plugged_in_values_and_reads_them_back(windows):
    w = windows(sleep=1800, hibernate=10800, lid=1)
    assert keepawake.apply() == Power(True, 0, 0, 0)
    assert w.sets() == [("/change", "standby-timeout-ac", "0"),
                        ("/change", "hibernate-timeout-ac", "0"),
                        ("/setacvalueindex", "SCHEME_CURRENT", "SUB_BUTTONS", "LIDACTION", "0"),
                        ("/setactive", "SCHEME_CURRENT")]
    assert not any("dc" in arg.lower() for call in w.sets() for arg in call)
    assert w.battery == {"STANDBYIDLE": 900, "HIBERNATEIDLE": 3600, "LIDACTION": 1}
    assert keepawake.apply().stays_awake()       # a second start changes nothing


def test_a_pc_without_hibernation_is_fine(windows):
    w = windows(hibernate=None)
    power = keepawake.apply()
    assert power == Power(True, 0, None, 0) and power.stays_awake()
    assert keepawake.report(power)[0][0] is True
    assert len(w.sets()) == 4                    # the refused command did not stop the rest


def test_what_windows_refuses_is_reported_from_what_is_read_back(windows):
    windows(refuse={"LIDACTION", "STANDBYIDLE"})
    power = keepawake.apply()
    assert power == Power(True, 1800, 0, 1) and not power.stays_awake()
    lines = keepawake.report(power)
    assert [fine for fine, _ in lines] == [False, False]
    assert "still goes to sleep after 30 min idle" in lines[0][1]
    assert "closing the lid still puts the PC to sleep" in lines[1][1]
    assert all("Choose what closing the lid does" in line for _, line in lines)


@pytest.mark.parametrize("power,fine,needles", [
    (Power(True, 0, 0, 0), True, ["plugged in; while plugged in this PC never sleeps",
                                  "closing the lid does nothing"]),
    (Power(False, 0, 0, 0), False, ["ON BATTERY", "Plug it in"]),
    (Power(None, 0, 0, 0), False, ["cannot tell whether the PC is plugged in"]),
    (Power(True, None, 0, 0), False, ["could not be read"]),
    (Power(True, 0, 0, None), False, ["could not be read"]),
    (Power(True, 0, 7200, 0), False, ["still hibernates after 120 min idle"]),
    (Power(True, 0, 0, 2), False, ["closing the lid still hibernates the PC"]),
    (Power(True, 0, 0, 3), False, ["closing the lid still shuts the PC down"]),
    (Power(True, 20, 0, 9), False, ["after 1 min idle", "closing the lid still stops the PC"]),
])
def test_the_report_says_what_is_wrong(power, fine, needles):
    assert power.stays_awake() is fine
    lines = keepawake.report(power)
    assert all(ok is fine for ok, _ in lines) and lines
    text = "\n".join(line for _, line in lines)
    for needle in needles:
        assert needle in text, (needle, text)
    assert all(line.startswith("power: ") for _, line in lines)


def test_on_battery_with_everything_else_wrong_every_line_is_there():
    lines = keepawake.report(Power(False, 600, 3600, 1))
    assert len(lines) == 4 and not any(fine for fine, _ in lines)


# ----------------------------------------------------------- the loop stood still

T0 = datetime(2026, 11, 11, 23, 5, tzinfo=timezone.utc)      # 18:05 New York


@pytest.mark.parametrize("seconds,frozen", [(60, False), (61, False), (299, False),
                                            (300, False), (301, True), (14040, True),
                                            (-3600, False)])     # the clock was set back
def test_a_gap_longer_than_the_pause_and_the_slack_is_a_stall(seconds, frozen):
    gap = keepawake.frozen_for(T0, T0 + timedelta(seconds=seconds), every=60)
    assert (gap == timedelta(seconds=seconds)) if frozen else gap is None
    assert keepawake.frozen_for(None, T0, every=60) is None      # the first tick


def test_the_stall_line_gives_the_span_in_new_york_time():
    text = keepawake.frozen_text(T0, timedelta(hours=3, minutes=54, seconds=20))
    assert text.startswith("the bot stood still for 3 h 54 min, from 18:05 to 21:59 New York")
    assert "nothing was planned, opened, managed or closed" in text
    assert "only its stop at the broker" in text
    short = keepawake.frozen_text(T0, timedelta(minutes=12))
    assert short.startswith("the bot stood still for 12 min, from 18:05 to 18:17 New York")
    night = keepawake.frozen_text(T0, timedelta(hours=14))       # across midnight: with dates
    assert "for 14 h 0 min, from 2026-11-11 18:05 to 2026-11-12 08:05 New York" in night


# ------------------------------------------------------------------ the bot's loop

class Stop(BaseException):
    """Ends the loop from a test, the way Ctrl+C does."""


def looped(tmp_path, monkeypatch, clock, ticks=None, **kw):
    """Run the real loop over a scripted clock; the tick is a stand-in that
    stops the loop when the clock runs out."""
    bars, _ = history()
    r = Runner(cfg(tmp_path, **kw), FakeBroker(bars))
    times = iter(clock)
    calls = []

    def now():
        try:
            return next(times)
        except StopIteration:
            raise Stop()

    def tick(self):
        calls.append(len(calls))
        if ticks:
            ticks(self, len(calls))
    monkeypatch.setattr(runner_mod, "_utcnow", now)
    monkeypatch.setattr(runner_mod._time, "sleep", lambda s: None)
    monkeypatch.setattr(Runner, "tick", tick)
    return r, calls


def test_the_loop_holds_the_guards_and_gives_them_back_when_it_stops(
        tmp_path, monkeypatch, windows, caplog):
    w = windows()
    modes = []

    def console(new=None):
        modes.append(new)
        return 0x01F7
    monkeypatch.setattr(keepawake, "_console_mode", console)
    r, calls = looped(tmp_path, monkeypatch, [T0, T0 + timedelta(seconds=61)])
    with caplog.at_level(logging.INFO, logger="ftmo_bot"), pytest.raises(Stop):
        r.run()
    assert len(calls) == 2
    assert w.states == [0x80000001, 0x80000000]                  # held, then given back
    assert modes == [None, 0x01B7, 0x01F7]                       # click-to-select off, then back
    assert "awake: Windows will not go to sleep on its own while the bot runs" in caplog.text
    assert "a click in this window no longer pauses the bot" in caplog.text
    assert "stood still" not in caplog.text
    assert w.calls == []                                         # the loop sets no power plan


def test_the_loop_says_when_it_stood_still(tmp_path, monkeypatch, windows, caplog):
    windows()
    clock = [T0, T0 + timedelta(seconds=61), T0 + timedelta(hours=3, minutes=55),
             T0 + timedelta(hours=3, minutes=56)]
    r, calls = looped(tmp_path, monkeypatch, clock)
    with caplog.at_level(logging.INFO, logger="ftmo_bot"), pytest.raises(Stop):
        r.run()
    stalls = [rec for rec in caplog.records if "stood still" in rec.getMessage()]
    assert len(calls) == 4 and len(stalls) == 1 and stalls[0].levelno == logging.WARNING
    assert "for 3 h 54 min, from 18:06 to 22:00 New York" in stalls[0].getMessage()


def test_a_tick_that_hangs_is_a_stall_too(tmp_path, monkeypatch, windows, caplog):
    """Measured from start to start: the time a tick itself took counts."""
    windows()
    r, calls = looped(tmp_path, monkeypatch, [T0, T0 + timedelta(minutes=30)])
    with caplog.at_level(logging.WARNING, logger="ftmo_bot"), pytest.raises(Stop):
        r.run()
    assert "the bot stood still for 30 min, from 18:05 to 18:35 New York" in caplog.text


def test_a_failing_tick_does_not_stop_the_loop_or_drop_the_guards(
        tmp_path, monkeypatch, windows, caplog):
    w = windows()

    def ticks(self, n):
        if n == 1:
            raise RuntimeError("terminal gone")
    r, calls = looped(tmp_path, monkeypatch, [T0, T0 + timedelta(seconds=60),
                                              T0 + timedelta(seconds=120)], ticks)
    with caplog.at_level(logging.INFO, logger="ftmo_bot"), pytest.raises(Stop):
        r.run()
    assert len(calls) == 3 and "tick failed" in caplog.text
    assert w.states == [0x80000001, 0x80000000]


def test_a_failing_stall_check_does_not_stop_the_loop(tmp_path, monkeypatch, windows, caplog):
    w = windows()

    def broken(last, gap):
        raise RuntimeError("no time zone data")
    monkeypatch.setattr(keepawake, "frozen_text", broken)
    r, calls = looped(tmp_path, monkeypatch, [T0, T0 + timedelta(hours=1),
                                              T0 + timedelta(hours=1, seconds=60)])
    with caplog.at_level(logging.INFO, logger="ftmo_bot"), pytest.raises(Stop):
        r.run()
    assert len(calls) == 3
    failed = [rec for rec in caplog.records if rec.getMessage() == "stall check failed"]
    assert len(failed) == 1                      # once, for the one stall: not every tick
    assert w.states == [0x80000001, 0x80000000]


def test_a_stop_while_the_guards_are_taken_still_gives_them_back(tmp_path, monkeypatch,
                                                                 windows):
    w = windows()

    def interrupted():
        raise Stop()                             # Ctrl+C right after the wake request
    monkeypatch.setattr(keepawake, "no_quick_edit", interrupted)
    r, calls = looped(tmp_path, monkeypatch, [T0])
    with pytest.raises(Stop):
        r.run()
    assert calls == [] and w.states == [0x80000001, 0x80000000]


def test_a_halt_ends_the_loop_and_gives_the_guards_back(tmp_path, monkeypatch, windows):
    w = windows()

    def ticks(self, n):
        self.st.halted = "max loss"
    r, calls = looped(tmp_path, monkeypatch, [T0, T0 + timedelta(seconds=60)], ticks)
    r.run()                                                      # returns: flat and halted
    assert len(calls) == 1 and w.states == [0x80000001, 0x80000000]


def test_keep_awake_false_leaves_windows_alone(tmp_path, monkeypatch, windows, caplog):
    w = windows()

    def console(new=None):
        raise AssertionError("the console was touched")
    monkeypatch.setattr(keepawake, "_console_mode", console)
    r, calls = looped(tmp_path, monkeypatch, [T0, T0 + timedelta(hours=2)], keep_awake=False)
    with caplog.at_level(logging.INFO, logger="ftmo_bot"), pytest.raises(Stop):
        r.run()
    assert len(calls) == 2 and w.states == [] and w.calls == []
    assert "awake:" not in caplog.text
    assert "stood still for 2 h 0 min" in caplog.text            # the stall check stays on


# ------------------------------------------------------------ the config and CLI

def test_keep_awake_is_on_by_default_and_in_both_configs(tmp_path):
    assert FtmoConfig().keep_awake is True
    for name in ("config.trial.yaml", "config.example.yaml"):
        assert load(ROOT / "deploy/ftmo" / name).keep_awake is True
        text = (ROOT / "deploy/ftmo" / name).read_text(encoding="utf-8")
        assert "\nkeep_awake: true " in text
    p = tmp_path / "c.yaml"
    p.write_text("keep_awake: false\n", encoding="utf-8")
    assert load(p).keep_awake is False
    p.write_text("keep_awake: 0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="keep_awake"):
        load(p)


@pytest.fixture
def started(monkeypatch):
    """Runner.run replaced by a recorder (the real one never returns)."""
    calls = []
    monkeypatch.setattr(Runner, "run", lambda self: calls.append(self.cfg.dry_run))
    return calls


def test_run_sets_the_power_plan_before_the_loop(tmp_path, monkeypatch, windows, started,
                                                 caplog):
    from ftmo_bot import __main__ as cli
    w = windows(sleep=1800, hibernate=10800, lid=1)
    seeded(tmp_path, monkeypatch)
    with caplog.at_level(logging.INFO, logger="ftmo_bot"):
        assert cli.main(["run", "--config", cli_config(tmp_path, False), "--execute"]) == 0
    assert started == [False] and len(w.sets()) == 4
    assert w.values == {"STANDBYIDLE": 0, "HIBERNATEIDLE": 0, "LIDACTION": 0}
    assert ("power: plugged in; while plugged in this PC never sleeps on its own, and "
            "closing the lid does nothing") in caplog.text
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_run_on_battery_warns_and_still_starts(tmp_path, monkeypatch, windows, started,
                                               caplog):
    from ftmo_bot import __main__ as cli
    windows(line=0)
    seeded(tmp_path, monkeypatch)
    with caplog.at_level(logging.INFO, logger="ftmo_bot"):
        assert cli.main(["run", "--config", cli_config(tmp_path, False), "--execute"]) == 0
    assert started == [False]
    warned = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warned) == 1 and "ON BATTERY" in warned[0]


def test_a_power_plan_that_cannot_be_set_or_read_never_stops_a_start(
        tmp_path, monkeypatch, windows, started, caplog, capsys):
    from ftmo_bot import __main__ as cli
    windows()
    seeded(tmp_path, monkeypatch)

    def broken(*a):
        raise OSError("policy forbids it")
    monkeypatch.setattr(keepawake, "apply", broken)
    monkeypatch.setattr(keepawake, "read", broken)
    with caplog.at_level(logging.INFO, logger="ftmo_bot"):
        assert cli.main(["run", "--config", cli_config(tmp_path, False), "--execute"]) == 0
    assert started == [False]                    # the bot started all the same
    warned = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warned) == 1 and "could not be set (policy forbids it)" in warned[0]
    capsys.readouterr()
    assert cli.main(["preflight", "--config", cli_config(tmp_path, False)]) == 0
    out = capsys.readouterr().out
    assert "WARN power: the sleep and lid settings could not be read (policy forbids it)" in out
    assert out.count("PASS ") == 4               # the other checks ran


def test_run_with_keep_awake_false_sets_nothing(tmp_path, monkeypatch, windows, started,
                                                caplog):
    from ftmo_bot import __main__ as cli
    w = windows()
    seeded(tmp_path, monkeypatch)
    config = cli_config(tmp_path, False, extra="keep_awake: false\n")
    with caplog.at_level(logging.INFO, logger="ftmo_bot"):
        assert cli.main(["run", "--config", config, "--execute"]) == 0
    assert started == [False] and w.calls == [] and w.states == []
    assert "keep_awake is false" in caplog.text


@pytest.mark.parametrize("command", ["flat", "selftest", "plan"])
def test_the_short_commands_set_no_power_plan(tmp_path, monkeypatch, windows, command):
    from ftmo_bot import __main__ as cli
    w = windows()
    seeded(tmp_path, monkeypatch)
    cli.main([command, "--config", cli_config(tmp_path, True)])
    assert w.calls == [] and w.states == []


def test_preflight_reads_the_power_plan_and_changes_nothing(tmp_path, monkeypatch, windows,
                                                            capsys):
    from ftmo_bot import __main__ as cli
    w = windows(sleep=1800, hibernate=0, lid=1)
    seeded(tmp_path, monkeypatch)
    assert cli.main(["preflight", "--config", cli_config(tmp_path, False)]) == 0
    out = capsys.readouterr().out
    assert "WARN power: while plugged in the PC still goes to sleep after 30 min idle" in out
    assert "WARN power: while plugged in, closing the lid still puts the PC to sleep" in out
    assert "the bot sets the sleep and lid settings itself when it starts" in out
    assert w.sets() == [] and w.states == []                     # read-only
    assert w.values == {"STANDBYIDLE": 1800, "HIBERNATEIDLE": 0, "LIDACTION": 1}

    w.values.update(STANDBYIDLE=0, LIDACTION=0)
    assert cli.main(["preflight", "--config", cli_config(tmp_path, False)]) == 0
    out = capsys.readouterr().out
    assert "power: plugged in; while plugged in this PC never sleeps on its own" in out
    assert "WARN power" not in out and "sets the sleep and lid settings" not in out

    w.values.update(LIDACTION=1)
    config = cli_config(tmp_path, False, extra="keep_awake: false\n")
    assert cli.main(["preflight", "--config", config]) == 0
    assert "keep_awake is false in the config" in capsys.readouterr().out


def test_preflight_off_windows_prints_no_power_line(tmp_path, monkeypatch, capsys):
    from ftmo_bot import __main__ as cli
    seeded(tmp_path, monkeypatch)
    assert cli.main(["preflight", "--config", cli_config(tmp_path, False)]) == 0
    out = capsys.readouterr().out
    assert "power:" not in out and "WARN" not in out
    assert MainBroker.last.sent == []
