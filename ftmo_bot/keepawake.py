"""Keep the PC awake while the bot runs, and notice when it was not.

A sleeping PC runs nothing: the bot does not plan, open, manage or close.
A position that is open then has only its stop at the broker. Seen on the
free trial (2026-11-11): the laptop slept through the evening and the bot
stood still for hours without a line in the log.

Four things. The first three act on Windows only (anywhere else they do
nothing):

* ``apply()`` sets the power plan, **while plugged in**, to never sleep or
  hibernate on its own and to do nothing when the lid closes. On battery
  Windows keeps its own settings: a closed laptop running in a bag
  overheats.
* ``hold()`` asks Windows not to sleep for idle time while this process
  lives. It does not stop a sleep someone starts (the lid, the power
  button, the Start menu); the lid is ``apply()``'s job.
* ``no_quick_edit()`` switches off the console's click-to-select. With it
  on, one click in the window pauses everything the bot prints, and so
  the bot, until a key is pressed.
* ``frozen_for()`` tells the loop how long it stood still between two
  ticks, so a sleep or a pause shows in the log.

``keep_awake: false`` in the config switches the first three off; the
stall check stays on.

What stays behind: the power plan ``apply()`` set stays set when the bot
stops, and ``keep_awake: false`` does not put the old values back (Windows
Settings does). The wake request and the console's click-to-select are
given back when the bot stops; a bot that is killed, not stopped, leaves
click-to-select off in that window until the window is closed.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

log = logging.getLogger("ftmo_bot")
NY = ZoneInfo("America/New_York")

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
QUICK_EDIT = 0x0040              # console input mode: a click starts a selection
EXTENDED_FLAGS = 0x0080          # must be set for QUICK_EDIT to be changed
SLACK = timedelta(minutes=4)     # a tick may take a while (history, a slow terminal)
LID = {0: "does nothing", 1: "puts the PC to sleep", 2: "hibernates the PC",
       3: "shuts the PC down"}
# powercfg's own names: (subgroup, setting)
SLEEP_AFTER = ("SUB_SLEEP", "STANDBYIDLE")
HIBERNATE_AFTER = ("SUB_SLEEP", "HIBERNATEIDLE")
LID_ACTION = ("SUB_BUTTONS", "LIDACTION")
SET_COMMANDS = (                 # the plugged-in ("ac") values only
    ("/change", "standby-timeout-ac", "0"),
    ("/change", "hibernate-timeout-ac", "0"),
    ("/setacvalueindex", "SCHEME_CURRENT", *LID_ACTION, "0"),
    ("/setactive", "SCHEME_CURRENT"),
)
BY_HAND = ("Windows Settings > System > Power: never sleep when plugged in; Control "
           "Panel > Power Options > Choose what closing the lid does: Do nothing when "
           "plugged in")


# --------------------------------------------------------- the calls to Windows

def _on_windows() -> bool:
    return sys.platform == "win32"


def _set_state(flags: int) -> int:               # pragma: no cover (Windows only)
    """``SetThreadExecutionState``: the state before, or 0 if it failed."""
    import ctypes
    fn = ctypes.windll.kernel32.SetThreadExecutionState
    fn.argtypes, fn.restype = [ctypes.c_uint], ctypes.c_uint
    return int(fn(flags))


def _ac_line() -> int:                           # pragma: no cover (Windows only)
    """``GetSystemPowerStatus``: 1 plugged in, 0 on battery, 255 unknown."""
    import ctypes

    class Status(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                    ("BatteryLifePercent", ctypes.c_ubyte),
                    ("SystemStatusFlag", ctypes.c_ubyte),
                    ("BatteryLifeTime", ctypes.c_ulong),
                    ("BatteryFullLifeTime", ctypes.c_ulong)]
    status = Status()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        return 255
    return int(status.ACLineStatus)


def _powercfg(*args: str) -> Tuple[int, str]:    # pragma: no cover (Windows only)
    """Run Windows' ``powercfg``: (exit code, what it printed)."""
    done = subprocess.run(["powercfg", *args], capture_output=True, text=True,
                          errors="replace", timeout=30)
    return done.returncode, done.stdout or ""


