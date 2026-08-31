#!/usr/bin/env python3
"""Phase 4 — the honest backtest (§4 Phase 4, §6, §9, §10).

Produces docs/PHASE_4_RESULTS.md: buy-and-hold comparison, per-fold
regime performance, parameter sensitivity grid, cost sensitivity, and
net-return-by-account-size. No parameter is tuned here (§10): the 12-1
configuration was fixed by the published literature before this ran; the
grid exists to detect fragility, not to pick a better cell.
"""
from __future__ import annotations

import dataclasses
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from engine.backtest import run_backtest  # noqa: E402
from engine.config import load_config  # noqa: E402
from engine.strategies import DualMomentum  # noqa: E402
from tests.conftest import ConstWeights  # noqa: E402

WEEKLY = 100.0
SHARPE_BUG_THRESHOLD = 1.5  # §2: above this on a retail strategy, assume a bug


def weekly_contribution(d: date) -> float:
    return WEEKLY if d.weekday() == 0 else 0.0


def no_contribution(d: date) -> float:
    return 0.0


def flows_for(index: pd.DatetimeIndex, contribution) -> pd.Series:
    return pd.Series([contribution(ts.date()) for ts in index], index=index)


def metrics(equity: pd.Series, flows: pd.Series) -> dict:
    """Time-weighted metrics (contributions stripped) + final wealth."""
    e_prev = equity.shift(1)
    r = (equity - flows) / e_prev - 1.0
    r = r.replace([np.inf, -np.inf], np.nan).dropna()
    r = r[e_prev.reindex(r.index) > 0]
    if len(r) < 30:
        return {"cagr": np.nan, "vol": np.nan, "sharpe": np.nan, "max_dd": np.nan,
                "final": float(equity.iloc[-1])}
    years = len(r) / 252.0
    growth = float((1 + r).prod())
    cagr = growth ** (1 / years) - 1 if growth > 0 else -1.0
    vol = float(r.std() * np.sqrt(252))
    sharpe = float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else np.nan
    # Drawdown on the TWR index so contributions don't mask losses.
    twr = (1 + r).cumprod()
    max_dd = float((twr / twr.cummax() - 1).min())
    return {"cagr": cagr, "vol": vol, "sharpe": sharpe, "max_dd": max_dd,
            "final": float(equity.iloc[-1])}


def run(prices, strategy, cfg, initial, contribution):
    res = run_backtest(prices, strategy, cfg, initial_equity=initial,
                       contribution=contribution)
    fl = flows_for(res.equity.index, contribution)
    m = metrics(res.equity, fl)
    m["costs"] = res.costs_paid
    m["contrib"] = res.contributions_total
    m["invested"] = initial + res.contributions_total
    m["halted"] = res.halted
    m["refusals"] = len(res.refusals)
    m["orders"] = len(res.orders_filled)
    avg_equity = float(res.equity.mean())
    years = len(res.equity) / 252.0
    m["fee_drag_yr"] = res.costs_paid / avg_equity / years if avg_equity > 0 else np.nan
    return m, res


def fmt_row(name: str, m: dict) -> str:
    # A halted or refusal-laden run must be impossible to mistake for a
    # clean one (§11) — flag it in the row itself.
    marks = []
    if m.get("halted"):
        marks.append("⚠HALTED")
    if m.get("refusals"):
        marks.append(f"⚠{m['refusals']} data refusals")
    if m.get("orders") == 0:
        marks.append("⚠NO TRADES")
    tag = (" " + " ".join(marks)) if marks else ""
    return (f"| {name}{tag} | {m['cagr']:.2%} | {m['vol']:.2%} | {m['sharpe']:.2f} | "
            f"{m['max_dd']:.2%} | {m['costs']:,.0f} | {m['fee_drag_yr']:.2%} | "
            f"{m['final']:,.0f} |")


HEADER = ("| config | CAGR (TWR) | vol | Sharpe | maxDD | fees paid | fee drag/yr | final $ |\n"
          "|---|---|---|---|---|---|---|---|")


