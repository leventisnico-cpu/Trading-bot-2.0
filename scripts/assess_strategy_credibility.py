#!/usr/bin/env python3
"""Ask the hard question: does this strategy show a real edge, or search noise?

Runs the shipped strategy through the historical replay harness, extracts
the equity curve, and applies the multiple-testing correction from
``mini_prop_os.quant.statistics``.

The trial count matters more than any other input. Reporting a Sharpe as
though it were the first and only idea tested is the central error this
script exists to prevent, so results are shown across a range of honest
trial counts — including the naive n=1 view, for contrast.

Usage:
    python scripts/assess_strategy_credibility.py
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Sequence, Tuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from mini_prop_os.core.config import RiskConfig  # noqa: E402
from mini_prop_os.quant import statistics as st  # noqa: E402
from mini_prop_os.risk.guardrails import RiskGuardrails  # noqa: E402
from mini_prop_os.sim import (HistoricalSession, SimConfig, bars_from_closes,
                              run_session)  # noqa: E402
from mini_prop_os.strategy.adaptive_ema import (  # noqa: E402
    AdaptiveEmaCrossoverStrategy)
from mini_prop_os.strategy.ema_crossover import EmaCrossoverStrategy  # noqa: E402

SYMBOL = "MES"
#: Trial counts to report. 1 is the naive view; the larger figures reflect
#: that an EMA-crossover variant is not an untested idea — the parameter
#: space has been searched exhaustively by the industry for decades.
TRIAL_COUNTS = (1, 10, 100, 1000)


def load_index_closes() -> Tuple[List[datetime], List[float]]:
    dates, closes = [], []
    with open(REPO / "data" / "prices_us.csv") as fh:
        for row in csv.DictReader(fh):
            if not row.get("SPY"):
                continue
            dates.append(datetime.strptime(row["Date"], "%Y-%m-%d")
                         .replace(tzinfo=timezone.utc))
            closes.append(float(row["SPY"]) * 10.0)
    return dates, closes


def equity_returns(curve: Sequence[Tuple[datetime, float]]) -> List[float]:
    """Per-bar simple returns from an equity curve, skipping flat stretches.

    Bars where the strategy held no position contribute exactly zero and
    would otherwise dominate the variance, deflating the Sharpe toward zero
    for reasons unrelated to skill. Only bars where equity actually moved
    are counted, which is the more favourable choice for the strategy.
    """
    out = []
    for (_, prev), (_, cur) in zip(curve, curve[1:]):
        if prev <= 0:
            continue
        r = (cur - prev) / prev
        if r != 0.0:
            out.append(r)
    return out


def run_strategy(name: str, dates, closes) -> List[float]:
    if name == "adaptive":
        strategy = AdaptiveEmaCrossoverStrategy(
            SYMBOL, 9, 21, base_quantity=2, risk_per_trade=250.0,
            multiplier=5.0)
    else:
        strategy = EmaCrossoverStrategy(SYMBOL, 9, 21, order_quantity=1)
    session = HistoricalSession(strategy, RiskGuardrails(RiskConfig()),
                                SimConfig())
    bars = bars_from_closes(closes, SYMBOL, timestamps=dates)
    result = run_session(session, bars)
    return equity_returns(result.equity_curve)


def main() -> int:
    dates, closes = load_index_closes()
    lines: List[str] = [
        "# Strategy credibility assessment",
        "",
        f"Generated: {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}",
        "",
        "Deflated Sharpe Ratio (Bailey & López de Prado) applied to the "
        "shipped strategies over the full SPY history scaled as an MES "
        "proxy. DSR is the probability the edge is real **after** "
        "correcting for how many strategies were searched to find it.",
        "",
    ]
    print()
    for label in ("adaptive", "baseline"):
        returns = run_strategy(label, dates, closes)
        if len(returns) < 2:
            print(f"{label}: too few active bars to assess")
            continue
        _, _, skew, kurt = st._moments(returns)
        sr_period = st.sharpe_ratio(returns)
        sr_annual = st.sharpe_ratio(returns, periods_per_year=252)

        lines += [f"## {label}", "",
                  f"- Active observations: {len(returns)}",
                  f"- Sharpe (per bar): {sr_period:.4f}",
                  f"- Sharpe (annualized): {sr_annual:.3f}",
                  f"- Skew: {skew:.3f}  |  Kurtosis: {kurt:.2f} "
                  f"(3.0 = normal)", "",
                  "| trials searched | selection bar | DSR | verdict |",
                  "|---|---|---|---|"]
        print(f"=== {label} ===")
        print(f"  observations {len(returns)}, Sharpe/bar {sr_period:.4f}, "
              f"annualized {sr_annual:.3f}, skew {skew:.2f}, "
              f"kurtosis {kurt:.1f}")
        # Variance of Sharpe estimates under the null is about 1/n.
        sr_var = 1.0 / len(returns)
        for n_trials in TRIAL_COUNTS:
            v = st.assess_credibility(returns, n_trials=n_trials,
                                      sr_variance_across_trials=sr_var,
                                      periods_per_year=252)
            mark = "CREDIBLE" if v.credible else "not credible"
            lines.append(f"| {n_trials} | {v.selection_bar:.4f} | "
                         f"{v.deflated_sharpe:.4f} | {mark} |")
            print(f"  trials={n_trials:<5} bar={v.selection_bar:.4f} "
                  f"DSR={v.deflated_sharpe:.4f}  {mark}")
        lines.append("")
        print()

    lines += [
        "## Reading this",
        "",
        "A DSR below 0.95 means the result is not statistically "
        "distinguishable from the best of N worthless strategies. That is "
        "not a flaw in the implementation — it is the honest state of a "
        "trend-following rule measured against its own search space.",
        "",
        "The correct response is more evidence (out-of-sample data, live "
        "paper fills), not more parameter tuning: every additional variant "
        "tried *raises* the bar this table measures against.",
    ]
    out = REPO / "reports" / "strategy_credibility.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    print(f"report: {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
