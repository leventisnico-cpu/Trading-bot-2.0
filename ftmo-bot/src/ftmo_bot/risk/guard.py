"""Process 1 — the live kill switch (SPEC "Execution layer").

Runs as its own process with its OWN MT5 login and trusts nothing else to be
alive. Every ``poll_seconds``:

1. Read equity from ``account_info`` (never from fills).
2. Resolve today's 00:00 CE(S)T baseline: load it from disk if it is today's,
   otherwise snapshot it now (the first poll after midnight) and persist it.
3. ``ftmo_rules.should_halt`` with the ENGINE limits. On breach write
   ``state/HALT``; an overall breach supersedes a daily one. Daily halts are
   cleared at the next reset; overall halts only by a human.
4. While HALT exists: close every position and cancel every pending order, every
   poll, until flat. Backstops: Friday cutoff, and any position outside its
   instrument's session window (time exit / nothing held overnight).
5. Write ``state/heartbeat`` (only after a successful equity read, so a guard
   that has lost MT5 looks dead to the runner, which then refuses to open).

The rules arithmetic lives in ``ftmo_rules`` — the same code the backtest uses.
"""

from __future__ import annotations

import json
import logging
import time as _time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from ftmo_bot.config import (
    FtmoProfile,
    StrategyParams,
    flatten_time_utc,
    session_start_utc,
)
from ftmo_bot.execution.mt5_client import MT5Client, MT5Error, PositionInfo
from ftmo_bot.execution.notify import Notifier
from ftmo_bot.execution.state import HaltRecord, StateStore
from ftmo_bot.risk import ftmo_rules
from ftmo_bot.risk.ftmo_rules import AccountState, Limits

log = logging.getLogger("ftmo_bot.guard")


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class GuardTick:
    now_utc: datetime
    equity: float | None
    baseline: float | None
    halted: str | None = None
    closed: list[int] = field(default_factory=list)
    reason: str = ""