def _console_mode(new: Optional[int] = None) -> Optional[int]:   # pragma: no cover (Windows only)
    """The console's input mode; with ``new``, set it and return the mode
    before. None when there is no console (output goes to a file) or the
    call failed."""
    import ctypes
    k = ctypes.windll.kernel32
    k.GetStdHandle.argtypes, k.GetStdHandle.restype = [ctypes.c_int], ctypes.c_void_p
    k.GetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)]
    k.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    handle = k.GetStdHandle(-10)                 # the console's input
    mode = ctypes.c_uint()
    if not handle or not k.GetConsoleMode(handle, ctypes.byref(mode)):
        return None
    if new is not None and not k.SetConsoleMode(handle, new):
        return None
    return int(mode.value)


# --------------------------------------------------------------- the wake request

def hold() -> bool:
    """Ask Windows not to sleep for idle time while this thread lives.
    True if it took the request. Call it from the thread that runs the
    loop: the request ends with its thread."""
    if not _on_windows():
        return False
    try:
        # Windows answers with the state before, 0 for a failure. A first call
        # answers ES_CONTINUOUS; were it ever 0 on success, the only cost is a
        # warning in the log that the request was not taken.
        return bool(_set_state(ES_CONTINUOUS | ES_SYSTEM_REQUIRED))
    except Exception as e:                       # the bot runs without it
        log.warning("could not ask Windows to stay awake (%s)", e)
        return False


def release() -> None:
    """Give the request back (a stopped bot no longer keeps the PC awake)."""
    if not _on_windows():
        return
    try:
        _set_state(ES_CONTINUOUS)
    except Exception:                            # stopping anyway
        pass


# ------------------------------------------------------------ the console window

def no_quick_edit() -> Optional[int]:
    """Switch off the console's click-to-select and return the mode it
    had, for ``restore_console``. None: nothing was changed (not Windows,
    no console, already off, or the call failed)."""
    if not _on_windows():
        return None
    try:
        before = _console_mode()
        if before is None or not before & QUICK_EDIT:
            return None
        return _console_mode((before | EXTENDED_FLAGS) & ~QUICK_EDIT)
    except Exception as e:                       # the bot runs without it
        log.warning("could not switch off click-to-select in this window (%s)", e)
        return None


def restore_console(before: Optional[int]) -> None:
    """Give the window its click-to-select back."""
    if before is None or not _on_windows():
        return
    try:
        _console_mode(before | EXTENDED_FLAGS)
    except Exception:                            # stopping anyway
        pass


def guard_lines(held: bool, console_changed: bool) -> List[Tuple[bool, str]]:
    """(fine, line) for the loop's start: what protects the bot from a
    sleep or a pause while it runs."""
    if not _on_windows():
        return [(True, "awake: not Windows, nothing to hold")]
    out = [(True, "awake: Windows will not go to sleep on its own while the bot runs")
           if held else
           (False, "awake: Windows did not take the stay-awake request; if this PC "
                   "sleeps, the bot stops until it wakes")]
    if console_changed:
        out.append((True, "awake: a click in this window no longer pauses the bot "
                          "(click-to-select is off until it stops)"))
    return out


# ------------------------------------------------------------- the power settings

@dataclass(frozen=True)
class Power:
    """What Windows does while plugged in. ``None``: could not be read."""
    plugged: Optional[bool]          # False: on battery now
    sleep: Optional[int]             # seconds idle before it sleeps; 0 never
    hibernate: Optional[int]         # ... before it hibernates; 0 never
    lid: Optional[int]               # closing the lid: 0 nothing, 1 sleep, 2 hibernate, 3 off

    def stays_awake(self) -> bool:
        """Plugged in, and neither idle time nor the lid stops the PC. A
        hibernate setting that cannot be read is a PC without hibernation."""
        return (self.plugged is True and self.sleep == 0 and self.lid == 0
                and self.hibernate in (0, None))


