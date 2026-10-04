"""The FTMO bot's daily cycle.

Every minute (``tick``):
1. roll the day-start balance at midnight Prague time (FTMO's day);
2. reconcile positions (a missing one was stopped out by its resting SL);
3. guard: flatten everything just before a loss limit; entries stay
   blocked until the next FTMO day (or for good after the max-loss line);
4. target: once the phase target is reached with enough trading days,
   flatten and halt so the phase can be reviewed by FTMO;
5. after 16:05 New York, compute the plan from the completed session;
6. after 09:31 New York the next session, execute the plan: exits first
   (never blocked), then entries, each through ``rules.check_entry``;
7. evaluation only: a keep-alive trade if 25 days pass without a fill.

In dry-run mode (the default) every order is logged and nothing is sent.
"""

from __future__ import annotations

import json
import logging
import time as _time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from . import fast4, rules, sessions
from .broker import Broker
from .config import FtmoConfig

NY = ZoneInfo("America/New_York")
PRAGUE = ZoneInfo("Europe/Prague")
CLOSE_AT = time(16, 5)
OPEN_AT = time(9, 31)
ENTRY_DEADLINE = time(10, 30)   # entries only near the open, as tested
BAR_MINUTES = 30
BAR_COUNT = 5000          # ~380 sessions of 30-minute bars
log = logging.getLogger("ftmo_bot")


