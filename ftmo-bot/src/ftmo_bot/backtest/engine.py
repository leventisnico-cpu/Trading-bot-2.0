"""Event-driven tick backtest (SPEC "Backtest engine").

- The strategy sees completed 15m bars; fills, stops, targets, breakeven and
  time exits are resolved against the tick stream.
- Market entries fill at the first tick at/after the signal bar's close (the
  next bar's open) at ask (long) / bid (short) plus slippage. Stops fill at the
  first tick through the level with the same slippage. Targets fill at touch,
  no slippage. Time exits fill at market with slippage.
- Spread is max(tick spread, typical spread) — the worse of the two — applied
  symmetrically around the tick mid. Commission per ``ftmo_2step.yaml``.
- Every entry goes through ``ftmo_rules.can_open`` → ``sizing.size_for`` (the
  order router's path), and every tick with an open position goes through
  ``ftmo_rules.should_halt`` with the ENGINE limits, flattening on breach the
  way the live guard does.

Overall-loss limits depend on the challenge start date, so the continuous run
evaluates overall loss against the day's baseline (never tighter than the daily
check); ``ftmo_sim`` then replays the true overall limits per rolling window.
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from ftmo_bot.config import (
    FtmoProfile,
    StrategyParams,
    engine_limits,
    flatten_time_utc,
    risk_amount,
)
from ftmo_bot.data.calendar import NewsEvent
from ftmo_bot.risk import ftmo_rules, sizing
from ftmo_bot.risk.sizing import ContractSpec
from ftmo_bot.strategy.asian_breakout import AsianBreakout
from ftmo_bot.strategy.base import Bar, Signal


@dataclass(frozen=True)
class Ticks:
    """One UTC day of ticks for one symbol, spread already floored."""

    ts: np.ndarray  # int64 ns since epoch, sorted
    bid: np.ndarray
    ask: np.ndarray


TickLoader = Callable[[str, date], Ticks | None]


def floor_spread(bid: np.ndarray, ask: np.ndarray, typical: float) -> tuple[np.ndarray, np.ndarray]:
    """Widen ticks whose spread is below ``typical`` symmetrically around the mid."""
    spread = ask - bid
    mid = (ask + bid) / 2
    widen = spread < typical
    return np.where(widen, mid - typical / 2, bid), np.where(widen, mid + typical / 2, ask)


def ticks_from_frame(df: pd.DataFrame, spec: ContractSpec) -> Ticks:
    df = df.sort_values("ts_utc", kind="stable")
    ts = df["ts_utc"].to_numpy(dtype="datetime64[ns]").astype(np.int64)
    bid, ask = floor_spread(
        df["bid"].to_numpy(np.float64), df["ask"].to_numpy(np.float64), spec.typical_spread
    )
    return Ticks(ts, bid, ask)


class ParquetTickLoader:
    """Loads ``{raw_dir}/{symbol}/{YYYY-MM-DD}.parquet`` with a small cache."""

    def __init__(self, raw_dir: Path, specs: dict[str, ContractSpec], cache_size: int = 16) -> None:
        self.raw_dir = raw_dir
        self.specs = specs
        self.cache_size = cache_size
        self._cache: dict[tuple[str, date], Ticks | None] = {}

    def __call__(self, symbol: str, day: date) -> Ticks | None:
        key = (symbol, day)
        if key not in self._cache:
            path = self.raw_dir / symbol / f"{day.isoformat()}.parquet"
            ticks = None
            if path.exists():
                df = pd.read_parquet(path)
                if len(df):
                    ticks = ticks_from_frame(df, self.specs[symbol])
            if len(self._cache) >= self.cache_size:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = ticks
        return self._cache[key]


def bars_from_frame(df: pd.DataFrame, symbol: str, minutes: int) -> list[Bar]:
    ts = df["ts_utc"].dt.tz_convert(UTC)
    return [
        Bar(symbol, t.to_pydatetime(), float(o), float(h), float(lo), float(c), minutes)
        for t, o, h, lo, c in zip(ts, df["open"], df["high"], df["low"], df["close"], strict=True)
    ]


@dataclass
class MarketData:
    bars15: dict[str, list[Bar]]
    bars4h: dict[str, list[Bar]]
    ticks: TickLoader
    excluded: dict[str, set[date]] = field(default_factory=dict)
    news: Sequence[NewsEvent] = ()


@dataclass
class _Pos:
    symbol: str
    side: ftmo_rules.Side
    lots: float
    spec: ContractSpec
    entry_ns: int
    entry: float
    stop: float
    initial_stop: float
    target: float
    session_id: str
    day: date
    flatten_ns: int
    ticks: Ticks
    idx: int
    mark: float
    entry_commission: float
    spread_cost: float
    be_done: bool = False
    mae: float = 0.0
    mfe: float = 0.0

    @property
    def r_dist(self) -> float:
        return abs(self.entry - self.initial_stop)

    def unrealized(self, mark: float) -> float:
        move = mark - self.entry if self.side == "long" else self.entry - mark
        return move * self.spec.value_per_price_unit(self.lots)


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    equity: pd.DataFrame
    days: pd.DataFrame
    rejections: pd.DataFrame
    initial_balance: float
    risk_amount: float
    start: date
    end: date


TRADE_COLUMNS = [
    "entry_ts",
    "exit_ts",
    "symbol",
    "side",
    "r_multiple",
    "pnl_usd",
    "mae",
    "mfe",
    "session_id",
    "date_cest",
    "entry_price",
    "exit_price",
    "stop",
    "target",
    "lots",
    "exit_reason",
    "commission_usd",
    "spread_cost_usd",
    "pip_value_usd",
]


class BacktestEngine:
    def __init__(self, params: StrategyParams, profile: FtmoProfile, data: MarketData) -> None:
        self.p = params
        self.profile = profile
        self.data = data
        self.limits = engine_limits(profile, params)
        self.risk_amount = risk_amount(profile, params)
        self.tz = ZoneInfo(params.timezone)
        self._h4_close = {s: [_ns(b.close_ts) for b in bars] for s, bars in data.bars4h.items()}

    # ------------------------------------------------------------ public

    def run(self, start: date, end: date | None = None) -> BacktestResult:
        self.strategy = AsianBreakout(self.p, self.data.news)
        self.cash = self.profile.initial_balance
        self.trades: list[dict[str, object]] = []
        self.rejections: list[dict[str, object]] = []
        self.eq_ts: list[int] = []
        self.eq_val: list[float] = []
        day_rows = []

        by_day: dict[date, list[Bar]] = defaultdict(list)
        for sym, bars in self.data.bars15.items():
            if sym not in self.p.instruments:
                continue
            for b in bars:
                d = b.ts_utc.astimezone(self.tz).date()
                if d >= start and (end is None or d <= end):
                    by_day[d].append(b)
        days = sorted(by_day)
        last = days[-1] if days else start

        for day in days:
            bars = sorted(by_day[day], key=lambda b: (b.close_ts, b.symbol))
            self.open: list[_Pos] = []
            self.day_start = self.cash
            self.day_low = self.cash
            self.day_high = self.cash
            self.consecutive_losses = 0
            self.halted: ftmo_rules.HaltDecision | None = None
            n_trades_before = len(self.trades)
            for b in bars:
                self._advance(_ns(b.close_ts))
                sig = self.strategy.on_bar(b, self._h4(b))
                if sig is not None:
                    self._try_open(sig, b, day)
            self._advance(_ns(ftmo_rules.next_reset_utc(bars[-1].close_ts, self.p.timezone)))
            for pos in list(self.open):  # ticks ran out before the time exit
                self._close(pos, pos.idx - 1, pos.mark, "data_end")
            day_rows.append(
                {
                    "date_cest": day,
                    "start_equity": self.day_start,
                    "min_equity": self.day_low,
                    "max_equity": self.day_high,
                    "end_equity": self.cash,
                    "trades": len(self.trades) - n_trades_before,
                    "halted": self.halted is not None,
                    "halt_reason": self.halted.reason if self.halted else "",
                }
            )

        trades = pd.DataFrame(self.trades, columns=TRADE_COLUMNS)
        equity = pd.DataFrame(
            {
                "ts_utc": pd.to_datetime(np.asarray(self.eq_ts, dtype=np.int64), utc=True),
                "equity": np.asarray(self.eq_val, dtype=np.float64),
            }
        )
        return BacktestResult(
            trades=trades,
            equity=equity,
            days=pd.DataFrame(day_rows),
            rejections=pd.DataFrame(self.rejections, columns=["ts", "symbol", "side", "reason"]),
            initial_balance=self.profile.initial_balance,
            risk_amount=self.risk_amount,
            start=start,
            end=last,
        )

    # ------------------------------------------------------------ internals

    def _h4(self, bar: Bar) -> list[Bar]:
        bars = self.data.bars4h.get(bar.symbol, [])
        k = bisect.bisect_right(self._h4_close.get(bar.symbol, []), _ns(bar.close_ts))
        return bars[max(0, k - self.p.h4_lookback) : k]

    def _equity(self) -> float:
        return self.cash + sum(p.unrealized(p.mark) for p in self.open)

    def _state(self, now_ns: int) -> ftmo_rules.AccountState:
        return ftmo_rules.AccountState(
            now_utc=_dt(now_ns),
            equity=self._equity(),
            day_baseline=self.day_start,
            # Overall loss is replayed per challenge window in ftmo_sim.
            overall_reference=self.day_start,
            open_positions=tuple(
                ftmo_rules.OpenPosition(
                    p.symbol, p.side, sizing.risk_to_stop(p.side, p.lots, p.mark, p.stop, p.spec)
                )
                for p in self.open
            ),
            consecutive_losses_today=self.consecutive_losses,
        )

    def _reject(self, ts: int, sig: Signal, reason: str) -> None:
        self.rejections.append(
            {"ts": _dt(ts), "symbol": sig.symbol, "side": sig.side, "reason": reason}
        )

    def _try_open(self, sig: Signal, bar: Bar, day: date) -> None:
        t = _ns(bar.close_ts)
        if day in self.data.excluded.get(sig.symbol, set()):
            self._reject(t, sig, "integrity: day excluded")
            return
        if self.halted is not None:
            self._reject(t, sig, f"halted: {self.halted.reason}")
            return
        spec = self.profile.contracts[sig.symbol]
        ticks = self.data.ticks(sig.symbol, bar.close_ts.date())
        inst = self.p.instruments[sig.symbol]
        flatten = _ns(flatten_time_utc(day, inst, self.p))
        if day.weekday() == 4:
            cutoff = datetime.combine(day, self.profile.friday_cutoff, tzinfo=self.tz)
            flatten = min(flatten, _ns(cutoff))
        if ticks is None:
            self._reject(t, sig, "no ticks")
            return
        i = int(np.searchsorted(ticks.ts, t, side="left"))
        if i >= len(ticks.ts) or ticks.ts[i] >= flatten:
            self._reject(t, sig, "no tick before time exit")
            return
        bid, ask = float(ticks.bid[i]), float(ticks.ask[i])
        state = self._state(int(ticks.ts[i]))
        projected = sizing.projected_loss(sig, spec, self.risk_amount, ask - bid)
        ok, reason = ftmo_rules.can_open(sig, state, self.limits, projected)
        if not ok:
            self._reject(int(ticks.ts[i]), sig, reason)
            return
        lots = sizing.size_for(sig, spec, self.risk_amount)
        if lots <= 0:
            self._reject(int(ticks.ts[i]), sig, "size below min lot")
            return
        if sig.side == "long":
            fill = ask + spec.slippage
            bad = fill <= sig.stop or fill >= sig.target
            mark = bid
        else:
            fill = bid - spec.slippage
            bad = fill >= sig.stop or fill <= sig.target
            mark = ask
        if bad:
            self._reject(int(ticks.ts[i]), sig, "fill beyond stop or target")
            return
        commission = spec.commission_per_lot_side * lots
        self.cash -= commission
        pos = _Pos(
            symbol=sig.symbol,
            side=sig.side,
            lots=lots,
            spec=spec,
            entry_ns=int(ticks.ts[i]),
            entry=fill,
            stop=sig.stop,
            initial_stop=sig.stop,
            target=sig.target,
            session_id=sig.session_id,
            day=day,
            flatten_ns=flatten,
            ticks=ticks,
            idx=i + 1,
            mark=mark,
            entry_commission=commission,
            spread_cost=(ask - bid) * spec.value_per_price_unit(lots),
        )
        self.open.append(pos)
        self._mark(pos, mark)
        self._record(int(ticks.ts[i]))

    def _mark(self, pos: _Pos, mark: float) -> None:
        pos.mark = mark
        contrib = pos.unrealized(mark) - pos.entry_commission
        pos.mae = min(pos.mae, contrib)
        pos.mfe = max(pos.mfe, contrib)

    def _record(self, ts: int) -> None:
        eq = self._equity()
        self.eq_ts.append(ts)
        self.eq_val.append(eq)
        self.day_low = min(self.day_low, eq)
        self.day_high = max(self.day_high, eq)

    def _close(self, pos: _Pos, i: int, price: float, reason: str) -> None:
        spec = pos.spec
        commission = spec.commission_per_lot_side * pos.lots
        gross = pos.unrealized(price)
        self.cash += gross - commission
        pnl = gross - commission - pos.entry_commission
        self.open.remove(pos)
        self.consecutive_losses = self.consecutive_losses + 1 if pnl < 0 else 0
        ts = int(pos.ticks.ts[max(i, 0)])
        self.trades.append(
            {
                "entry_ts": _dt(pos.entry_ns),
                "exit_ts": _dt(ts),
                "symbol": pos.symbol,
                "side": pos.side,
                "r_multiple": pnl / self.risk_amount,
                "pnl_usd": pnl,
                "mae": min(pos.mae, pnl),
                "mfe": max(pos.mfe, pnl),
                "session_id": pos.session_id,
                "date_cest": pos.day,
                "entry_price": pos.entry,
                "exit_price": price,
                "stop": pos.stop,
                "target": pos.target,
                "lots": pos.lots,
                "exit_reason": reason,
                "commission_usd": commission + pos.entry_commission,
                "spread_cost_usd": pos.spread_cost,
                "pip_value_usd": spec.pip_value(pos.lots),
            }
        )
        self._record(ts)

    def _market_exit_price(self, pos: _Pos, i: int) -> float:
        if pos.side == "long":
            return float(pos.ticks.bid[i]) - pos.spec.slippage
        return float(pos.ticks.ask[i]) + pos.spec.slippage

    def _advance(self, until_ns: int) -> None:
        """Process ticks with ts < ``until_ns`` for all open positions."""
        if not self.open:
            return
        segs = []
        for k, pos in enumerate(self.open):
            hi = int(np.searchsorted(pos.ticks.ts, until_ns, side="left"))
            if hi > pos.idx:
                idx = np.arange(pos.idx, hi)
                segs.append((pos.ticks.ts[pos.idx : hi], np.full(hi - pos.idx, k), idx))
        if not segs:
            return
        ts_all = np.concatenate([s[0] for s in segs])
        order = np.argsort(ts_all, kind="stable")
        who = np.concatenate([s[1] for s in segs])[order]
        where = np.concatenate([s[2] for s in segs])[order]
        positions = list(self.open)
        be_r = self.p.breakeven_r
        for k, i in zip(who.tolist(), where.tolist(), strict=True):
            pos = positions[k]
            if pos not in self.open:
                continue
            pos.idx = i + 1
            ts = int(pos.ticks.ts[i])
            bid = float(pos.ticks.bid[i])
            ask = float(pos.ticks.ask[i])
            if ts >= pos.flatten_ns:
                self._close(pos, i, self._market_exit_price(pos, i), "time")
            elif pos.side == "long":
                if bid <= pos.stop:
                    self._close(
                        pos, i, bid - pos.spec.slippage, "breakeven" if pos.be_done else "stop"
                    )
                elif bid >= pos.target:
                    self._close(pos, i, pos.target, "target")
                else:
                    if not pos.be_done and bid >= pos.entry + be_r * pos.r_dist:
                        pos.stop = pos.entry
                        pos.be_done = True
                    self._mark(pos, bid)
            else:
                if ask >= pos.stop:
                    self._close(
                        pos, i, ask + pos.spec.slippage, "breakeven" if pos.be_done else "stop"
                    )
                elif ask <= pos.target:
                    self._close(pos, i, pos.target, "target")
                else:
                    if not pos.be_done and ask <= pos.entry - be_r * pos.r_dist:
                        pos.stop = pos.entry
                        pos.be_done = True
                    self._mark(pos, ask)
            if pos in self.open:
                self._record(ts)
            # Same function the live guard calls; open positions don't affect it.
            decision = ftmo_rules.should_halt(
                ftmo_rules.AccountState(_dt(ts), self._equity(), self.day_start, self.day_start),
                self.limits,
            )
            if decision is not None:
                self.halted = decision
                for other in list(self.open):
                    j = max(other.idx - 1, 0)
                    self._close(other, j, self._market_exit_price(other, j), "guard_halt")
                return
            if not self.open:
                return


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _ns(ts: datetime) -> int:
    return (ts - _EPOCH) // timedelta(microseconds=1) * 1000


def _dt(ns: int) -> datetime:
    return datetime.fromtimestamp(ns / 1e9, tz=UTC)


def load_market_data(
    bars_dir: Path,
    raw_dir: Path,
    params: StrategyParams,
    profile: FtmoProfile,
    excluded: dict[str, set[date]],
    news: Sequence[NewsEvent] = (),
    symbols: Sequence[str] | None = None,
) -> MarketData:
    from ftmo_bot.data.resample import bars_path

    symbols = list(symbols or params.instruments)
    b15: dict[str, list[Bar]] = {}
    b4: dict[str, list[Bar]] = {}
    for s in symbols:
        b15[s] = bars_from_frame(
            pd.read_parquet(bars_path(bars_dir, s, params.bar_minutes)), s, params.bar_minutes
        )
        b4[s] = bars_from_frame(
            pd.read_parquet(bars_path(bars_dir, s, params.trend_minutes)), s, params.trend_minutes
        )
    return MarketData(
        bars15=b15,
        bars4h=b4,
        ticks=ParquetTickLoader(raw_dir, profile.contracts),
        excluded=excluded,
        news=news,
    )


__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "MarketData",
    "ParquetTickLoader",
    "Ticks",
    "bars_from_frame",
    "floor_spread",
    "load_market_data",
    "ticks_from_frame",
]
