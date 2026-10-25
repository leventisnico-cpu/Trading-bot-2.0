"""Local replica of the weekly AIR3 re-validation on SMH: Astral strategy
41110 (AIR3 SMH ride, hysteresis 5%) and its aligned buy-and-hold benchmark
41122, run on an Astral daily-bar export. Used when Astral's backtest tool
cannot run (it needs an approval in the app that has gone unanswered since
2026-10-11).

    python -I research/air3_replica.py SMH_1D_CSV [--end YYYY-MM-DD]
                                       [--capital N] [--comm BP] [--slip BP]

Rules (research/air3_daily_log.md): signal at the daily close, fill at the
next open. Buy 95% of equity, sized on the signal close, when close >
1.05 x SMA200 and SMA50 > SMA200. Sell everything when close < 0.95 x
SMA200. Buy-and-hold buys 95% once at the first eligible bar. Both take
their 220 warm-up bars from inside the window, as Astral does. Commission
and slippage are basis points per side.

One exception, inferred from the 2026-10-04 Astral runs: an entry whose
condition already holds on the first eligible bar fills at that bar's
close. With it, the replica reproduces all eight 10-04 AIR3 figures
(return and CAGR in four windows) to rounding, and the drawdowns to 0.1
point. Buy-and-hold is within 6 points in three windows. Fold 3 is
unexplained: +457.5% here against Astral's +445%, with drawdowns of
-35.3% against -34.9%. Confirm the exception on the next real Astral
run.
"""

from __future__ import annotations

import argparse

import pandas as pd

WINDOWS = [("full", "2014-01-01", None), ("fold 1", "2013-03-01", "2018-06-30"),
           ("fold 2", "2017-06-01", "2022-08-31"), ("fold 3", "2021-08-01", None)]


def load(path: str) -> pd.DataFrame:
    """Astral 1d export: bar stamps at New York midnight of the session."""
    df = pd.read_csv(path)
    ts = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert("America/New_York")
    df["date"] = ts.dt.date
    return df[["date", "open", "close"]].reset_index(drop=True)


def run(df: pd.DataFrame, start: str, end: str, mode: str, capital: float = 100000.0,
        warmup: int = 220, comm: float = 1.0, slip: float = 2.0, pct: float = 0.95) -> dict:
    """Backtest one window; mode is "air3" or "bh". Trade returns are on
    equity (equity after the exit over equity before the entry)."""
    lo, hi = pd.Timestamp(start).date(), pd.Timestamp(end).date()
    w = df[(df["date"] >= lo) & (df["date"] <= hi)].reset_index(drop=True)
    if len(w) <= warmup:
        raise ValueError(f"{start}..{end}: {len(w)} bars, need more than {warmup}")
    c, o = w["close"], w["open"]
    s50, s200 = c.rolling(50).mean(), c.rolling(200).mean()
    state = {"cash": capital, "shares": 0.0, "eq_in": 0.0}
    trades: list[float] = []

    def fill(side: str, qty: float, price: float) -> None:
        if side == "buy":
            px = price * (1 + slip / 1e4) * (1 + comm / 1e4)
            qty = min(qty, state["cash"] / px)       # a gap up never overdraws cash
            state["eq_in"] = state["cash"]           # flat before an entry
            state["cash"] -= qty * px
            state["shares"] += qty
        else:
            state["cash"] += qty * price * (1 - slip / 1e4) * (1 - comm / 1e4)
            state["shares"] -= qty
            trades.append(state["cash"] / state["eq_in"] - 1)

    pending = None
    curve = []
    for i in range(warmup, len(w)):
        if pending is not None:                      # fill at this bar's open
            fill(*pending, o[i])
            pending = None
        equity = state["cash"] + state["shares"] * c[i]
        signal = None
        if mode == "air3":
            if state["shares"] == 0 and c[i] > 1.05 * s200[i] and s50[i] > s200[i]:
                signal = ("buy", pct * equity / c[i])
            elif state["shares"] > 0 and c[i] < 0.95 * s200[i]:
                signal = ("sell", state["shares"])
        elif mode == "bh" and i == warmup:
            signal = ("buy", pct * equity / c[i])
        if signal is not None and i == warmup:       # first eligible bar: at its close
            fill(*signal, c[i])
        elif signal is not None and i < len(w) - 1:
            pending = signal
        curve.append((w["date"][i], state["cash"] + state["shares"] * c[i]))
    eq = pd.Series([e for _, e in curve], index=[d for d, _ in curve])
    days = (pd.Timestamp(eq.index[-1]) - pd.Timestamp(eq.index[0])).days
    ret = eq.iloc[-1] / capital - 1
    held = state["shares"] > 0
    return {
        "from": eq.index[0], "to": eq.index[-1], "ret": ret,
        "cagr": (1 + ret) ** (365.25 / days) - 1 if days > 0 else float("nan"),
        "dd": float((eq / eq.cummax() - 1).min()),
        "closed": len(trades), "open": held,
        "win": sum(t > 0 for t in trades) / len(trades) if trades else None,
        "trades": [round(100 * float(t), 1) for t in trades],
        "open_trade": float(eq.iloc[-1] / state["eq_in"] - 1) if held else None,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("csv")
    ap.add_argument("--end", help="last session (default: the last bar)")
    ap.add_argument("--capital", type=float, default=100000.0)
    ap.add_argument("--comm", type=float, default=1.0)
    ap.add_argument("--slip", type=float, default=2.0)
    a = ap.parse_args(argv)
    df = load(a.csv)
    last = pd.Timestamp(a.end or str(df["date"].iloc[-1])).date()
    print("| window | AIR3 return | CAGR | max DD | trades | win rate "
          "| B&H return | B&H max DD | AIR3 lower DD |")
    print("|---|---|---|---|---|---|---|---|---|")
    notes = []
    for name, start, end in WINDOWS:
        end = min(pd.Timestamp(end).date(), last) if end else last
        try:
            r = run(df, start, str(end), "air3", a.capital, comm=a.comm, slip=a.slip)
            b = run(df, start, str(end), "bh", a.capital, comm=a.comm, slip=a.slip)
        except ValueError as e:
            notes.append(f"{name}: skipped ({e})")
            continue
        n = f"{r['closed']}" + (" + 1 open" if r["open"] else "")
        win = "-" if r["win"] is None else f"{100 * r['win']:.0f}%"
        print(f"| {name} {r['from']} → {r['to']} | {100 * r['ret']:+,.1f}% | "
              f"{100 * r['cagr']:.1f}% | {100 * r['dd']:.1f}% | {n} | {win} | "
              f"{100 * b['ret']:+,.1f}% | {100 * b['dd']:.1f}% | "
              f"{'yes' if r['dd'] > b['dd'] else 'NO'} |")
        note = f"{name}: closed trades on equity {r['trades']} (%)"
        if r["open_trade"] is not None:
            note += f", open trade {100 * r['open_trade']:+.1f}%"
        notes.append(note)
    print()
    print("\n".join(notes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