@dataclass
class State:
    initial_balance: Optional[float] = None
    day: Optional[str] = None                 # Prague date of day_start_balance
    day_start_balance: Optional[float] = None
    plan_day: Optional[str] = None            # NY date the plan was made on
    pending_exits: List[str] = field(default_factory=list)
    pending_entries: List[str] = field(default_factory=list)
    pending_atr: Dict[str, float] = field(default_factory=dict)
    executed_day: Optional[str] = None        # NY date the plan was executed
    held: Dict[str, Dict] = field(default_factory=dict)   # strat sym -> {ticket, entry_day}
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
            self.st.initial_balance = cfg.initial_balance or acct.balance
        self.limits = rules.Limits(self.st.initial_balance, cfg.max_loss,
                                   cfg.daily_loss, cfg.guard_buffer)
        self.by_broker = {v: k for k, v in cfg.symbols.items()}
        if self.st.last_fill is None:          # inactivity counts from the start
            self.st.last_fill = self.b.now().isoformat()

    # --------------------------------------------------------- helpers
    def _note_fill(self, now: datetime) -> None:
        d = now.astimezone(NY).date().isoformat()
        self.st.last_fill = now.isoformat()
        if d not in self.st.trading_days:
            self.st.trading_days.append(d)

    def _close(self, pos, why: str, now: datetime) -> None:
        if self.cfg.dry_run:
            log.info("DRY-RUN close %s %.2f lots (%s)", pos.symbol, pos.volume, why)
            return
        f = self.b.close(pos, self.cfg.magic, f"FAST4 {why}")
        log.info("close %s %.2f lots (%s): %s", pos.symbol, pos.volume, why, f)
        if f.ok:
            self._note_fill(now)

    def flatten(self, why: str, now: datetime) -> None:
        for p in self.b.positions(self.cfg.magic):
            self._close(p, why, now)
        if not self.cfg.dry_run:
            self.st.held.clear()

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

    def reconcile(self, now: datetime) -> None:
        live = {self.by_broker.get(p.symbol) for p in self.b.positions(self.cfg.magic)}
        for s in list(self.st.held):
            if s not in live and not self.cfg.dry_run:
                log.info("%s no longer open (stop hit or closed outside the bot)", s)
                del self.st.held[s]
                self._note_fill(now)

    def guard(self, now: datetime) -> bool:
        a = self.b.account()
        why = self.limits.guard(a.equity, self.st.day_start_balance)
        if not why:
            return False
        log.warning("GUARD: %s - flattening", why)
        self.flatten("guard", now)
        nxt = (now.astimezone(PRAGUE).date() + timedelta(days=1)).isoformat()
        self.st.blocked_until = nxt
        if "max-loss" in why:
            self.st.halted = why
        return True

    def target(self, now: datetime) -> bool:
        a = self.b.account()
        if rules.target_reached(a.equity, self.st.initial_balance,
                                self.cfg.profit_target,
                                len(self.st.trading_days),
                                self.cfg.min_trading_days):
            log.warning("TARGET reached: equity %.2f - flattening and halting",
                        a.equity)
            self.flatten("target", now)
            self.st.halted = "profit target reached; review the phase on FTMO"
            return True
        return False

    def make_plan(self, now: datetime) -> None:
        today = now.astimezone(NY).date()
        ind, held_n = {}, {}
        for s, broker_sym in self.cfg.symbols.items():
            ss = sessions.build(self.b.bars(broker_sym, BAR_MINUTES, BAR_COUNT),
                                BAR_MINUTES, now)
            done = [x for x in ss if x.complete]
            if not done or done[-1].day != today:
                log.info("no completed %s session today (%s); no plan", s, today)
                return
            ind[s] = fast4.indicators(done)
            if s in self.st.held:
                entry = date.fromisoformat(self.st.held[s]["entry_day"])
                held_n[s] = sum(1 for x in done if x.day >= entry)
        p = fast4.plan(ind, held_n, self.cfg.max_positions,
                       self.cfg.max_hold_sessions)
        self.st.plan_day = today.isoformat()
        self.st.pending_exits, self.st.pending_entries = p.exits, p.entries
        self.st.pending_atr = p.atr
        log.info("plan for the next open: exits %s, entries %s", p.exits, p.entries)

    def execute(self, now: datetime, entries_ok: bool = True) -> None:
        today = now.astimezone(NY).date().isoformat()
        live = {self.by_broker.get(p.symbol): p for p in self.b.positions(self.cfg.magic)}
        for s in self.st.pending_exits:            # exits are never blocked
            if s in live:
                self._close(live[s], "exit", now)
                if not self.cfg.dry_run:
                    self.st.held.pop(s, None)
        if not entries_ok and self.st.pending_entries:
            log.warning("missed the open window; entries %s skipped",
                        self.st.pending_entries)
        for s in (self.st.pending_entries if entries_ok else []):
            a = self.b.account()
            open_n = len(self.b.positions(self.cfg.magic))
            blocked = bool(self.st.blocked_until or self.st.halted)
            why = rules.check_entry(a.equity, self.st.day_start_balance,
                                    self.limits, open_n,
                                    self.cfg.max_positions, blocked)
            if why:
                log.info("entry %s refused: %s", s, why)
                continue
            sym = self.cfg.symbols[s]
            spec = self.b.spec(sym)
            _, ask = self.b.quote(sym)
            stop = ask - self.cfg.atr_stop_mult * self.st.pending_atr[s]
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
            f = self.b.buy(sym, vol, stop, self.cfg.magic, "FAST4 entry")
            log.info("buy %s %.2f lots stop %.2f: %s", sym, vol, stop, f)
            if f.ok:
                self.st.held[s] = {"ticket": f.ticket, "entry_day": today}
                self._note_fill(now)
        self.st.executed_day = today

    def keepalive(self, now: datetime) -> None:
        if self.cfg.profit_target is None or self.cfg.keepalive_days <= 0:
            return
        ref = datetime.fromisoformat(self.st.last_fill)
        if now - ref < timedelta(days=self.cfg.keepalive_days):
            return
        local = now.astimezone(NY)
        if local.weekday() >= 5 or not time(10, 0) <= local.time() <= time(15, 30):
            return
        sym = self.cfg.symbols[self.cfg.keepalive_symbol]
        spec = self.b.spec(sym)
        if self.cfg.dry_run:
            log.info("DRY-RUN keep-alive: buy+close %s %.2f", sym, spec.volume_min)
            self.st.last_fill = now.isoformat()
            return
        f = self.b.buy(sym, spec.volume_min, None, self.cfg.magic, "FAST4 keepalive")
        if f.ok:
            for p in self.b.positions(self.cfg.magic):
                if p.ticket == f.ticket:
                    self.b.close(p, self.cfg.magic, "FAST4 keepalive")
            self._note_fill(now)
        log.info("keep-alive trade on %s: %s", sym, f)

    # ------------------------------------------------------------ tick
    def tick(self, now: Optional[datetime] = None) -> None:
        now = now or self.b.now()
        self.roll_day(now)
        if self.st.halted:
            self.st.save(self.path)
            return
        self.reconcile(now)
        if self.guard(now) or self.target(now):
            self.st.save(self.path)
            return
        local = now.astimezone(NY)
        today = local.date().isoformat()
        weekday = local.weekday() < 5
        if (weekday and local.time() >= CLOSE_AT and self.st.plan_day != today):
            self.make_plan(now)
        if (weekday and local.time() >= OPEN_AT and self.st.plan_day
                and self.st.plan_day < today and self.st.executed_day != today
                and local.time() < time(16, 0)):
            self.execute(now, entries_ok=local.time() <= ENTRY_DEADLINE)
        self.keepalive(now)
        self.st.save(self.path)

    def run(self, every: int = 60) -> None:    # pragma: no cover (loop)
        log.info("FTMO bot running (%s), risk %.1f%% per trade, symbols %s",
                 "DRY-RUN" if self.cfg.dry_run else "LIVE ORDERS",
                 self.cfg.risk_per_trade * 100, self.cfg.symbols)
        while True:
            try:
                self.tick()
            except Exception:                    # keep running; log the error
                log.exception("tick failed")
            if self.st.halted:
                log.warning("halted: %s", self.st.halted)
                return
            _time.sleep(every)
