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
5. target: once the phase target is reached with enough trading days,
   flatten and halt so the phase can be reviewed on FTMO;
6. after 16:05 New York, plan from the session that just completed;
7. 09:31-16:00 New York on the next session, execute that plan once:
   exits first (never blocked), then entries (until 10:30 only), each
   through ``rules.check_entry`` and never for a symbol already held.
   On a holiday the plan waits for the next session; a plan older than
   the previous session is discarded. A failed or raising close is
   queued and retried every tick;
8. evaluation only: a keep-alive trade if 25 days pass without a fill,
   also through ``rules.check_entry``.

A halted bot keeps ticking (retrying closes) until it holds nothing.
In dry-run mode (the default) every order is logged and nothing is sent.
"""

from __future__ import annotations

import json
import logging
import time as _time
from dataclasses import asdict, dataclass, field
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
BAR_MINUTES = 30
BAR_COUNT = 5000                # ~380 sessions of 30-minute bars
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

    @classmethod
    def load(cls, path: Path) -> "State":
        if path.exists():
            return cls(**json.loads(path.read_text()))
        return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2))
        tmp.replace(path)


class Runner:
    def __init__(self, cfg: FtmoConfig, broker: Broker) -> None:
        self.cfg, self.b = cfg, broker
        self.path = Path(cfg.state_path)
        self.st = State.load(self.path)
        acct = self.b.account()
        if self.st.initial_balance is None:
            if cfg.initial_balance is None:
                log.warning("initial_balance not set; using the current balance "
                            "%.2f. Set it to the FTMO account size.", acct.balance)
            self.st.initial_balance = cfg.initial_balance or acct.balance
        self.limits = rules.Limits(self.st.initial_balance, cfg.max_loss,
                                   cfg.daily_loss, cfg.guard_buffer)
        self.by_broker = {v: k for k, v in cfg.symbols.items()}
        if self.st.last_fill is None:          # inactivity counts from the start
            self.st.last_fill = self.b.now().isoformat()

    def save(self) -> None:
        self.st.save(self.path)

    # --------------------------------------------------------- helpers
    def _note_fill(self, now: datetime) -> None:
        d = now.astimezone(NY).date().isoformat()
        self.st.last_fill = now.isoformat()
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
            self._note_fill(now)
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
                self._note_fill(now)
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
        a = self.b.account()
        if rules.target_reached(a.equity, self.st.initial_balance,
                                self.cfg.profit_target,
                                len(self.st.trading_days),
                                self.cfg.min_trading_days):
            log.warning("TARGET reached: equity %.2f - flattening and halting",
                        a.equity)
            self.flatten("target", now, live)
            self.st.halted = "profit target reached; review the phase on FTMO"
            return True
        return False

    def _sessions(self, s: str, now: datetime) -> List[sessions.Session]:
        return sessions.build(self.b.bars(self.cfg.symbols[s], BAR_MINUTES,
                                          BAR_COUNT), BAR_MINUTES, now)

    def compute_plan(self, now: datetime, day: Optional[date] = None
                     ) -> Optional[Tuple[date, fast4.Plan]]:
        """FAST-4 plan from the last completed session (which must be
        ``day`` when given, and the same day for every symbol). Read-only."""
        ind, held_n, days = {}, {}, set()
        for s in self.cfg.symbols:
            done = [x for x in self._sessions(s, now) if x.complete]
            if not done or (day is not None and done[-1].day != day):
                log.info("no completed %s session for %s; no plan", s, day)
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
            blocked = bool(self.st.blocked_until or self.st.halted)
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
                self._note_fill(now)
            self.save()

    def keepalive(self, now: datetime, live: List[Position]) -> None:
        if self.cfg.profit_target is None or self.cfg.keepalive_days <= 0:
            return
        if now - datetime.fromisoformat(self.st.last_fill) < timedelta(
                days=self.cfg.keepalive_days):
            return
        local = now.astimezone(NY)
        if local.weekday() >= 5 or not time(10, 0) <= local.time() <= time(15, 30):
            return
        a = self.b.account()
        why = rules.check_entry(a.equity, self.st.day_start_balance, self.limits,
                                len(live), self.cfg.max_positions,
                                bool(self.st.blocked_until or self.st.halted))
        if why:
            log.info("keep-alive refused: %s", why)
            return
        sym = self.cfg.symbols[self.cfg.keepalive_symbol]
        spec = self.b.spec(sym)
        if not spec.exists:
            log.error("keep-alive skipped: %s unavailable", sym)
            return
        if self.cfg.dry_run:
            log.info("DRY-RUN keep-alive: buy+close %s %.2f", sym, spec.volume_min)
            self.st.last_fill = now.isoformat()
            return
        try:
            f = self.b.buy(sym, spec.volume_min, None, self.cfg.magic, "FAST4 keepalive")
        except Exception:                          # may have filled: reconcile closes it
            log.exception("keep-alive buy %s failed", sym)
            self._note_fill(now)
            return
        log.info("keep-alive buy %s: %s", sym, f)
        if not f.ok:
            return
        self._note_fill(now)                       # never a second keep-alive
        opened = [p for p in self.b.positions(self.cfg.magic) if p.ticket == f.ticket]
        if not opened:
            log.error("keep-alive ticket %d not found; reconcile will close it", f.ticket)
            return
        self._close(opened[0], "keepalive", now)   # failure is queued for retry

    # ------------------------------------------------------------ tick
    def tick(self, now: Optional[datetime] = None) -> None:
        now = now or self.b.now()
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
            status = self.plan_status(now)
            if status == "current":
                self.execute(now, live,
                             entries_ok=local.time() <= ENTRY_DEADLINE)
            elif status == "stale":
                log.warning("plan from %s is stale; discarded", self.st.plan_day)
                self._clear_plan()
        self.keepalive(now, live)
        self.save()

    def holding(self) -> bool:
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
