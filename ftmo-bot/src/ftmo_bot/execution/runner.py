"""Process 2 — the strategy runner (``ftmo-bot live`` / ``ftmo-bot paper``).

- Refuses to start if the guard heartbeat is older than 10 s or HALT exists.
- On each completed 15m bar: ``strategy.on_bar`` → ``OrderRouter.place``
  (which runs ``ftmo_rules.can_open`` → ``sizing.size_for`` → order).
- Stops and targets live server-side on the order. The runner's only
  modification is the one breakeven move at 1 R, then the position is left alone.
- Time exit (15 min before session end) and Friday flatten are done here; the
  guard enforces both again as a backstop.
- After a restart the strategy is re-warmed from the terminal's bar history;
  signals from bars older than ``signal_max_age_seconds`` are never traded and
  the idempotency key blocks re-entry into a session already traded.
"""

from __future__ import annotations

import logging
import time as _time
from collections.abc import Callable
from datetime import datetime

from ftmo_bot.config import FtmoProfile, StrategyParams, flatten_time_utc
from ftmo_bot.execution.mt5_client import MT5Client, PositionInfo
from ftmo_bot.execution.notify import Notifier
from ftmo_bot.execution.order_router import OrderRouter
from ftmo_bot.execution.state import StateStore
from ftmo_bot.risk import ftmo_rules
from ftmo_bot.risk.ftmo_rules import Limits
from ftmo_bot.strategy.base import Bar, Strategy

log = logging.getLogger("ftmo_bot.runner")


class RefuseToStart(RuntimeError):
    pass


class Runner:
    def __init__(
        self,
        client: MT5Client,
        store: StateStore,
        router: OrderRouter,
        strategy: Strategy,
        params: StrategyParams,
        profile: FtmoProfile,
        limits: Limits,
        notifier: Notifier,
        clock: Callable[[], datetime],
        require_demo: bool = False,
    ) -> None:
        self.client = client
        self.store = store
        self.router = router
        self.strategy = strategy
        self.params = params
        self.profile = profile
        self.limits = limits
        self.notifier = notifier
        self.clock = clock
        self.require_demo = require_demo
        self._last_bar: dict[str, datetime] = {}

    # ------------------------------------------------------------ startup

    def preflight(self) -> None:
        now = self.clock()
        halt = self.store.read_halt()
        if halt is not None:
            raise RefuseToStart(f"state/HALT exists ({halt.kind}): {halt.reason}")
        if not self.store.heartbeat_fresh(now, self.profile.heartbeat_stale_seconds):
            age = self.store.heartbeat_age(now)
            raise RefuseToStart(
                "guard heartbeat missing" if age is None else f"guard heartbeat {age:.1f}s old"
            )
        acct = self.client.account()
        if self.require_demo and not acct.is_demo:
            raise RefuseToStart(f"paper mode requires a demo account; login {acct.login} is not")

    # ------------------------------------------------------------ one step

    def _ours(self) -> list[PositionInfo]:
        return [p for p in self.client.positions() if p.magic == self.profile.magic]

    def _flatten_due(self, pos: PositionInfo, now: datetime) -> str | None:
        if ftmo_rules.past_friday_cutoff(now, self.limits):
            return "friday"
        name = self.router.instrument_of.get(pos.symbol)
        inst = self.params.instruments.get(name) if name else None
        if inst is None:
            return "unknown instrument"
        day = ftmo_rules.trading_day(now, self.params.timezone)
        if now >= flatten_time_utc(day, inst, self.params):
            return "time"
        return None

    def step(self) -> None:
        now = self.clock()
        st = self.store.load_runner()
        today = ftmo_rules.trading_day(now, self.params.timezone)
        if st.day != today:
            st.day = today
            st.consecutive_losses = 0

        ours = self._ours()
        open_tickets = {p.ticket for p in ours}
        for ticket in list(st.known_tickets):
            if ticket in open_tickets:
                continue
            pnl = self.client.closed_pnl(ticket)
            if pnl is None:
                continue  # history not yet visible; check again next step
            st.consecutive_losses = st.consecutive_losses + 1 if pnl < 0 else 0
            st.known_tickets.remove(ticket)
            st.original_stops.pop(str(ticket), None)
            if ticket in st.breakeven_done:
                st.breakeven_done.remove(ticket)
            self.notifier.send(
                f"CLOSED #{ticket} pnl {pnl:+,.2f} "
                f"(consecutive losses today: {st.consecutive_losses})"
            )
        for p in ours:
            if p.ticket not in st.known_tickets:
                st.known_tickets.append(p.ticket)
                st.original_stops[str(p.ticket)] = p.sl
        self.store.save_runner(st)

        for p in ours:
            reason = self._flatten_due(p, now)
            if reason is not None:
                res = self.client.close_position(p, comment=f"runner:{reason}")
                self.notifier.send(
                    f"FLATTEN {p.symbol} #{p.ticket} ({reason}): {'ok' if res.ok else res.comment}"
                )
                continue
            self._maybe_breakeven(p, st.original_stops.get(str(p.ticket), p.sl), st.breakeven_done)
        self.store.save_runner(st)

        for name in self.params.instruments:
            self._process_bars(name, now, st.consecutive_losses)

    def _maybe_breakeven(self, p: PositionInfo, orig_sl: float, done: list[int]) -> None:
        if p.ticket in done:
            return
        if p.sl == p.price_open:
            done.append(p.ticket)  # already moved (e.g. before a restart)
            return
        r = abs(p.price_open - orig_sl)
        if r <= 0:
            return
        move = (
            p.price_current - p.price_open if p.side == "long" else p.price_open - p.price_current
        )
        if move >= self.params.breakeven_r * r:
            res = self.client.modify_sl(p, p.price_open)
            if res.ok:
                done.append(p.ticket)
                self.notifier.send(f"BREAKEVEN {p.symbol} #{p.ticket} sl -> {p.price_open}")

    def _process_bars(self, name: str, now: datetime, consecutive_losses: int) -> None:
        sym = self.profile.mt5_symbols[name]
        bars = self.client.completed_bars(sym, self.params.bar_minutes, 120)
        if not bars:
            return
        h4 = [
            Bar(name, b.ts_utc, b.open, b.high, b.low, b.close, b.minutes)
            for b in self.client.completed_bars(
                sym, self.params.trend_minutes, self.params.h4_lookback
            )
        ]
        last = self._last_bar.get(name)
        for b in bars:
            if last is not None and b.ts_utc <= last:
                continue
            bar = Bar(name, b.ts_utc, b.open, b.high, b.low, b.close, b.minutes)
            sig = self.strategy.on_bar(bar, h4)
            if sig is None:
                continue
            age = (now - bar.close_ts).total_seconds()
            if age > self.profile.signal_max_age_seconds:
                log.info("stale signal ignored (%ss): %s", age, sig)
                continue
            if not self.client.symbol_tradeable(sym, now):
                self.notifier.send(f"SKIP {name}: market closed / no fresh quote")
                continue
            self.router.place(sig, consecutive_losses)
        self._last_bar[name] = bars[-1].ts_utc

    # ------------------------------------------------------------ loop

    def run(
        self,
        poll_seconds: float = 2.0,
        max_iterations: int | None = None,
        sleep: Callable[[float], None] = _time.sleep,
    ) -> None:
        self.preflight()
        self.notifier.send("RUNNER started")
        n = 0
        while max_iterations is None or n < max_iterations:
            try:
                self.step()
            except Exception as exc:
                log.exception("runner step failed")
                self.notifier.send(f"RUNNER error: {exc}")
            n += 1
            sleep(poll_seconds)
