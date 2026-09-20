"""Multi-signal ensemble: several independent strategies must agree to enter.

Why not LLM agents in the trade path
------------------------------------
Multi-agent LLM trading frameworks (TradingAgents and its descendants) model
a desk as analysts who debate and a risk manager who rules. The structural
insight is real and worth taking: *independent* views, combined with an
explicit agreement requirement, beat one view acting alone.

Putting literal LLM agents inside this bot's order path would not work, for
reasons specific to what it trades:

* **Latency.** A debate among agents costs seconds to minutes. On one-minute
  futures bars the signal is stale before the call returns.
* **Non-determinism.** The same bar can yield different decisions on
  different runs, so a failure cannot be reproduced — fatal for a system
  whose safety rests on regression tests and mutation testing.
* **Hallucination in the order path.** A confident, wrong number reaching
  order submission is exactly the failure class the risk layer exists to
  prevent, and it cannot be unit-tested away.
* **Cost.** Per-bar inference on a 23-hour session is thousands of calls a
  day to decide whether to hold one micro contract.

LLM agents are genuinely valuable *around* this loop — proposing strategies
to test, critiquing a diff, summarizing a session's fills — where seconds of
latency are free and a human reads the output before anything trades. What
belongs *in* the loop is the deterministic core of the idea, which is this
module.

Asymmetric voting
-----------------
Entry requires ``min_agreement`` members to signal simultaneously. Exit
requires only **one** member to call it. That asymmetry is deliberate: being
slow to take risk is cheap, and being slow to shed it is how accounts die.
Size is the *minimum* any agreeing member proposed, never the maximum.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Sequence

from ..core.types import Action, Bar, IntentSource, OrderIntent, OrderType
from .base import BaseStrategy

log = logging.getLogger(__name__)


class EnsembleStrategy(BaseStrategy):
    """Combines independent member strategies under an agreement rule."""

    strategy_id = "ensemble"

    def __init__(
        self,
        symbol: str,
        members: Sequence[BaseStrategy],
        min_agreement: int = 2,
        quantity: Optional[int] = None,
    ) -> None:
        """
        Args:
            symbol: the traded symbol; every member must agree on it.
            members: independent strategies. Two members correlated by
                construction (the same indicator at two lengths) do not
                provide two views — agreement between them means little.
            min_agreement: members that must signal BUY on the same bar.
                Must be >= 1 and <= len(members).
            quantity: fixed entry size. When None, the minimum size proposed
                by the agreeing members is used.
        """
        super().__init__()
        if not members:
            raise ValueError("ensemble needs at least one member strategy")
        # Structural errors first: a member trading the wrong instrument is
        # a deeper misconfiguration than a threshold that needs adjusting,
        # and reporting the threshold first would mask it.
        mismatched = [m.strategy_id for m in members
                      if m.symbol and m.symbol != symbol]
        if mismatched:
            raise ValueError(
                f"member(s) {mismatched} trade a different symbol than "
                f"the ensemble's {symbol!r}")
        if not 1 <= min_agreement <= len(members):
            raise ValueError(
                f"min_agreement must be in [1, {len(members)}], "
                f"got {min_agreement}")
        if quantity is not None and quantity < 1:
            raise ValueError("quantity must be >= 1 when specified")
        self.symbol = symbol
        self.members = list(members)
        self.min_agreement = min_agreement
        self.quantity = quantity
        #: Per-bar record of which members voted to enter, for diagnosis.
        self.last_votes: List[str] = []

    @property
    def warmup_bars(self) -> int:
        """The slowest member governs: the ensemble is not warm until every
        member can be trusted."""
        return max(m.warmup_bars for m in self.members)

    def compute_signals(self, bar: Bar) -> List[OrderIntent]:
        buy_votes: List[tuple[str, int]] = []
        sell_callers: List[str] = []

        for member in self.members:
            for intent in member.on_bar(bar):
                if intent.action is Action.BUY:
                    buy_votes.append((member.strategy_id, intent.quantity))
                else:
                    sell_callers.append(member.strategy_id)

        self.last_votes = [name for name, _ in buy_votes]

        # Exit first, and on a single voice. Shedding risk is never gated
        # on consensus.
        if sell_callers and self.position > 0:
            return [OrderIntent(
                action=Action.SELL, symbol=self.symbol,
                quantity=self.position, order_type=OrderType.MARKET,
                source=IntentSource.STRATEGY, strategy_id=self.strategy_id,
                reason=f"exit called by {', '.join(sorted(set(sell_callers)))}")]

        if self.position != 0 or len(buy_votes) < self.min_agreement:
            if buy_votes and self.position == 0:
                log.debug("ensemble: %d/%d votes, holding off (%s)",
                          len(buy_votes), self.min_agreement,
                          ", ".join(self.last_votes))
            return []

        qty = (self.quantity if self.quantity is not None
               else min(q for _, q in buy_votes))
        if qty < 1:
            return []
        return [OrderIntent(
            action=Action.BUY, symbol=self.symbol, quantity=qty,
            order_type=OrderType.MARKET, source=IntentSource.STRATEGY,
            strategy_id=self.strategy_id,
            reason=(f"{len(buy_votes)}/{len(self.members)} agreement "
                    f"({', '.join(self.last_votes)}), size {qty}"))]

    def on_own_fill(self, signed_quantity: int, price: float) -> None:
        """Mirror fills to every member so their internal position state
        matches reality — a member that believes it is flat while the
        ensemble is long would keep proposing entries."""
        super().on_own_fill(signed_quantity, price)
        for member in self.members:
            member.on_own_fill(signed_quantity, price)
