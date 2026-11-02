"""The FTMO bot's daily cycle.

Every minute (``tick``):
1. roll the day-start balance at midnight Prague time (FTMO's day);
2. reconcile with the broker: a held position that is gone was stopped
   out; a bot position the state does not know is adopted (never
   forgotten); a broker read error aborts the tick without touching
   state;
3. retry any close that failed earlier (exits are never blocked);
4. guard: flatten everything just before a loss limit; entries stay
   blocked until the next FTMO day (for good after the max-loss line);
5. target: once equity holds the phase target plus a small margin for
   closing costs, flatten to lock the gain and stop FAST-4 entries; if
   FTMO's minimum trading days are not met yet, add one minimum-lot
   round trip per FTMO day, then halt so the phase can be reviewed;
6. after 16:05 New York, plan from the session that just completed;
7. 09:31-16:00 New York on the next session, execute that plan once:
   exits first (never blocked), then entries (until 10:30 only), each
   through ``rules.check_entry`` and never for a symbol already held.
   On a holiday the plan waits for the next session; a plan older than
   the previous session is discarded. A failed or raising close is
   queued and retried every tick;
8. keep-alive: a minimum-lot round trip in the first session of a new
   account and whenever 25 days pass without an opened position (FTMO
   ends accounts with no new trade for 30 days, funded ones too), also
   through ``rules.check_entry``.

Minimum-lot round trips (keep-alive, finish line) open only 10:00-10:45
New York, at least two hours before any close, early closes included
(FTMO forbids opening within two hours of a close of two hours or more).

Trading days are counted on FTMO's calendar (Prague dates) and only for
opened positions; a close counts for nothing. State written by this
version therefore never counts a day FTMO would not.

The state file belongs to one account. A terminal logged into another
account parks the old state under its login and resumes the new one's
(or starts fresh: a new phase). A state from before logins were kept is
adopted unless it holds a halt or a target lock, which never carry over
to an account they may not belong to.

A halted bot keeps ticking (retrying closes) until it holds nothing.
In dry-run mode (the default) every order is logged and nothing is sent.
"""

from __future__ import annotations

import json
import logging
import math
import time as _time
from dataclasses import asdict, dataclass, field, fields
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from . import fast4, rules, sessions
from .broker import Broker, Fill, Position
from .config import FtmoConfig

NY = ZoneInfo("America/New_York")
PRAGUE = ZoneInfo("Europe/Prague")
CLOSE_AT = time(16, 5)
OPEN_AT = time(9, 31)
ENTRY_DEADLINE = time(10, 30)   # entries only near the open, as tested
SESSION_END = time(16, 0)
ROUNDTRIP_FROM, ROUNDTRIP_TO = time(10, 0), time(10, 45)   # >2 h before a 13:00 early close
BAR_MINUTES = 30
# FTMO's index CFDs trade ~23 h a day: ~46 half-hour bars per session.
# 15,000 bars is ~320 sessions, enough for the 200-session average plus
# holidays. (5,000 bars would hold only ~108 sessions: no SMA200, no trades.)
BAR_COUNT = 15000
MIN_SESSIONS = 205
log = logging.getLogger("ftmo_bot")