def _index(sub: str, setting: str) -> Optional[int]:
    """The plugged-in value of one power setting. ``powercfg /query`` ends
    with the plugged-in value and then the battery one, as 0x numbers,
    whatever language Windows speaks."""
    try:
        code, text = _powercfg("/query", "SCHEME_CURRENT", sub, setting)
    except Exception as e:
        log.debug("powercfg /query %s %s failed: %s", sub, setting, e)
        return None
    found = re.findall(r"0x[0-9a-fA-F]{8}", text)
    if code != 0 or len(found) < 2:
        return None
    return int(found[-2], 16)


def read() -> Optional[Power]:
    """The power settings as they are; None when this is not Windows."""
    if not _on_windows():
        return None
    try:
        line = _ac_line()
    except Exception as e:
        log.debug("GetSystemPowerStatus failed: %s", e)
        line = 255
    return Power({0: False, 1: True}.get(line), _index(*SLEEP_AFTER),
                 _index(*HIBERNATE_AFTER), _index(*LID_ACTION))


def apply() -> Optional[Power]:
    """Set the plugged-in power settings so the PC stays awake with the lid
    open or closed, then read them back; None when this is not Windows.
    What counts is what is read back, not what powercfg answered: a PC
    without hibernation refuses that one command and is fine."""
    if not _on_windows():
        return None
    for args in SET_COMMANDS:
        try:
            code, _ = _powercfg(*args)
            if code != 0:
                log.debug("powercfg %s answered %d", " ".join(args), code)
        except Exception as e:
            log.debug("powercfg %s failed: %s", " ".join(args), e)
    return read()


def _minutes(seconds: int) -> str:
    return f"{max(1, round(seconds / 60))} min"


def report(power: Optional[Power]) -> List[Tuple[bool, str]]:
    """(fine, line) for each thing to say about the power settings."""
    if power is None:
        return [(True, "power: not Windows, nothing to set")]
    if power.stays_awake():
        return [(True, "power: plugged in; while plugged in this PC never sleeps on its "
                       "own, and closing the lid does nothing")]
    out = []
    if power.plugged is False:
        out.append("power: ON BATTERY. On battery Windows keeps its own settings, so the "
                   "PC can sleep when the lid closes or it sits idle, and the bot stops "
                   "until it wakes. Plug it in")
    elif power.plugged is None:
        out.append("power: cannot tell whether the PC is plugged in")
    if power.sleep is None or power.lid is None:
        out.append("power: the sleep and lid settings could not be read; check them by "
                   f"hand ({BY_HAND})")
    else:
        if power.sleep:
            out.append(f"power: while plugged in the PC still goes to sleep after "
                       f"{_minutes(power.sleep)} idle ({BY_HAND})")
        if power.lid:
            out.append(f"power: while plugged in, closing the lid still "
                       f"{LID.get(power.lid, 'stops the PC')} ({BY_HAND})")
    if power.hibernate:
        out.append(f"power: while plugged in the PC still hibernates after "
                   f"{_minutes(power.hibernate)} idle ({BY_HAND})")
    return [(False, line) for line in out]


# ------------------------------------------------------------ the loop stood still

def frozen_for(last: Optional[datetime], now: datetime, every: float) -> Optional[timedelta]:
    """How long ago the last tick started, if that is more than the loop's
    own pause plus some slack: the loop stood still in between. Measured
    from start to start, so a tick that hung is caught too."""
    if last is None:
        return None
    gap = now - last
    return gap if gap > timedelta(seconds=every) + SLACK else None


def frozen_text(last: datetime, gap: timedelta) -> str:
    minutes = round(gap.total_seconds() / 60)
    span = f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min"
    a, b = last.astimezone(NY), (last + gap).astimezone(NY)
    day = "%Y-%m-%d %H:%M" if a.date() != b.date() else "%H:%M"
    return (f"the bot stood still for {span}, from {a.strftime(day)} to "
            f"{b.strftime(day)} New York (the PC slept, the window was paused, or "
            "MetaTrader did not answer). In that time nothing was planned, opened, "
            "managed or closed; an open position had only its stop at the broker")
