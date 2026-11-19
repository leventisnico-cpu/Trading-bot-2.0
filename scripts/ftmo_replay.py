#!/usr/bin/env python3
"""Replay the real FTMO bot over years of daily bars and audit every action.

The same ``ftmo_bot.Runner`` the MT5 bot runs trades a ``SimBroker`` (as in
``scripts/ftmo_shadow.py``) on the study's daily exports. Each session is
fed as 13 half-hour bars: one flat bar at the open, then a monotone walk
open -> first extreme -> second extreme -> close that passes exactly
through every open position's next targets, so the polling bot sees what
a resting order would have seen. ``--order`` picks which extreme comes
first (``low_first`` is the unfavourable one for a long position).

An account that halts (the max-loss guard; in ``challenge`` mode also the
reached target) is replaced by a fresh one the next session, so one run is
a chain of accounts over the whole history. So is an account the bot
reports FROZEN (flat, with no room left over the max-loss line and its
buffer: it can open nothing more), as the operator would replace it.

Checked on every run; a mismatch is a bug in the bot or in this script:

* the plan after each close, against FAST-4 computed from the daily arrays
  of ``research/ftmo_fast_pass.py`` (signal, priority, slots);
* every entry: the signal, a slot for it, the stop 3 x ATR under the fill,
  and the size (3% risk, the combined-risk cap with its two buffers, the
  notional cap);
* every 5-step trade, deal by deal, against an independent oracle (part
  closes, stop moves, the trail, the stop-out);
* invariants: at most two positions taking a slot and one per index, a stop
  never lowered, a volume never raised, the balance equal to the initial
  balance plus the deals' P&L; no planned entry refused for want of a slot;
  the bot says FROZEN when, and only when, the account is.

``--slots free`` (the bot's default, ``free_slots``): a position whose stop
is at or over its entry takes no slot. ``--slots all``: every open position
takes one (the rule before 2026-11-10).

    python -B scripts/ftmo_replay.py --data-dir DIR [--mode funded|challenge]
        [--order low_first|high_first] [--slots free|all] [--start YYYY-MM-DD]
        [--end YYYY-MM-DD] [--report FILE] [--json FILE]

DIR holds ``qqq_long.csv``, ``spy_long.csv``, ``dia_long.csv`` and
``iwm_long.csv``. Exit code 1 if anything mismatched. Costs are zero here
(no spread, no financing): this audits the bot's actions, not its returns.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import math
import sys
import tempfile
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ftmo_bot import runner as runner_mod  # noqa: E402
from ftmo_bot.broker_sim import BAR, SimBroker  # noqa: E402
from ftmo_bot.config import FtmoConfig  # noqa: E402
from ftmo_bot.runner import Runner  # noqa: E402

NY = ZoneInfo("America/New_York")
PROXY = {"US100": "QQQ", "US500": "SPY", "US30": "DIA", "US2000": "IWM"}
STUDY = {"US100": "US100 (QQQ)", "US500": "US500 (SPY)", "US30": "US30 (DIA)",
         "US2000": "US2000 (IWM)"}
INITIAL = 15000.0
SESSION_BARS = 13                 # 09:30 ... 15:30 starts
HISTORY = 320                     # sessions the bot sees, like 15,000 CFD half-hours
POLL = timedelta(minutes=5)       # the bot looks 5 minutes after each bar ends
STEP = 0.01                       # SimBroker's volume step and minimum
# the 5 steps, restated here on purpose (not imported from the bot)
TP1, TP2, HALF, THREE_QUARTERS = 1.0, 1.5, Decimal("0.5"), Decimal("0.75")
RISK, ATR_MULT, NOTIONAL_CAP = 0.03, 3.0, 3.0
SLOTS = 2                         # positions that may take a slot at once
DAILY, MAX_LOSS, DAILY_PAD, MAX_LOSS_PAD = 0.05, 0.10, 0.002, 0.015
# a flat account with no more room than this over the max-loss line and its
# buffer (0.05% of the initial balance) is frozen: it can open nothing more
FROZEN_AT = ((1 - MAX_LOSS) + MAX_LOSS_PAD + 0.0005) * INITIAL
ACCOUNT_CLOSES = ("guard", "target", "halted", "stand-down", "retry")
Event = Tuple[str, datetime, float, float]        # kind, time, volume, price


def load_study(data_dir: Path):
    spec = importlib.util.spec_from_file_location(
        "ftmo_fast_pass", ROOT / "research" / "ftmo_fast_pass.py")
    base = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules.setdefault("ftmo_fast_pass", base)
    spec.loader.exec_module(base)
    return base.load_all(data_dir)


def bar_start(d: date, k: int) -> datetime:
    return (datetime.combine(d, time(9, 30), NY) + k * BAR).astimezone(timezone.utc)


def waypoints(o: float, h: float, l: float, c: float, order: str,
              levels: Sequence[float]) -> List[float]:
    """Closes of the bars after the opening bar: open -> first extreme ->
    second extreme -> close, through each target in ``levels`` on the first
    rise that reaches it (a hair above it, so the bid counts as there)."""
    def rise(a: float, b: float) -> List[float]:
        return [math.nextafter(x, math.inf) for x in sorted(levels) if a < x <= b]
    if order == "low_first":
        return [l] + rise(l, h) + [h, c]
    return rise(o, h) + [h, l, c]


def session_bars(d: date, o: float, ws: Sequence[float]) -> List[tuple]:
    """Bar 0 flat at the open, then one monotone bar per waypoint, then
    flat at the close."""
    assert 1 <= len(ws) <= SESSION_BARS - 1, ws
    ws = list(ws) + [ws[-1]] * (SESSION_BARS - 1 - len(ws))
    out, prev = [(bar_start(d, 0), o, o, o, o)], o
    for k, w in enumerate(ws, start=1):
        out.append((bar_start(d, k), prev, max(prev, w), min(prev, w), w))
        prev = w
    return out


def keep_after(vol0: float, stage: int) -> float:
    """Lots left open once ``stage``'s share of the first volume is sold:
    1/2 then 3/4 in all, rounded half up to the lot step; a target never
    sells the last lot."""
    share = {1: HALF, 2: THREE_QUARTERS}[stage]
    first = Decimal(str(round(vol0, 2)))
    sold = (first * share).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(max(first - sold, Decimal("0.01")))


def five_steps(bars: Sequence[tuple], entry: float, stop0: float,
               vol0: float) -> List[Event]:
    """The deals the 5 steps call for on ``bars`` (those after the entry
    bar): a resting stop fills first, at its price or at the bar's open if
    the bar opened through it; then the bot polls the bar's close."""
    r = entry - stop0
    stop, stage, vol, hc = stop0, 0, vol0, None
    out: List[Event] = []
    for start, o, h, l, c, last in bars:
        end = start + BAR
        if l <= stop:
            out.append(("sell", end, vol, min(o, stop)))
            return out
        st = 2 if c >= entry + TP2 * r else 1 if c >= entry + TP1 * r else 0
        if st > stage:
            sell = round(vol - keep_after(vol0, st), 8)
            if sell >= STEP - 1e-9:
                out.append(("sell", end + POLL, sell, c))
                vol = round(vol - sell, 8)
            floor = entry if st == 1 else max(entry + TP1 * r,
                                              -math.inf if hc is None else hc - r)
            if floor > stop:
                out.append(("sl", end + POLL, vol, floor))
                stop = floor
            stage = st
        if last:                                   # the session closed: the trail
            hc = c if hc is None else max(hc, c)
            if stage == 2 and max(entry + TP1 * r, hc - r) > stop:
                stop = max(entry + TP1 * r, hc - r)
                out.append(("sl", end + POLL, vol, stop))
    return out