def main() -> None:
    cfg = load_config(REPO / "config" / "engine.toml")
    out: list[str] = []
    flags: list[str] = []

    cad = pd.read_csv(REPO / "data" / "prices_cad.csv", index_col=0, parse_dates=True)
    cad = cad.loc[cad.dropna().index[0]:]          # common history only
    us = pd.read_csv(REPO / "data" / "prices_us.csv", index_col=0, parse_dates=True)
    us = us.loc[us.dropna().index[0]:]

    dm = lambda c: DualMomentum(c.universe, c.strategy)
    bench_equity = ConstWeights({cfg.universe[0]: 1.0})            # 100% US equity (XUU)
    bench_6040 = ConstWeights({cfg.universe[0]: 0.6, cfg.strategy["defensive_symbol"]: 0.4})

    out.append("# Phase 4 Results — measured, not tuned\n")
    out.append(f"CAD universe: {list(cad.columns)}, {cad.index[0].date()} → {cad.index[-1].date()} "
               f"({len(cad)} bars). Adjusted closes (distributions reinvested). "
               f"Costs: {cfg.costs.fee_model}, min {cfg.costs.fixed_min_fee} "
               f"{cfg.base_currency}/order, spread {cfg.costs.spread_bps}bps, "
               f"slippage {cfg.costs.slippage_bps}bps, all per order (§6).\n")

    # ---- 1. Headline: the actual deployment shape ($100/wk from zero) ----
    out.append("## 1. The actual deployment: $0 start, $100/week\n")
    out.append(HEADER)
    m, _ = run(cad, dm(cfg), cfg, 0.0, weekly_contribution)
    out.append(fmt_row("dual momentum 12-1", m))
    if m["sharpe"] > SHARPE_BUG_THRESHOLD:
        flags.append(f"headline Sharpe {m['sharpe']:.2f} > {SHARPE_BUG_THRESHOLD} — §2 says assume a bug")
    mb, _ = run(cad, bench_equity, cfg, 0.0, weekly_contribution)
    out.append(fmt_row("buy-and-hold DCA 100% US equity", mb))
    m64, _ = run(cad, bench_6040, cfg, 0.0, weekly_contribution)
    out.append(fmt_row("buy-and-hold DCA 60/40", m64))
    out.append("")
    headline = {"strategy": m, "bh_equity": mb, "bh_6040": m64}

    # ---- 2. Net return by account size (§6: the most valuable table) ----
    out.append("## 2. Net return by account size (no contributions)\n")
    out.append(HEADER)
    by_size = {}
    for size in (1_000, 2_500, 5_000, 10_000, 25_000, 100_000):
        ms, _ = run(cad, dm(cfg), cfg, float(size), no_contribution)
        by_size[size] = ms
        out.append(fmt_row(f"${size:,}", ms))
    out.append("")

    # ---- 3. Cost sensitivity ----
    out.append("## 3. Cost sensitivity ($5,000 start, no contributions)\n")
    out.append(HEADER)
    for mult in (0.0, 0.5, 1.0, 2.0, 4.0):
        c2 = dataclasses.replace(cfg, costs=dataclasses.replace(
            cfg.costs, fixed_min_fee=cfg.costs.fixed_min_fee * mult,
            per_share_fee=cfg.costs.per_share_fee * mult))
        mc, _ = run(cad, dm(c2), c2, 5_000.0, no_contribution)
        out.append(fmt_row(f"commission x{mult}", mc))
    for sp in (5.0, 20.0, 40.0):
        c2 = dataclasses.replace(cfg, costs=dataclasses.replace(cfg.costs, spread_bps=sp))
        mc, _ = run(cad, dm(c2), c2, 5_000.0, no_contribution)
        out.append(fmt_row(f"spread {sp:.0f}bps", mc))
    out.append("")

    # ---- 4. Parameter sensitivity grid (NOT for tuning — §10) ----
    out.append("## 4. Parameter sensitivity ($5,000, no contributions) — "
               "robustness check, not a menu (§10)\n")
    out.append("| lookback | skip | top_n | CAGR | Sharpe | maxDD |\n|---|---|---|---|---|---|")
    grid = {}
    for lb in (3, 6, 9, 12):
        for skip in (0, 1):
            for tn in (1, 2):
                c2 = dataclasses.replace(cfg, strategy=dict(
                    cfg.strategy, lookback_months=lb, skip_months=skip, top_n=tn))
                mg, _ = run(cad, dm(c2), c2, 5_000.0, no_contribution)
                grid[(lb, skip, tn)] = mg
                out.append(f"| {lb} | {skip} | {tn} | {mg['cagr']:.2%} | "
                           f"{mg['sharpe']:.2f} | {mg['max_dd']:.2%} |")
    sharpes = [g["sharpe"] for g in grid.values() if not np.isnan(g["sharpe"])]
    chosen = grid[(cfg.strategy["lookback_months"], cfg.strategy["skip_months"],
                   cfg.strategy["top_n"])]
    if sharpes and chosen["sharpe"] >= np.nanmax(sharpes) - 1e-9 and \
            chosen["sharpe"] > np.nanmedian(sharpes) + 0.5:
        flags.append("chosen parameter cell is a lonely peak vs the grid median — fragile")
    out.append(f"\ngrid Sharpe: median {np.nanmedian(sharpes):.2f}, "
               f"min {np.nanmin(sharpes):.2f}, max {np.nanmax(sharpes):.2f}; "
               f"chosen (12-1, top1): {chosen['sharpe']:.2f}\n")

    # ---- 5. Walk-forward folds on the CAD history ----
    out.append("## 5. Performance by fold (single run, sliced — no resets)\n")
    _, res_full = run(cad, dm(cfg), cfg, 5_000.0, no_contribution)
    _, res_b64 = run(cad, bench_6040, cfg, 5_000.0, no_contribution)
    n_folds = 3
    edges = np.linspace(0, len(res_full.equity), n_folds + 1, dtype=int)
    out.append("| fold | period | strategy Sharpe | 60/40 Sharpe | strategy maxDD |\n|---|---|---|---|---|")
    zero_flows = pd.Series(0.0, index=res_full.equity.index)
    for k in range(n_folds):
        sl = slice(edges[k], edges[k + 1])
        eq = res_full.equity.iloc[sl]
        fb = res_b64.equity.iloc[sl]
        ms = metrics(eq, zero_flows.iloc[sl])
        mbf = metrics(fb, zero_flows.iloc[sl])
        out.append(f"| {k + 1} | {eq.index[0].date()} → {eq.index[-1].date()} | "
                   f"{ms['sharpe']:.2f} | {mbf['sharpe']:.2f} | {ms['max_dd']:.2%} |")
    out.append("")

    # ---- 6. Long-history US proxy (includes 2008) ----
    out.append("## 6. Long-history US proxy (SPY/EFA/EEM, AGG defensive; "
               "approximate USD 1 min commission)\n")
    us_cfg = dataclasses.replace(
        cfg,
        universe=tuple(us.columns),
        strategy=dict(cfg.strategy, defensive_symbol="AGG"),
    )
    out.append(HEADER)
    mus, res_us = run(us, dm(us_cfg), us_cfg, 5_000.0, no_contribution)
    out.append(fmt_row("dual momentum 12-1 (US)", mus))
    mus_b, res_usb = run(us, ConstWeights({"SPY": 0.6, "AGG": 0.4}), us_cfg,
                         5_000.0, no_contribution)
    out.append(fmt_row("60/40 SPY/AGG", mus_b))
    if mus["sharpe"] > SHARPE_BUG_THRESHOLD:
        flags.append(f"US-proxy Sharpe {mus['sharpe']:.2f} > {SHARPE_BUG_THRESHOLD} — §2 says assume a bug")
    # 2008 fold specifically:
    crisis = res_us.equity.loc["2007-10-01":"2009-06-30"]
    crisis_b = res_usb.equity.loc["2007-10-01":"2009-06-30"]
    if len(crisis) > 100:
        zf = pd.Series(0.0, index=crisis.index)
        mc_ = metrics(crisis, zf)
        mcb = metrics(crisis_b, pd.Series(0.0, index=crisis_b.index))
        out.append(f"\n2007-10 → 2009-06: strategy maxDD {mc_['max_dd']:.2%} "
                   f"vs 60/40 maxDD {mcb['max_dd']:.2%}\n")

    # ---- flags + machine-readable summary ----
    out.append("## Flags\n")
    if flags:
        out.extend(f"- ⚠ {f}" for f in flags)
    else:
        out.append("- none raised by the automated checks")
    out.append("\n*(Verdict is written separately in docs/PHASE_4_REPORT.md after "
               "human review of these numbers — this file is measurements only.)*")

    (REPO / "docs").mkdir(exist_ok=True)
    (REPO / "docs" / "PHASE_4_RESULTS.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
