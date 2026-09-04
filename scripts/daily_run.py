#!/usr/bin/env python3
"""Daily paper-mode cycle (§9: paper mode runs with NO credentials).

Runs on GitHub Actions on a daily schedule:
  1. The workflow runs the test suite first — a red suite means no trading (§8).
  2. Fetch fresh prices for the universe.
  3. Rebuild the paper account from durable state, simulate the $100/week
     contribution, and run one engine cycle (decision on the last trading
     day of the month).
  4. Write the report and persist state; the workflow commits both.

Live execution is Phase 5 and does not exist in this script: there is no
code path here that can reach a real venue (§9: live requires a separate,
deliberate config change and separate credentials).
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from engine.broker import PaperBroker  # noqa: E402
from engine.config import load_config  # noqa: E402
from engine.costs import CostModel  # noqa: E402
from engine.errors import HaltError  # noqa: E402
from engine.journal import Journal  # noqa: E402
from engine.runner import run_cycle  # noqa: E402
from engine.state import EngineState, StateStore  # noqa: E402
from engine.strategies import DualMomentum  # noqa: E402

WEEKLY_CONTRIBUTION = 100.0
STATE_PATH = REPO / "state" / "paper_state.json"
REPORTS_DIR = REPO / "reports"


def fetch_prices(symbols: list[str]) -> pd.DataFrame:
    import yfinance as yf
    df = yf.download(symbols, period="2y", interval="1d",
                     auto_adjust=True, progress=False)["Close"]
    if isinstance(df, pd.Series):
        df = df.to_frame(symbols[0])
    return df[symbols]


def is_last_trading_day_of_month(today: date, index: pd.DatetimeIndex) -> bool:
    """True only on the last business day of the calendar month.

    The first cut compared against the max of the FETCHED index — which by
    construction never extends past today, so every day looked like the
    month's last and the paper engine rebalanced at month START while the
    backtest decided at month END (audit round 1, finding #2). The calendar
    is the reference, not the data. (An exchange holiday on the last
    business day shifts the decision one day early via the workflow simply
    not producing fresher data — validation still gates on staleness.)
    """
    ts = pd.Timestamp(today)
    last_bday = pd.bdate_range(ts.replace(day=1), ts + pd.offsets.MonthEnd(0))[-1]
    return today == last_bday.date()


def contributions_due(state: EngineState, today: date) -> float:
    """$100 for each Monday since the last recorded equity date."""
    if not state.last_equity_date:
        return WEEKLY_CONTRIBUTION
    last = date.fromisoformat(state.last_equity_date)
    total, d = 0.0, last + timedelta(days=1)
    while d <= today:
        if d.weekday() == 0:
            total += WEEKLY_CONTRIBUTION
        d += timedelta(days=1)
    return total


def main() -> int:
    today = date.today()
    cfg = load_config(REPO / "config" / "engine.toml")
    journal = Journal(REPO / "state" / "journal.jsonl")

    store = StateStore(STATE_PATH)
    if not STATE_PATH.exists() and not store.backup_path.exists():
        # Deliberate paper-mode bootstrap (allowed: no real money exists here).
        store.save(EngineState(last_equity_date=today.isoformat()))
        journal.record("bootstrap", mode="paper")
    state_preview = store.load()

    prices = fetch_prices(list(cfg.universe))
    latest = {s: float(prices[s].dropna().iloc[-1]) for s in cfg.universe
              if s in prices.columns and not prices[s].dropna().empty}

    # Simulate the weekly contribution into the paper account.
    contribution = contributions_due(state_preview, today)
    broker = PaperBroker(cash=state_preview.cash + contribution,
                         prices=latest, cost_model=CostModel(cfg.costs),
                         positions=dict(state_preview.positions))
    if contribution:
        journal.record("contribution", amount=contribution)

    strategy = DualMomentum(cfg.universe, cfg.strategy)
    decision = is_last_trading_day_of_month(today, prices.index)

    REPORTS_DIR.mkdir(exist_ok=True)
    try:
        result = run_cycle(today=today, cfg=cfg, store=store, broker=broker,
                           strategy=strategy, prices=prices, journal=journal,
                           decision_day=decision, net_flows=contribution)
        report = result.report
    except HaltError as exc:
        report = f"REFUSED TO TRADE\ndate: {today.isoformat()}\nreason: {exc}\n"
        journal.record("refusal", reason=str(exc))
        (REPORTS_DIR / f"{today.isoformat()}.md").write_text(report)
        print(report)
        return 1

    (REPORTS_DIR / f"{today.isoformat()}.md").write_text(report + "\n")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