def takes_slot(p, free_slots: bool) -> bool:
    """The slot rule, restated: every open position takes one of the two
    slots, except, with free slots, one whose stop is at or over its entry
    price (the 5 steps moved it there; it can no longer lose against its
    entry unless the price gaps through the stop)."""
    return not (free_slots and p.sl and p.sl >= p.price_open)


def expected_volume(balance: float, day_start: float, others: Sequence,
                    entry: float, stop: float) -> float:
    """3% of the balance at risk, capped by 3x notional and by the room the
    open stops leave above both loss lines; rounded down to the lot step."""
    per_lot = entry - stop
    v = min(RISK * balance / per_lot, NOTIONAL_CAP * balance / entry, 1000.0)
    v = math.floor(v / STEP + 1e-9) * STEP
    committed = sum(max(0.0, p.price_open - p.sl) * p.volume for p in others if p.sl)
    worst = balance - committed
    room = max(0.0, min(worst - (day_start - DAILY * INITIAL + DAILY_PAD * INITIAL),
                        worst - ((1 - MAX_LOSS) * INITIAL + MAX_LOSS_PAD * INITIAL)))
    fit = math.floor(room / per_lot / STEP + 1e-9) * STEP
    return round(min(v, fit), 8)


class Keep(logging.Handler):
    """Warnings and the bot's lines about entries, for the report."""

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.lines: List[Tuple[int, str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        if record.levelno >= logging.WARNING or msg.startswith("entry "):
            self.lines.append((record.levelno, msg))


class Replay:
    def __init__(self, dates, inst, mode: str, order: str, workdir: Path,
                 history: int = HISTORY, slots: str = "free") -> None:
        assert slots in ("free", "all"), slots
        self.dates, self.inst, self.mode, self.order = dates, inst, mode, order
        self.workdir, self.history, self.free = workdir, history, slots == "free"
        self.keep = (history + 3) * SESSION_BARS
        self.days = [pd.Timestamp(d).date() for d in dates]
        self.data: Dict[str, list] = {p: [] for p in PROXY.values()}
        self.archive: Dict[str, list] = {p: [] for p in PROXY.values()}
        self.problems: List[str] = []
        self.attempts: List[dict] = []
        self.trades: List[dict] = []
        self.count = dict(sessions=0, plans=0, entries=0, events=0, keepalives=0,
                          refused=0, ticks=0, beyond_two=0, max_open=0)
        self.crossed: List[Tuple[date, str]] = []     # sessions under an FTMO line
        self.log = Keep()
        self.sim: Optional[SimBroker] = None
        self.r: Optional[Runner] = None
        self.ctx: List[dict] = []
        self.k = 0

    # ------------------------------------------------------------ feeding
    def feed(self, sym: str, bars: List[tuple]) -> None:
        if self.sim is not None and self.sim.data is self.data:
            self.sim.ends[sym].extend(b[0] + BAR for b in bars)
        self.data[sym].extend(bars)
        self.archive[sym].extend(bars)
        if self.sim is not None and len(self.data[sym]) > self.keep + 20 * SESSION_BARS:
            del self.data[sym][:-self.keep]
            del self.sim.ends[sym][:-self.keep]

    def bars_of(self, i: int, s: str, levels: Sequence[float]) -> List[tuple]:
        x = self.inst[STUDY[s]]
        o, h, l, c = (float(x[k][i]) for k in "ohlc")
        return session_bars(self.days[i], o, waypoints(o, h, l, c, self.order, levels))

    def next_levels(self, s: str) -> List[float]:
        """The targets ``s``'s open position has not reached yet."""
        h = self.r.st.held.get(s)
        if not h or h.get("exit") != "scale_out":
            return []
        p = next((p for p in self.sim.pos if p.ticket == h.get("ticket")), None)
        if p is None:
            return []
        r = p.price_open - h["stop0"]
        stage = int(h.get("stage", 0))
        return [p.price_open + m * r for m, need in ((TP1, 1), (TP2, 2)) if stage < need]

    # ----------------------------------------------------------- accounts
    def open_account(self, t0: datetime) -> None:
        self.k += 1
        self.sim = SimBroker(self.data, None, balance=INITIAL, half_spread=0.0)
        self.sim.clock = t0
        cfg = FtmoConfig(
            symbols=dict(PROXY), dry_run=False, initial_balance=INITIAL,
            exit_mode="scale_out", free_slots=self.free,
            profit_target=None if self.mode == "funded" else 0.10,
            state_path=str(self.workdir / f"account{self.k}" / "bot_state.json"),
            log_path=str(self.workdir / "bot.log"))
        cfg.validate()
        self.r = Runner(cfg, self.sim)
        self.ctx = []
        sim, ctx, me = self.sim, self.ctx, self
        buy = sim.buy

        def recording_buy(symbol, volume, sl, magic, comment):
            ctx.append(dict(ticket=sim.next_ticket, symbol=symbol, volume=volume, sl=sl,
                            comment=comment, time=sim.clock, ask=sim.quote(symbol)[1],
                            balance=sim.balance, others=list(sim.pos),
                            day_start=me.r.st.day_start_balance))
            return buy(symbol, volume, sl, magic, comment)
        sim.buy = recording_buy
        self.account = dict(k=self.k, opened=t0, first=None, stops={}, vols={})

    def close_account(self, why: str, i: int) -> None:
        self.check_account(i)
        self.attempts.append(dict(account=self.k, opened=self.account["opened"].date(),
                                  closed=self.days[i], why=why,
                                  balance=round(self.sim.balance, 2),
                                  trading_days=len(self.r.st.trading_days)))
        self.sim = self.r = None

    def frozen(self) -> bool:
        """Flat, and the balance leaves no room over the max-loss line and
        its buffer: nothing can be opened, so the balance cannot rise."""
        return not self.sim.pos and self.sim.balance <= FROZEN_AT

    # -------------------------------------------------------------- ticks
    def tick(self, d: date, at: time) -> None:
        t = datetime.combine(d, at, NY)
        prev = self.sim.clock
        self.sim.advance_to(t)
        low = self.sim.low_equity(prev)
        self.r.tick(t)
        self.count["ticks"] += 1
        self.day_low = min(self.day_low, low, self.sim.account().equity)
        used = sum(takes_slot(p, self.free) for p in self.sim.pos)
        if used > SLOTS or len({p.symbol for p in self.sim.pos}) < len(self.sim.pos):
            self.problems.append(f"{t}: {len(self.sim.pos)} positions open, {used} of them "
                                 f"taking a slot: {[p.symbol for p in self.sim.pos]}")
        self.count["max_open"] = max(self.count["max_open"], len(self.sim.pos))
        for p in self.sim.pos:                       # stops only up, volumes only down
            s0 = self.account["stops"].get(p.ticket)
            v0 = self.account["vols"].get(p.ticket)
            if s0 is not None and p.sl < s0 - 1e-12:
                self.problems.append(f"{t}: ticket {p.ticket} stop lowered {s0} -> {p.sl}")
            if v0 is not None and p.volume > v0 + 1e-9:
                self.problems.append(f"{t}: ticket {p.ticket} volume raised {v0} -> {p.volume}")
            self.account["stops"][p.ticket] = p.sl
            self.account["vols"][p.ticket] = p.volume

    def session(self, i: int) -> None:
        d = self.days[i]
        if self.sim is None:
            self.open_account(datetime.combine(d, time(9, 0), NY))
        first = {s: self.bars_of(i, s, ()) for s in PROXY}     # only bar 0 is used
        for s in PROXY:
            self.feed(PROXY[s], first[s][:1])
        was_frozen, seen = self.frozen(), len(self.log.lines)
        self.day_low = math.inf
        self.tick(d, time(9, 35))
        day_start = self.r.st.day_start_balance
        self.tick(d, time(10, 5))
        for s in PROXY:
            self.feed(PROXY[s], self.bars_of(i, s, self.next_levels(s))[1:])
        t = datetime.combine(d, time(10, 35))
        while t.time() <= time(16, 5):
            self.tick(d, t.time())
            t += timedelta(minutes=30)
        self.count["sessions"] += 1
        if self.day_low <= (1 - MAX_LOSS) * INITIAL:
            self.crossed.append((d, "max-loss"))
        elif self.day_low <= day_start - DAILY * INITIAL:
            self.crossed.append((d, "daily"))
        self.check_plan(i)
        said = [m for _, m in self.log.lines[seen:]      # entries not taken this session
                if m.startswith("entry ") and ("skipped" in m or "refused" in m)]
        told = any("FROZEN" in m for m in said)
        if was_frozen and any("FROZEN" not in m for m in said):
            self.problems.append(f"{d}: the account was frozen but the bot said {said}")
        if told and not self.frozen():
            self.problems.append(f"{d}: the bot said FROZEN with room left: {said}")
        if self.r.st.halted and not self.sim.pos:
            self.close_account(self.r.st.halted, i)
        elif told and self.frozen():
            self.close_account("frozen: no room left over the max-loss line and its "
                               "buffer", i)

    # ------------------------------------------------------------- checks
    def check_plan(self, i: int) -> None:
        st = self.r.st
        if st.plan_day != self.days[i].isoformat():
            return                                   # no plan made (halted, locked, blocked)
        self.count["plans"] += 1
        held = set(st.held)
        cands = []
        for s in PROXY:
            x = self.inst[STUDY[s]]
            if s in held or np.isnan(x["sma200"][i]):
                continue
            if x["c"][i] > x["sma200"][i] and x["rsi"][i] < 10:
                cands.append((float(x["rsi"][i]), s))
        used = sum(takes_slot(p, self.free) for p in self.sim.pos)
        want = [s for _, s in sorted(cands)[:max(0, SLOTS - used)]]
        if st.pending_entries != want or st.pending_exits:
            self.problems.append(f"{self.days[i]}: plan {st.pending_entries} exits "
                                 f"{st.pending_exits}, expected {want} and no exits")

    def check_account(self, i_last: int) -> None:
        """Every entry and every 5-step trade of the account just ended."""
        sim, by_symbol = self.sim, {v: k for k, v in PROXY.items()}
        pnl = sum(x.get("pnl", 0.0) for x in sim.deals)
        if abs(sim.balance - INITIAL - pnl) > 0.01 * max(1, len(sim.deals)):
            self.problems.append(f"account {self.k}: balance {sim.balance:.2f} is not "
                                 f"{INITIAL:.0f} + deals {pnl:.2f}")
        last_tick = datetime.combine(self.days[i_last], time(16, 5), NY)
        deals: Dict[int, list] = {}
        for x in sim.deals:
            deals.setdefault(x["ticket"], []).append(x)
        day_index = {d: j for j, d in enumerate(self.days)}
        for c in self.ctx:
            mine = deals.get(c["ticket"], [])
            if not c["comment"].endswith("entry"):
                self.count["keepalives"] += 1
                if c["sl"] or len(mine) != 2 or abs(mine[1]["volume"] - c["volume"]) > 1e-9:
                    self.problems.append(f"round trip {c['time']}: {mine}")
                continue
            self.count["entries"] += 1
            s, sym = by_symbol[c["symbol"]], c["symbol"]
            i = day_index[c["time"].astimezone(NY).date()]
            x = self.inst[STUDY[s]]
            where = f"account {self.k} {self.days[i]} {s}"
            if not (x["c"][i - 1] > x["sma200"][i - 1] and x["rsi"][i - 1] < 10):
                self.problems.append(f"{where}: entry without a FAST-4 signal")
            used = sum(takes_slot(p, self.free) for p in c["others"])
            if used >= SLOTS or any(p.symbol == sym for p in c["others"]):
                self.problems.append(f"{where}: entry without a slot ({used} of the "
                                     f"{len(c['others'])} open positions take one)")
            self.count["beyond_two"] += len(c["others"]) >= SLOTS
            stop = c["ask"] - ATR_MULT * float(x["atr"][i - 1])
            if abs(c["sl"] - stop) > 1e-7 * c["ask"]:
                self.problems.append(f"{where}: stop {c['sl']} is not ask - 3 ATR = {stop}")
            want = expected_volume(c["balance"], c["day_start"], c["others"], c["ask"], c["sl"])
            if abs(c["volume"] - want) > 1e-6:
                self.problems.append(f"{where}: {c['volume']} lots, expected {want}")
            if c["volume"] * (c["ask"] - c["sl"]) > RISK * c["balance"] + 1e-6:
                self.problems.append(f"{where}: risks over 3% of the balance")
            self.check_trade(where, sym, c, mine[1:], last_tick)

    def check_trade(self, where: str, sym: str, c: dict, mine: list,
                    last_tick: datetime) -> None:
        entry_bar = bar_start(c["time"].astimezone(NY).date(), 0)
        bars = [(b[0], b[1], b[2], b[3], b[4],
                 (b[0] + BAR).astimezone(NY).time() == time(16, 0))
                for b in self.archive[sym] if b[0] > entry_bar and b[0] + BAR + POLL <= last_tick]
        want = five_steps(bars, c["ask"], c["sl"], c["volume"])
        got: List[Event] = []
        ended_by = "open at the end"
        for x in mine:
            t = datetime.fromisoformat(x["time"])
            if x["side"] == "sl":
                got.append(("sl", t, x["volume"], x["price"]))
                continue
            got.append(("sell", t, x["volume"], x["price"]))
            why = x["why"].replace("FAST4 ", "")
            if why == "stop" or why in ACCOUNT_CLOSES or why == "stop level" or why == "exit":
                ended_by = why
        if ended_by in ACCOUNT_CLOSES:               # the account's own flatten cut it short
            cut = got[-1][1]
            want = [e for e in want if e[1] < cut]
            got_cmp = got[:-1]
        else:
            got_cmp = got
        ok = len(want) == len(got_cmp) and all(
            a[0] == b[0] and a[1] == b[1] and abs(a[2] - b[2]) < 1e-6
            and abs(a[3] - b[3]) <= 1e-4 + 1e-9 * abs(a[3])
            for a, b in zip(want, got_cmp))
        self.count["events"] += len(got_cmp)
        if not ok or ended_by in ("stop level", "exit"):
            show = lambda es: [(k, t.astimezone(NY).strftime("%Y-%m-%d %H:%M"),   # noqa: E731
                                round(v, 2), round(px, 4)) for k, t, v, px in es]
            self.problems.append(f"{where}: 5 steps differ ({ended_by}).\n    bot    "
                                 f"{show(got_cmp)}\n    oracle {show(want)}")
        r = c["ask"] - c["sl"]
        realised = sum(x.get("pnl", 0.0) for x in mine)
        tp = [x for x in mine if x["side"] == "sell" and "TP" in x["why"]]
        stops = [x["price"] for x in mine if x["side"] == "sl"]   # a stop moves only after a target
        self.trades.append(dict(
            where=where, ended_by=ended_by, tp1=bool(stops or tp),
            tp2=any(px >= c["ask"] + TP1 * r - 1e-4 for px in stops),
            trail=any(px > c["ask"] + TP1 * r + 1e-4 for px in stops),
            moves=len(stops), parts=len(tp),
            R=realised / (c["volume"] * r), risk=c["volume"] * r / c["balance"],
            closed=ended_by != "open at the end"))

    # ---------------------------------------------------------------- run
    def run(self, i0: int, i1: int) -> None:
        logger = logging.getLogger("ftmo_bot")
        saved = (runner_mod.BAR_COUNT, logger.level, logger.propagate, logger.handlers)
        runner_mod.BAR_COUNT = self.history * SESSION_BARS
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.handlers = [self.log]
        try:
            for i in range(max(0, i0 - self.history), i0):   # history the bot starts with
                for s in PROXY:
                    self.feed(PROXY[s], self.bars_of(i, s, ()))
            for i in range(i0, i1):
                self.session(i)
            if self.sim is not None:
                self.close_account("end of the data", i1 - 1)
        finally:
            runner_mod.BAR_COUNT = saved[0]
            logger.setLevel(saved[1])
            logger.propagate, logger.handlers = saved[2], saved[3]
        self.count["refused"] = sum(1 for _, m in self.log.lines if m.startswith("entry ")
                                    and ("refused" in m or "skipped" in m))
        # the plan and the open count slots alike, and between the two a slot is
        # only ever given back: a planned entry is never refused for want of one
        self.problems += [f"planned {m}" for _, m in self.log.lines
                          if m.startswith("entry ") and "refused: already" in m]


def summarise(rp: Replay, i0: int, i1: int) -> Tuple[str, dict]:
    closed = [t for t in rp.trades if t["closed"]]
    rule = [t for t in closed if t["ended_by"] == "stop"]          # ended by the 5 steps
    cut = [t for t in closed if t["ended_by"] in ACCOUNT_CLOSES]
    n = len(rule) or 1
    wins = sum(t["tp1"] for t in rule)
    facts = dict(
        mode=rp.mode, order=rp.order, slots="free" if rp.free else "all",
        first=str(rp.days[i0]), last=str(rp.days[i1 - 1]),
        **rp.count, accounts=len(rp.attempts), trades=len(rp.trades),
        crossed=[f"{d} {w}" for d, w in rp.crossed],
        closed_by_rule=len(rule), closed_by_account=len(cut),
        open_at_end=len(rp.trades) - len(closed),
        part_closes=sum(t["parts"] for t in rp.trades),
        stop_moves=sum(t["moves"] for t in rp.trades),
        reached_tp1=wins, reached_tp2=sum(t["tp2"] for t in rule),
        trailed=sum(t["trail"] for t in rule),
        win_rate=wins / n, loss_rate=1 - wins / n,
        pnl_win_rate=sum(t["R"] > 0 for t in rule) / n,
        mean_R=float(np.mean([t["R"] for t in rule])) if rule else float("nan"),
        avg_win_R=float(np.mean([t["R"] for t in rule if t["R"] > 0] or [float("nan")])),
        avg_loss_R=float(np.mean([t["R"] for t in rule if t["R"] <= 0] or [float("nan")])),
        avg_risk=float(np.mean([t["risk"] for t in rp.trades])) if rp.trades else float("nan"),
        problems=len(rp.problems))
    f = facts
    out = [f"## {rp.mode}, {rp.order.replace('_', ' ')}, slots {f['slots']}: "
           f"{f['first']} → {f['last']}", "",
           f"* {f['sessions']} sessions, {f['ticks']} bot ticks, {f['accounts']} accounts "
           f"in a chain, {f['plans']} plans checked.",
           "* Slots: " + (f"a position whose stop is at or over its entry takes none "
                          f"(free slots). {f['beyond_two']} entries were made with two or "
                          f"more positions already open; most open at once: {f['max_open']}."
                          if rp.free else
                          f"every open position takes one of the two (free slots off). "
                          f"Most open at once: {f['max_open']}."),
           f"* {f['entries']} entries checked (signal, slot, stop, size); {f['refused']} "
           f"planned entries the bot refused or skipped; {f['keepalives']} keep-alive "
           "round trips.",
           f"* {f['trades']} trades: {f['closed_by_rule']} ended by the 5 steps' stops, "
           f"{f['closed_by_account']} cut short by the account's own flatten (guard, target), "
           f"{f['open_at_end']} open at the end.",
           f"* {f['events']} deals checked against the oracle: {f['part_closes']} part "
           f"closes and {f['stop_moves']} stop moves among them.",
           f"* Of the {f['closed_by_rule']} trades the 5 steps ended: {f['reached_tp1']} "
           f"reached +1R first ({f['win_rate']:.1%}), {f['reached_tp2']} went on to +1.5R, "
           f"{f['trailed']} had their stop trailed; {f['closed_by_rule'] - f['reached_tp1']} "
           f"lost at the first stop ({f['loss_rate']:.1%}, 1 in "
           f"{1 / f['loss_rate']:.1f})." if f["loss_rate"] > 0 else "* no losers",
           f"* Before costs: mean {f['mean_R']:+.3f}R per trade, average win "
           f"{f['avg_win_R']:+.2f}R, average loss {f['avg_loss_R']:+.2f}R; average first "
           f"risk {f['avg_risk']:.2%} of the balance.",
           "* Sessions whose lowest equity crossed an FTMO line (a gap through the stops; "
           "FTMO would have ended the account, the replay goes on): "
           + (", ".join(f"{d} ({w})" for d, w in rp.crossed) or "none") + ".",
           f"* **Mismatches: {f['problems']}.**", ""]
    if rp.attempts:
        out += ["| account | opened | closed | ended by | balance | trading days |",
                "|---|---|---|---|---|---|"]
        out += [f"| {a['account']} | {a['opened']} | {a['closed']} | {a['why']} | "
                f"{a['balance']:,.2f} | {a['trading_days']} |" for a in rp.attempts]
        out.append("")
    if rp.problems:
        out += ["Mismatches (first 25):", ""] + [f"* {p}" for p in rp.problems[:25]] + [""]
    return "\n".join(out), facts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True, type=Path)
    ap.add_argument("--mode", choices=("funded", "challenge"), default="funded")
    ap.add_argument("--order", choices=("low_first", "high_first"), default="low_first")
    ap.add_argument("--slots", choices=("free", "all"), default="free",
                    help="free: a position whose stop is at or over its entry takes no "
                         "slot (the bot's default); all: every open position takes one")
    ap.add_argument("--start", help="first session to trade (default: the first with "
                                    f"{HISTORY} sessions of history)")
    ap.add_argument("--end", help="last session (default: the last in the data)")
    ap.add_argument("--history", type=int, default=HISTORY,
                    help="sessions of history the bot sees (at least 205)")
    ap.add_argument("--report", type=Path)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    dates, inst = load_study(a.data_dir)
    days = [pd.Timestamp(d).date() for d in dates]
    i0 = a.history if not a.start else max(a.history, next(
        i for i, d in enumerate(days) if d >= date.fromisoformat(a.start)))
    i1 = len(days) if not a.end else 1 + max(
        i for i, d in enumerate(days) if d <= date.fromisoformat(a.end))
    with tempfile.TemporaryDirectory() as tmp:
        rp = Replay(dates, inst, a.mode, a.order, Path(tmp), a.history, a.slots)
        rp.run(i0, i1)
    text, facts = summarise(rp, i0, i1)
    print(text)
    if a.report:
        a.report.write_text(text, encoding="utf-8")
    if a.json:
        a.json.write_text(json.dumps(facts, indent=2), encoding="utf-8")
    return 1 if rp.problems else 0


if __name__ == "__main__":
    sys.exit(main())