@dataclass
class State:
    initial_balance: Optional[float] = None
    day: Optional[str] = None                 # Prague date of day_start_balance
    day_start_balance: Optional[float] = None
    plan_day: Optional[str] = None            # NY session the plan was made from
    plan_checked: Optional[str] = None        # NY date the close phase last ran
    pending_exits: List[str] = field(default_factory=list)
    pending_entries: List[str] = field(default_factory=list)
    pending_atr: Dict[str, float] = field(default_factory=dict)
    executed_day: Optional[str] = None        # NY date a plan was last executed
    held: Dict[str, Dict] = field(default_factory=dict)   # strat sym -> {ticket, entry_day}
    to_close: List[int] = field(default_factory=list)     # tickets whose close failed
    last_fill: Optional[str] = None
    trading_days: List[str] = field(default_factory=list)
    blocked_until: Optional[str] = None       # Prague date
    halted: Optional[str] = None
    login: Optional[int] = None               # the account this state belongs to
    target_locked: Optional[str] = None       # Prague date the target was locked in
    last_roundtrip: Optional[str] = None      # Prague date of the last min-lot round trip

    @classmethod
    def load(cls, path: Path) -> "State":
        """Unknown keys (a state written by a newer version) are dropped
        with a warning, so a rollback still starts."""
        if not path.exists():
            return cls()
        try:            # utf-8-sig: the runbook has the operator fix it in Notepad
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except ValueError as e:
            raise RuntimeError(f"state file {path} could not be read ({e}). Fix it in "
                               "Notepad (quotes, commas, brackets) and start again.") from e
        if not isinstance(raw, dict):
            raise RuntimeError(f"state file {path} does not hold a state (a JSON object)")
        known = {f.name for f in fields(cls)}
        extra = sorted(set(raw) - known)
        if extra:
            log.warning("state %s: ignoring unknown keys %s", path, extra)
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        tmp.replace(path)


