"""Signal → order. The ONLY path to the market (SPEC "Module contracts").

Order of operations for every signal — there is no bypass flag:

1. refuse if ``state/HALT`` exists or the guard heartbeat is stale (> 10 s)
2. refuse if the idempotency key ``(symbol, session_date, side)`` was used
3. refuse if the guard has not written today's baseline
4. ``ftmo_rules.can_open`` with projected loss incl. spread + commission
5. ``sizing.size_for``
6. persist the idempotency key, THEN send the market order with server-side
   ``sl``/``tp`` (a crash after step 6 can never double-enter)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from ftmo_bot.config import FtmoProfile
from ftmo_bot.execution.mt5_client import MT5Client, PositionInfo
from ftmo_bot.execution.notify import Notifier
from ftmo_bot.execution.state import StateStore, idempotency_key
from ftmo_bot.risk import ftmo_rules, sizing
from ftmo_bot.risk.ftmo_rules import AccountState, Limits, OpenPosition
from ftmo_bot.strategy.base import Signal

log = logging.getLogger("ftmo_bot.router")


@dataclass(frozen=True)
class PlaceResult:
    placed: bool
    reason: str
    ticket: int = 0
    lots: float = 0.0


class OrderRouter:
    def __init__(
        self,
        client: MT5Client,
        store: StateStore,
        limits: Limits,
        profile: FtmoProfile,
        risk_amount: float,
        notifier: Notifier,
        clock: Callable[[], datetime],
    ) -> None:
        self.client = client
        self.store = store
        self.limits = limits
        self.profile = profile
        self.risk_amount = risk_amount
        self.notifier = notifier
        self.clock = clock
        self.instrument_of = {v: k for k, v in profile.mt5_symbols.items()}

    def open_positions(self, positions: list[PositionInfo]) -> tuple[OpenPosition, ...]:
        out = []
        for p in positions:
            name = self.instrument_of.get(p.symbol, p.symbol)
            spec = self.profile.contracts.get(name)
            if spec is None or p.sl <= 0:
                # Unknown instrument or no stop: count its whole notional as at risk.
                risk = float("inf")
            else:
                risk = sizing.risk_to_stop(p.side, p.volume, p.price_current, p.sl, spec)
            out.append(OpenPosition(name, p.side, risk))
        return tuple(out)

    def _reject(self, sig: Signal, reason: str) -> PlaceResult:
        log.info("rejected %s %s: %s", sig.symbol, sig.side, reason)
        self.notifier.send(f"REJECT {sig.symbol} {sig.side}: {reason}")
        return PlaceResult(False, reason)

    def place(self, sig: Signal, consecutive_losses: int) -> PlaceResult:
        now = self.clock()
        halt = self.store.read_halt()
        if halt is not None:
            return self._reject(sig, f"HALT ({halt.kind}): {halt.reason}")
        if not self.store.heartbeat_fresh(now, self.profile.heartbeat_stale_seconds):
            return self._reject(sig, "guard heartbeat stale or missing")
        session_date = sig.session_id.split(":", 1)[-1]
        key = idempotency_key(sig.symbol, session_date, sig.side)
        if self.store.has_key(key):
            return self._reject(sig, f"duplicate: {key} already used")
        baseline = self.store.load_baseline()
        if baseline is None or baseline.day != ftmo_rules.trading_day(now, self.limits.reset_tz):
            return self._reject(sig, "no baseline for today from the guard")

        spec = self.profile.contracts[sig.symbol]
        mt5_symbol = self.profile.mt5_symbols[sig.symbol]
        acct = self.client.account()
        tick = self.client.tick(mt5_symbol)
        state = AccountState(
            now_utc=now,
            equity=acct.equity,
            day_baseline=baseline.equity,
            overall_reference=self.limits.initial_balance,
            open_positions=self.open_positions(self.client.positions()),
            consecutive_losses_today=consecutive_losses,
        )
        projected = sizing.projected_loss(sig, spec, self.risk_amount, tick.ask - tick.bid)
        ok, reason = ftmo_rules.can_open(sig, state, self.limits, projected)
        if not ok:
            return self._reject(sig, reason)
        lots = sizing.size_for(sig, spec, self.risk_amount)
        if lots <= 0:
            return self._reject(sig, "size below min lot")

        self.store.add_key(key)  # persisted BEFORE the order leaves
        res = self.client.market_order(
            mt5_symbol,
            sig.side,
            lots,
            sl=sig.stop,
            tp=sig.target,
            magic=self.profile.magic,
            comment=key,
        )
        if not res.ok:
            self.notifier.send(f"ORDER FAILED {key} {lots} lots: {res.retcode} {res.comment}")
            return PlaceResult(False, f"order failed: {res.retcode} {res.comment}")
        self.notifier.send(
            f"ORDER {sig.symbol} {sig.side} {lots} lots @ {res.price} sl {sig.stop} tp "
            f"{sig.target} ({key})"
        )
        return PlaceResult(True, "placed", res.ticket, lots)