class Guard:
    def __init__(
        self,
        client: MT5Client,
        store: StateStore,
        limits: Limits,
        params: StrategyParams,
        profile: FtmoProfile,
        notifier: Notifier,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.client = client
        self.store = store
        self.limits = limits
        self.params = params
        self.profile = profile
        self.notifier = notifier
        self.clock = clock
        # MT5 symbol name -> internal instrument name
        self.instrument_of = {v: k for k, v in profile.mt5_symbols.items()}
        self._mt5_down_notified = False
        self._last_ping: datetime | None = None
        self._summary_sent_for: str | None = None
        self._prev_baseline: float | None = None

    # ------------------------------------------------------------ helpers

    def _in_window(self, pos: PositionInfo, now: datetime) -> bool:
        name = self.instrument_of.get(pos.symbol)
        inst = self.params.instruments.get(name) if name else None
        if inst is None:
            return False
        day = ftmo_rules.trading_day(now, self.params.timezone)
        return (
            session_start_utc(day, inst, self.params)
            <= now
            < flatten_time_utc(day, inst, self.params)
        )

    def _log(self, tick: GuardTick) -> None:
        log.info(
            json.dumps(
                {
                    "event": "guard_tick",
                    "now": tick.now_utc.isoformat(),
                    "equity": tick.equity,
                    "baseline": tick.baseline,
                    "daily_limit": self.limits.daily_loss_limit,
                    "overall_limit": self.limits.overall_loss_limit,
                    "halted": tick.halted,
                    "closed": tick.closed,
                    "reason": tick.reason,
                }
            )
        )

    # ------------------------------------------------------------ one poll

    def tick(self) -> GuardTick:
        now = self.clock()
        try:
            acct = self.client.account()
        except MT5Error as exc:
            if not self._mt5_down_notified:
                self.notifier.send(f"GUARD: MT5 unreachable ({exc}); heartbeat withheld")
                self._mt5_down_notified = True
            out = GuardTick(now, None, None, reason=f"mt5 down: {exc}")
            self._log(out)
            return out
        self._mt5_down_notified = False

        tz = self.params.timezone
        today = ftmo_rules.trading_day(now, tz)
        stored = self.store.load_baseline()
        baseline = ftmo_rules.resolve_baseline(stored, now, acct.equity, tz)
        if baseline is not stored:
            self._prev_baseline = stored.equity if stored else None
            self.store.save_baseline(baseline)
            self.notifier.send(
                f"GUARD: baseline {baseline.day} = {baseline.equity:,.2f}"
                + (" (LATE snapshot after restart)" if baseline.late else "")
            )
        if self.store.clear_daily_halt(today):
            self.notifier.send("GUARD: daily halt cleared at reset")

        state = AccountState(now, acct.equity, baseline.equity, self.limits.initial_balance)
        decision = ftmo_rules.should_halt(state, self.limits)
        halt = self.store.read_halt()
        if decision is not None and (
            halt is None or (halt.kind == "daily" and decision.kind.value == "overall")
        ):
            self.store.write_halt(HaltRecord(decision.kind.value, decision.reason, today, now))
            self.notifier.send(f"GUARD HALT ({decision.kind.value}): {decision.reason}")
            halt = self.store.read_halt()

        out = GuardTick(now, acct.equity, baseline.equity, halted=halt.kind if halt else None)
        try:
            positions = self.client.positions()
            if halt is not None:
                targets, out.reason = positions, f"HALT {halt.kind}"
                for ticket in self.client.pending_orders():
                    self.client.cancel_order(ticket)
            elif ftmo_rules.past_friday_cutoff(now, self.limits):
                targets, out.reason = positions, "friday cutoff"
            else:
                targets = [p for p in positions if not self._in_window(p, now)]
                out.reason = "outside session window" if targets else "ok"
            for p in targets:
                res = self.client.close_position(p, comment=f"guard:{out.reason}"[:31])
                if res.ok:
                    out.closed.append(p.ticket)
                else:
                    self.notifier.send(
                        f"GUARD: close {p.symbol} #{p.ticket} failed "
                        f"({res.retcode} {res.comment}); retrying next poll"
                    )
            if out.closed:
                self.notifier.send(f"GUARD flattened {out.closed} ({out.reason})")
        except MT5Error as exc:
            out.reason = f"flatten error: {exc}"
            self.notifier.send(f"GUARD: {out.reason}")

        self.store.write_heartbeat(now)
        self._daily_summary(now, acct.equity, baseline.equity)
        if self._last_ping is None or now - self._last_ping >= timedelta(seconds=60):
            self.notifier.ping()
            self._last_ping = now
        self._log(out)
        return out

    def _daily_summary(self, now: datetime, equity: float, baseline: float) -> None:
        local = ftmo_rules.to_local(now, self.params.timezone)
        key = local.date().isoformat()
        if local.time() < self.profile.daily_summary_time or self._summary_sent_for == key:
            return
        self._summary_sent_for = key
        reset = ftmo_rules.last_reset_utc(now, self.params.timezone)
        try:
            trades = self.client.deals_between(reset - timedelta(days=1), reset)
        except Exception:
            trades = -1
        prev = self._prev_baseline
        day_pnl = f"{baseline - prev:+,.2f}" if prev is not None else "n/a"
        daily_room = equity - (baseline - self.limits.daily_loss_limit)
        overall_room = equity - (self.limits.initial_balance - self.limits.overall_loss_limit)
        self.notifier.send(
            f"DAILY {key}: equity {equity:,.2f} | yesterday P&L {day_pnl} | "
            f"entries yesterday {trades} | room to daily limit {daily_room:,.2f} | "
            f"room to overall limit {overall_room:,.2f}"
        )

    # ------------------------------------------------------------ loop

    def run(
        self, max_iterations: int | None = None, sleep: Callable[[float], None] = _time.sleep
    ) -> None:
        self.notifier.send("GUARD started")
        n = 0
        while max_iterations is None or n < max_iterations:
            self.tick()
            n += 1
            if max_iterations is None or n < max_iterations:
                sleep(self.profile.poll_seconds)