class Runner:
    def __init__(self, cfg: FtmoConfig, broker: Broker, readonly: bool = False) -> None:
        """``readonly``: never move or write a state file (``plan`` and
        ``preflight``). The start-up checks run before any state file is
        moved, so a refused start leaves the files as they were."""
        self.cfg, self.b = cfg, broker
        self.path = Path(cfg.state_path)
        self.st = State.load(self.path)
        acct = self.b.account()
        if cfg.login is not None and acct.login != cfg.login:
            # main() checks this too; checking the account read here closes
            # the gap between the two reads, and tick() then refuses any
            # later switch away from st.login (= cfg.login).
            raise RuntimeError(f"the terminal is on account {acct.login} but the config "
                               f"is for account {cfg.login}: log the terminal into "
                               f"{cfg.login}, or set login: to this account in the config")
        moves: List[Tuple[Path, Path]] = []      # applied once the checks pass
        if self.st.login is not None and self.st.login != acct.login:
            moves = self._switch_account(self.st.login, acct.login)
        elif self.st.login is None and (self.st.halted or self.st.target_locked):
            legacy = self.path.with_name(f"{self.path.stem}.legacy{self.path.suffix}")
            log.warning("state without an account login holds a halt or a target "
                        "lock: not carried over to account %s (kept as %s)",
                        acct.login, legacy)
            if self.path.exists():
                moves = [(self.path, legacy)]
            self.st = State()
        elif self.st.login is None and self.st.trading_days:
            log.warning("state without an account login: its %d trading days were "
                        "counted by an older rule (closes included, New York dates) "
                        "and are dropped", len(self.st.trading_days))
            self.st.trading_days = []
        self.st.login = acct.login
        self.balance_source = "the bot's state"
        if self.st.initial_balance is None:              # a new account
            if cfg.initial_balance is None:              # FTMO accounts start at their size
                self._note_balance_from_account(acct.balance, acct.login)
                self.balance_source = "the account"
            else:
                self._check_initial_balance(cfg, acct.balance, acct.login)
                self.balance_source = "the config"
            self.st.initial_balance = cfg.initial_balance or acct.balance
        if not readonly:
            for src, dst in moves:
                src.replace(dst)
        self.limits = rules.Limits(self.st.initial_balance, cfg.max_loss,
                                   cfg.daily_loss, cfg.guard_buffer)
        self.by_broker = {v: k for k, v in cfg.symbols.items()}
        # last_fill None (a new account): FTMO's 30 days run from when the
        # account was opened, not from the bot's start, so the keep-alive
        # is due in the first session.

    @staticmethod
    def _check_initial_balance(cfg: FtmoConfig, balance: float, login: int) -> None:
        """A configured account size that this account's balance cannot
        have (at or under the max-loss line, or at or over the target)
        would draw every loss line and the target in the wrong place: an
        instant permanent halt, or a target 'reached' on the first tick.
        Refuse to start; a small difference only warns."""
        size = cfg.initial_balance
        assert size is not None
        low = size * (1 - cfg.max_loss)
        high = size * (1 + cfg.profit_target) if cfg.profit_target is not None else None
        if balance <= low or (high is not None and balance >= high):
            raise RuntimeError(
                f"initial_balance {size:,.2f} in the config does not fit account "
                f"{login} (balance {balance:,.2f}). FTMO accounts start at their size: "
                "set initial_balance to it, or to null to take it from the account.")
        if abs(balance / size - 1) > 0.01:
            log.warning("initial_balance %.2f in the config but the account balance "
                        "is %.2f: check the account size and currency", size, balance)

    @staticmethod
    def _note_balance_from_account(balance: float, login: int) -> None:
        """A new FTMO account starts at a round size (10,000, 25,000, ...).
        Any other balance means it traded before the bot first saw it (or
        the bot's state was lost), and the loss lines drawn from it would
        sit in the wrong place: warn, so the operator sets the size."""
        if round(balance, 2) % 1000:
            log.warning("account %s: initial balance %.2f taken from the account, but a "
                        "new FTMO account starts at a round size. If it traded before the "
                        "bot, stop and set initial_balance to the account size",
                        login, balance)
        else:
            log.info("account %s: initial balance %.2f taken from the account",
                     login, balance)

    def _parked(self, login: int) -> Path:
        return self.path.with_name(f"{self.path.stem}.{login}{self.path.suffix}")

    def _switch_account(self, old: int, new: int) -> List[Tuple[Path, Path]]:
        """The terminal is on another account than the state file. Park
        the old account's state under its login and resume the new
        account's parked state, or start fresh (the next phase). Returns
        the file moves, which the caller makes once the start-up checks
        pass. Switching back and forth (a trial, a phase review) loses
        nothing, so the inactivity clock and the trading days survive."""
        mine = self._parked(new)
        log.warning("state file belongs to account %s but the terminal is on %s: "
                    "%s", old, new, f"resuming {mine}" if mine.exists()
                    else "starting fresh (a new phase)")
        moves = [(self.path, self._parked(old))] if self.path.exists() else []
        if mine.exists():
            self.st = State.load(mine)
            moves.append((mine, self.path))
        else:
            self.st = State()
        return moves

    def save(self) -> None:
        self.st.save(self.path)

    # --------------------------------------------------------- helpers
    @staticmethod
    def _prague(now: datetime) -> str:
        return now.astimezone(PRAGUE).date().isoformat()

    @staticmethod
    def _roundtrip_window(now: datetime) -> bool:
        local = now.astimezone(NY)
        return local.weekday() < 5 and ROUNDTRIP_FROM <= local.time() <= ROUNDTRIP_TO

    def _note_open(self, now: datetime) -> None:
        """A position was opened: resets the inactivity clock and counts a
        trading day on FTMO's calendar. Closes count for neither."""
        self.st.last_fill = now.isoformat()
        d = self._prague(now)
        if d not in self.st.trading_days:
            self.st.trading_days.append(d)

    def _close(self, pos: Position, why: str, now: datetime) -> bool:
        """Close one position; a failure is queued for retry. True if closed."""
        if self.cfg.dry_run:
            log.info("DRY-RUN close %s %.2f lots (%s)", pos.symbol, pos.volume, why)
            return True
        try:
            f = self.b.close(pos, self.cfg.magic, f"FAST4 {why}")
        except Exception as e:                   # queue it like any failure
            f = Fill(False, message=f"error: {e}")
        log.info("close %s %.2f lots (%s): %s", pos.symbol, pos.volume, why, f)
        if f.ok:
            if pos.ticket in self.st.to_close:
                self.st.to_close.remove(pos.ticket)
            s = self.by_broker.get(pos.symbol)
            if s in self.st.held and self.st.held[s].get("ticket") == pos.ticket:
                del self.st.held[s]
        elif pos.ticket not in self.st.to_close:
            self.st.to_close.append(pos.ticket)
            log.error("close of ticket %d FAILED; will retry every tick", pos.ticket)
        self.save()
        return f.ok

    def flatten(self, why: str, now: datetime, live: List[Position]) -> None:
        for p in live:
            self._close(p, why, now)

    def stand_down(self, now: datetime, live: List[Position]) -> None:
        """Close every bot position and drop the pending plan: FTMO pays
        out only on a flat account. ``run`` picks up again afterwards. In
        dry-run nothing is closed, so nothing is dropped or saved either."""
        self.flatten("stand-down", now, live)
        if self.cfg.dry_run:
            return
        self._clear_plan()
        self.save()

    # ----------------------------------------------------------- steps
    def roll_day(self, now: datetime) -> None:
        pd_ = now.astimezone(PRAGUE).date().isoformat()
        if self.st.day != pd_:
            self.st.day = pd_
            self.st.day_start_balance = self.b.account().balance
            log.info("FTMO day %s: day-start balance %.2f", pd_,
                     self.st.day_start_balance)
            if self.st.blocked_until and pd_ >= self.st.blocked_until:
                self.st.blocked_until = None

    def reconcile(self, now: datetime, live: List[Position]) -> None:
        if self.cfg.dry_run:
            return
        live_tickets = {p.ticket for p in live}
        self.st.to_close = [t for t in self.st.to_close if t in live_tickets]
        for s in list(self.st.held):                 # gone -> stopped out
            if self.st.held[s].get("ticket") not in live_tickets:
                log.info("%s no longer open (stop hit or closed outside the bot)", s)
                del self.st.held[s]
        for p in live:                               # unknown -> adopt
            s = self.by_broker.get(p.symbol)
            if p.ticket in self.st.to_close or s is None or s in self.st.held:
                continue
            if not p.sl:                             # FAST-4 entries always have a stop;
                log.warning("closing stop-less bot position %s (ticket %d)",
                            p.symbol, p.ticket)    # e.g. a stray keep-alive
                self.st.to_close.append(p.ticket)
            else:
                log.warning("adopting open %s position (ticket %d) into state",
                            s, p.ticket)
                self.st.held[s] = {"ticket": p.ticket,
                                   "entry_day": now.astimezone(NY).date().isoformat()}

    def retry_closes(self, now: datetime, live: List[Position]) -> None:
        for p in live:
            if p.ticket in self.st.to_close:
                self._close(p, "retry", now)

    def guard(self, now: datetime, live: List[Position]) -> bool:
        a = self.b.account()
        why = self.limits.guard(a.equity, self.st.day_start_balance)
        if not why:
            return False
        log.warning("GUARD: %s - flattening", why)
        self.flatten("guard", now, live)
        nxt = (now.astimezone(PRAGUE).date() + timedelta(days=1)).isoformat()
        self.st.blocked_until = nxt
        if "max-loss" in why:
            self.st.halted = why
        return True

    def target(self, now: datetime, live: List[Position]) -> bool:
        """The phase target. Equity at the target plus ``target_margin``
        (room for closing costs) locks the gain in: everything is
        flattened and FAST-4 entries stop. Once the account is flat, a
        realised balance under the target releases the lock (trading
        resumes); otherwise one minimum-lot round trip per FTMO day adds
        any missing minimum trading days, then the bot halts for the
        phase review. Nothing is judged while a close is still pending."""
        if self.cfg.profit_target is None:              # the funded account
            if self.st.target_locked:
                log.warning("no profit target configured: target lock of %s cleared",
                            self.st.target_locked)
                self.st.target_locked = None
            return False
        goal = self.st.initial_balance * (1 + self.cfg.profit_target)
        a = self.b.account()
        days, need = len(self.st.trading_days), self.cfg.min_trading_days
        if self.st.target_locked is None:
            if a.equity < goal + self.cfg.target_margin * self.st.initial_balance:
                return False
            log.warning("TARGET: equity %.2f is over the target %.2f - flattening "
                        "to lock it in (trading days %d/%d)", a.equity, goal, days, need)
            self.flatten("target", now, live)
            self.st.target_locked = self._prague(now)
        if not self.cfg.dry_run:
            left = self.b.positions(self.cfg.magic)
            if left:                                 # a failed close, or a late fill adopted
                fresh = [p for p in left if p.ticket not in self.st.to_close]
                if fresh:                            # queued ones are retried by retry_closes
                    log.info("target lock: closing %d position(s) still open", len(fresh))
                    self.flatten("target", now, fresh)
                return True                          # judge only a flat account
        a = self.b.account()
        if a.balance < goal:
            log.warning("balance %.2f is under the target %.2f after the lock: "
                        "released, trading resumes", a.balance, goal)
            self.st.target_locked = None
            return False
        if days >= need:
            log.warning("TARGET reached: balance %.2f with %d trading days - "
                        "halting for the phase review", a.balance, days)
            self.st.halted = "profit target reached; review the phase on FTMO"
            return True
        if self.st.last_roundtrip != self._prague(now) and self._roundtrip_window(now):
            why = rules.check_entry(a.equity, self.st.day_start_balance, self.limits,
                                    len(self.b.positions(self.cfg.magic)),
                                    self.cfg.max_positions, bool(self.st.blocked_until))
            if why:
                log.info("finish-line trade refused: %s", why)
            else:
                log.info("finish line: trading day %d of %d", days + 1, need)
                self._roundtrip(now, "finish-line")
        return True

    def _sessions(self, s: str, now: datetime) -> List[sessions.Session]:
        return sessions.build(self.b.bars(self.cfg.symbols[s], BAR_MINUTES,
                                          BAR_COUNT), BAR_MINUTES, now)

    def compute_plan(self, now: datetime, day: Optional[date] = None
                     ) -> Optional[Tuple[date, fast4.Plan]]:
        """FAST-4 plan from the last completed session (which must be
        ``day`` when given, and the same day for every symbol). Read-only.
        If the broker's server-clock rule changes while the symbols are
        read (its first narrowing), the pass is repeated so that every
        symbol's sessions come from the same rule; a second change raises,
        and the planning tick retries."""
        for _ in range(2):
            before = getattr(self.b, "rule", None)
            res = self._compute_once(now, day)
            if getattr(self.b, "rule", None) == before:
                return res
            log.warning("server clock rule changed while reading bars "
                        "(%s -> %s); recomputing", before, getattr(self.b, "rule", None))
        raise RuntimeError("server clock rule changed twice while reading bars")

    def _compute_once(self, now: datetime, day: Optional[date]
                      ) -> Optional[Tuple[date, fast4.Plan]]:
        ind, held_n, days = {}, {}, set()
        for s in self.cfg.symbols:
            done = [x for x in self._sessions(s, now) if x.complete]
            if not done or (day is not None and done[-1].day != day):
                log.info("no completed %s session for %s; no plan", s, day)
                return None
            if len(done) < MIN_SESSIONS:
                log.error("%s: only %d completed sessions in the terminal's "
                          "history, need %d for the 200-session average; no plan",
                          s, len(done), MIN_SESSIONS)
                return None
            days.add(done[-1].day)
            ind[s] = fast4.indicators(done)
            if s in self.st.held:
                entry = date.fromisoformat(self.st.held[s]["entry_day"])
                held_n[s] = sum(1 for x in done if x.day >= entry)
        if len(days) != 1:
            log.warning("symbols end on different sessions %s; no plan", sorted(days))
            return None
        return days.pop(), fast4.plan(ind, held_n, self.cfg.max_positions,
                                      self.cfg.max_hold_sessions)

    def make_plan(self, now: datetime) -> None:
        today = now.astimezone(NY).date()
        res = self.compute_plan(now, today)          # a broker error retries next tick
        self.st.plan_checked = today.isoformat()     # once per day, even on holidays
        if res is None:                              # holiday: keep any pending plan
            return
        _, p = res
        self.st.plan_day = today.isoformat()
        self.st.pending_exits, self.st.pending_entries = p.exits, p.entries
        self.st.pending_atr = p.atr
        log.info("plan for the next open: exits %s, entries %s", p.exits, p.entries)

    def _clear_plan(self) -> None:
        self.st.pending_exits, self.st.pending_entries = [], []
        self.st.pending_atr = {}

    def plan_status(self, now: datetime) -> str:
        """'current' if the plan comes from the session immediately before
        today's; 'wait' if today's session has not started (first bar not in
        yet, or a holiday); 'stale' otherwise."""
        if not self.st.plan_day:
            return "stale"
        ss = self._sessions(self.cfg.keepalive_symbol, now)
        today = now.astimezone(NY).date()
        if not ss or ss[-1].day != today:
            return "wait"
        prev = [x.day for x in ss if x.complete and x.day < today]
        ok = bool(prev) and prev[-1].isoformat() == self.st.plan_day
        return "current" if ok else "stale"

    def execute(self, now: datetime, live: List[Position],
                entries_ok: bool = True) -> None:
        today = now.astimezone(NY).date().isoformat()
        exits = list(self.st.pending_exits)
        atrs = dict(self.st.pending_atr)
        entries = list(self.st.pending_entries) if entries_ok else []
        if not entries_ok and self.st.pending_entries:
            log.warning("missed the open window; entries %s skipped",
                        self.st.pending_entries)
        # mark executed and drop the plan BEFORE sending anything, so a
        # crash or retry can never send the same plan twice
        self.st.executed_day = today
        self._clear_plan()
        self.save()
        by_ticket = {p.ticket: p for p in live}
        for s in exits:                              # exits are never blocked
            p = by_ticket.get(self.st.held.get(s, {}).get("ticket"))
            if p is not None:
                self._close(p, "exit", now)
        for s in entries:
            sym = self.cfg.symbols[s]
            current = self.b.positions(self.cfg.magic)
            if s in self.st.held or any(p.symbol == sym for p in current):
                log.info("entry %s skipped: already holding it", s)
                continue
            a = self.b.account()
            blocked = bool(self.st.blocked_until or self.st.halted
                           or self.st.target_locked)
            why = rules.check_entry(a.equity, self.st.day_start_balance,
                                    self.limits, len(current),
                                    self.cfg.max_positions, blocked)
            if why:
                log.info("entry %s refused: %s", s, why)
                continue
            spec = self.b.spec(sym)
            if not spec.exists or spec.volume_step <= 0:
                log.error("entry %s skipped: symbol %s unavailable", s, sym)
                continue
            _, ask = self.b.quote(sym)
            stop = ask - self.cfg.atr_stop_mult * atrs[s]
            vol = rules.lots(a.balance, self.cfg.risk_per_trade, ask, stop,
                             self.b.loss_per_lot(sym, ask, stop),
                             self.cfg.notional_cap, spec.volume_step,
                             spec.volume_min, spec.volume_max)
            if vol <= 0:
                log.info("entry %s skipped: size below the minimum volume", s)
                continue
            if self.cfg.cap_combined_risk:
                lpl = self.b.loss_per_lot(sym, ask, stop)
                committed = sum(self.b.loss_per_lot(p.symbol, p.price_open, p.sl)
                                * p.volume for p in current if p.sl)
                room = rules.risk_room(a.balance, self.st.day_start_balance,
                                       committed, self.limits)
                fit = math.floor(room / lpl / spec.volume_step + 1e-9) * spec.volume_step
                if fit < vol:
                    log.info("entry %s cut from %.2f to %.2f lots: open stops "
                             "already risk %.2f, room %.2f", s, vol, fit,
                             committed, room)
                    vol = round(fit, 8)
                if vol < spec.volume_min:
                    log.info("entry %s skipped: no risk room left", s)
                    continue
            if self.cfg.dry_run:
                log.info("DRY-RUN buy %s %.2f lots at ~%.2f, stop %.2f", sym,
                         vol, ask, stop)
                continue
            try:
                f = self.b.buy(sym, vol, stop, self.cfg.magic, "FAST4 entry")
            except Exception:                        # may or may not have filled
                log.exception("buy %s failed; reconcile adopts it if it filled", sym)
                continue
            log.info("buy %s %.2f lots stop %.2f: %s", sym, vol, stop, f)
            if f.ok:
                self.st.held[s] = {"ticket": f.ticket, "entry_day": today}
                self._note_open(now)
            self.save()

    def _roundtrip(self, now: datetime, why: str) -> None:
        """Open and close the minimum lot of the keep-alive symbol: a trade
        that resets FTMO's inactivity clock or adds a trading day, with
        nothing left resting in the market. One attempt per FTMO day: a
        buy that raises may or may not have filled (reconcile closes a
        stray), so the day is not counted and tomorrow tries again. The
        attempt is saved before the buy, so a crash cannot repeat it."""
        self.st.last_roundtrip = self._prague(now)
        self.save()
        sym = self.cfg.symbols[self.cfg.keepalive_symbol]
        spec = self.b.spec(sym)
        if not spec.exists:
            log.error("%s skipped: %s unavailable", why, sym)
            return
        if self.cfg.dry_run:                       # nothing opened: no trading day, and
            log.info("DRY-RUN %s: buy+close %s %.2f",  # the inactivity clock stays put
                     why, sym, spec.volume_min)
            return
        try:
            f = self.b.buy(sym, spec.volume_min, None, self.cfg.magic, f"FAST4 {why}")
        except Exception:
            log.exception("%s buy %s failed; tried again tomorrow", why, sym)
            return
        log.info("%s buy %s: %s", why, sym, f)
        if not f.ok:
            return
        self._note_open(now)
        opened = [p for p in self.b.positions(self.cfg.magic) if p.ticket == f.ticket]
        if not opened:
            log.error("%s ticket %d not found; reconcile will close it", why, f.ticket)
            return
        self._close(opened[0], why, now)           # failure is queued for retry

    def keepalive(self, now: datetime, live: List[Position]) -> None:
        """FTMO closes an account with no opened position for 30 days, in
        the evaluation and on the funded account alike; ``keepalive_days``
        0 turns this off. A new account (no opened position on record)
        gets its round trip in the first session: FTMO's 30 days started
        when the account was opened, which may be well before the bot."""
        if self.cfg.keepalive_days <= 0 or not self._roundtrip_window(now):
            return
        if self.st.last_fill is not None and now - datetime.fromisoformat(
                self.st.last_fill) < timedelta(days=self.cfg.keepalive_days):
            return
        if self.st.last_roundtrip == self._prague(now):
            return
        a = self.b.account()
        why = rules.check_entry(a.equity, self.st.day_start_balance, self.limits,
                                len(live), self.cfg.max_positions,
                                bool(self.st.blocked_until or self.st.halted))
        if why:
            log.info("keep-alive refused: %s", why)
            return
        self._roundtrip(now, "keepalive")

    # ------------------------------------------------------------ tick
    def tick(self, now: Optional[datetime] = None) -> None:
        now = now or self.b.now()
        refresh = getattr(self.b, "refresh_clock", None)
        if refresh is not None:                      # MT5: keep the clock verified
            refresh()
        login = self.b.account().login
        if login != self.st.login:                   # never act on another account
            raise RuntimeError(
                f"the terminal switched from account {self.st.login} to {login} "
                "while the bot was running; nothing done. Stop the bot and start "
                "it again on the account you want.")
        live = self.b.positions(self.cfg.magic)      # raises on a broker error
        self.roll_day(now)
        self.reconcile(now, live)
        self.retry_closes(now, live)
        live = self.b.positions(self.cfg.magic)
        if self.st.halted:
            if live and not self.cfg.dry_run:
                self.flatten("halted", now, live)
            self.save()
            return
        if self.guard(now, live) or self.target(now, live):
            self.save()
            return
        local = now.astimezone(NY)
        today = local.date().isoformat()
        weekday = local.weekday() < 5
        if weekday and local.time() >= CLOSE_AT and self.st.plan_checked != today:
            self.make_plan(now)
        if (weekday and OPEN_AT <= local.time() < SESSION_END
                and self.st.executed_day != today
                and (self.st.pending_exits or self.st.pending_entries)):
            try:
                status = self.plan_status(now)
            except Exception as e:                   # e.g. the clock refuses bars
                status = "unreadable"
                if not self._plan_is_recent(local.date()):
                    log.error("cannot read today's session (%s); waiting", e)
                else:
                    log.error("cannot read today's session (%s): planned exits run "
                              "now, entries wait until %s", e,
                              ENTRY_DEADLINE.strftime("%H:%M"))
                    self._run_exits(now, live)
                    if local.time() > ENTRY_DEADLINE:
                        log.warning("entries %s dropped: today's session was not "
                                    "readable before the entry deadline",
                                    self.st.pending_entries)
                        self.st.executed_day = today
                        self._clear_plan()
            if status == "current":
                self.execute(now, live,
                             entries_ok=local.time() <= ENTRY_DEADLINE)
            elif status == "stale":
                log.warning("plan from %s is stale; discarded", self.st.plan_day)
                self._clear_plan()
        self.keepalive(now, live)
        self.save()

    def _run_exits(self, now: datetime, live: List[Position]) -> None:
        """The plan's exits alone (never blocked). They are dropped from
        the plan before anything is sent, so they go out at most once; the
        entries stay pending for a later tick."""
        exits = list(self.st.pending_exits)
        if not exits:
            return
        self.st.pending_exits = []
        self.save()
        by_ticket = {p.ticket: p for p in live}
        for s in exits:
            p = by_ticket.get(self.st.held.get(s, {}).get("ticket"))
            if p is not None:
                self._close(p, "exit", now)

    def _plan_is_recent(self, today: date) -> bool:
        """The plan was made on the weekday before ``today`` (made on a
        verified clock, so its exits are safe to run when today's session
        cannot be read)."""
        if not self.st.plan_day:
            return False
        prev = today - timedelta(days=3 if today.weekday() == 0 else 1)
        return self.st.plan_day == prev.isoformat()

    def holding(self) -> bool:
        """Bot positions on this state's account. A terminal on another
        account cannot show them, so it counts as still holding: a halted
        run keeps retrying until it sees its own book empty."""
        if self.b.account().login != self.st.login:
            return True
        return bool(self.b.positions(self.cfg.magic))

    def run(self, every: int = 60) -> None:    # pragma: no cover (loop)
        log.info("FTMO bot running (%s), risk %.1f%% per trade, symbols %s",
                 "DRY-RUN" if self.cfg.dry_run else "LIVE ORDERS",
                 self.cfg.risk_per_trade * 100, self.cfg.symbols)
        while True:
            try:
                self.tick()
                if self.st.halted and (self.cfg.dry_run or not self.holding()):
                    log.warning("halted: %s", self.st.halted)
                    return
            except Exception:                    # keep running; state untouched
                log.exception("tick failed")
            _time.sleep(every)
