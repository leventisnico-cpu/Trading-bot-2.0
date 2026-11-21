"""``ftmo-bot`` command line.

Data:      download, resample, integrity
Research:  backtest --split insample|oos|holdout, montecarlo, report
Live:      guard (Process 1), paper / live (Process 2)

There is no flag anywhere that bypasses ``risk/ftmo_rules.py``.
"""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from ftmo_bot.config import (
    DEFAULT_CONFIG_DIR,
    FtmoProfile,
    StrategyParams,
    engine_limits,
    ftmo_limits,
    load_profile,
    load_strategy,
    risk_amount,
)

ROOT = DEFAULT_CONFIG_DIR.parent
log = logging.getLogger("ftmo_bot")


def _configs(args: argparse.Namespace) -> tuple[StrategyParams, FtmoProfile]:
    cfg = Path(args.config_dir)
    return load_strategy(cfg / "strategy.yaml"), load_profile(cfg / args.profile)


def _symbols(args: argparse.Namespace, params: StrategyParams) -> list[str]:
    return [args.symbol] if getattr(args, "symbol", None) else list(params.instruments)


def _setup_logging(path: Path | None = None, verbose: bool = False) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            logging.handlers.RotatingFileHandler(
                path, maxBytes=10_000_000, backupCount=20, encoding="utf-8"
            )
        )
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )


# ------------------------------------------------------------------ data


def cmd_download(args: argparse.Namespace) -> int:
    from ftmo_bot.data.dukascopy import HttpFetcher, download_range

    params, profile = _configs(args)
    end = date.fromisoformat(args.to) if args.to else date.today()
    fetch = HttpFetcher(min_interval_s=args.rate_limit)
    for sym in _symbols(args, params):
        instrument, divisor = profile.dukascopy[sym]
        paths = download_range(
            sym, instrument, divisor, date.fromisoformat(args.from_), end, Path(args.raw_dir), fetch
        )
        print(f"{sym}: {len(paths)} day files in {Path(args.raw_dir) / sym}")
    return 0


def cmd_resample(args: argparse.Namespace) -> int:
    from ftmo_bot.data.resample import resample_symbol

    params, _ = _configs(args)
    for sym in _symbols(args, params):
        out = resample_symbol(
            Path(args.raw_dir),
            Path(args.bars_dir),
            params.instruments[sym],
            params.timezone,
            params.bar_minutes,
            params.trend_minutes,
        )
        print(f"{sym}: " + ", ".join(str(p) for p in out.values()))
    return 0


def cmd_integrity(args: argparse.Namespace) -> int:
    from ftmo_bot.data.integrity import run_integrity

    params, _ = _configs(args)
    for sym in _symbols(args, params):
        rep = run_integrity(
            Path(args.raw_dir), params.instruments[sym], params.timezone, Path(args.integrity_dir)
        )
        print(
            f"{sym}: {rep['trading_days']} trading days, {rep['failed_days']} failed "
            f"({rep['failed_fraction']:.1%}) → excluded; report in {args.integrity_dir}"
        )
    return 0


# ------------------------------------------------------------------ research


def _load_news(args: argparse.Namespace) -> list:  # type: ignore[type-arg]
    from ftmo_bot.data import calendar

    if args.news_csv:
        return calendar.high_impact(calendar.load_csv(Path(args.news_csv)))
    cache = Path(args.calendar_dir)
    return calendar.high_impact(calendar.load_cache(cache)) if cache.exists() else []


def cmd_backtest(args: argparse.Namespace) -> int:
    from ftmo_bot.backtest import ledger
    from ftmo_bot.backtest.engine import BacktestEngine, load_market_data
    from ftmo_bot.backtest.report import build_report, summarize_backtest
    from ftmo_bot.data.integrity import load_excluded

    params, profile = _configs(args)
    reports = Path(args.reports_dir)
    ledger_path = reports / "ledger.jsonl"
    try:
        ledger.check(ledger_path, args.split, params.params_hash)
    except ledger.LedgerRefusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    symbols = list(params.instruments)
    excluded = {s: load_excluded(Path(args.integrity_dir), s) for s in symbols}
    news = _load_news(args)
    md = load_market_data(
        Path(args.bars_dir), Path(args.raw_dir), params, profile, excluded, news, symbols
    )
    start, end = params.splits[args.split]
    result = BacktestEngine(params, profile, md).run(start, end)
    summary = summarize_backtest(
        args.split,
        result,
        engine_limits(profile, params),
        ftmo_limits(profile, params),
        profile,
        params,
        len(news),
    )
    out = reports / args.split
    out.mkdir(parents=True, exist_ok=True)
    result.trades.to_parquet(out / "trades.parquet", index=False)
    result.days.to_parquet(out / "days.parquet", index=False)
    result.equity.to_parquet(out / "equity.parquet", index=False)
    result.rejections.to_parquet(out / "rejections.parquet", index=False)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    ledger.record(
        ledger_path,
        args.split,
        params.params_hash,
        trades=summary["trades"],
        expectancy_r=summary["expectancy_r"],
        pass_rate=summary["ftmo_phase1"]["pass_rate"],
    )
    html = build_report(reports, Path(args.integrity_dir), profile)
    print(
        json.dumps(
            {k: summary[k] for k in ("split", "start", "end", "trades", "expectancy_r", "win_rate")}
            | {"phase1_pass_rate": summary["ftmo_phase1"]["pass_rate"]},
            default=str,
        )
    )
    print(f"report: {html}")
    return 0


def cmd_montecarlo(args: argparse.Namespace) -> int:
    import pandas as pd

    from ftmo_bot.backtest import montecarlo
    from ftmo_bot.backtest.report import build_report

    params, profile = _configs(args)
    reports = Path(args.reports_dir)
    trades_path = reports / args.split / "trades.parquet"
    if not trades_path.exists():
        print(f"no trades for split {args.split}; run `ftmo-bot backtest` first", file=sys.stderr)
        return 2
    res = montecarlo.run(
        pd.read_parquet(trades_path),
        engine_limits(profile, params),
        ftmo_limits(profile, params),
        tuple(p.profit_target_pct for p in profile.phases),
        profile.min_trading_days,
        profile.challenge_fee,
        paths=args.paths,
        seed=args.seed,
    )
    res["split"] = args.split
    res["params_hash"] = params.params_hash
    (reports / "montecarlo.json").write_text(json.dumps(res, indent=2))
    build_report(reports, Path(args.integrity_dir), profile)
    print(
        json.dumps(
            {
                k: res.get(k)
                for k in (
                    "paths",
                    "p_phase1",
                    "p_both",
                    "p_ftmo_daily_breach",
                    "expected_cost_to_funded",
                )
            }
        )
    )
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from ftmo_bot.backtest.report import build_report

    _, profile = _configs(args)
    cov = Path(args.coverage_json) if args.coverage_json else None
    print(build_report(Path(args.reports_dir), Path(args.integrity_dir), profile, cov))
    return 0


# ------------------------------------------------------------------ live


def _mt5_from_env(prefix: str, profile: FtmoProfile):  # type: ignore[no-untyped-def]
    from ftmo_bot.execution.mt5_client import MT5Client

    missing = [k for k in ("LOGIN", "PASSWORD", "SERVER") if not os.environ.get(f"{prefix}{k}")]
    if missing:
        raise SystemExit(f"missing environment variables: {', '.join(prefix + m for m in missing)}")
    client = MT5Client(server_tz=profile.server_timezone)
    client.connect(
        int(os.environ[f"{prefix}LOGIN"]),
        os.environ[f"{prefix}PASSWORD"],
        os.environ[f"{prefix}SERVER"],
        os.environ.get(f"{prefix}PATH"),
    )
    return client


def cmd_guard(args: argparse.Namespace) -> int:
    from ftmo_bot.execution.notify import Notifier
    from ftmo_bot.execution.state import StateStore
    from ftmo_bot.risk.guard import Guard

    params, profile = _configs(args)
    state = Path(args.state_dir)
    _setup_logging(state / "logs" / "guard.log", args.verbose)
    client = _mt5_from_env("MT5_GUARD_", profile)
    Guard(
        client,
        StateStore(state),
        engine_limits(profile, params),
        params,
        profile,
        Notifier.from_env("[guard] "),
    ).run()
    return 0


def _run_strategy(args: argparse.Namespace, require_demo: bool) -> int:
    from ftmo_bot.data import calendar
    from ftmo_bot.execution.notify import Notifier
    from ftmo_bot.execution.order_router import OrderRouter
    from ftmo_bot.execution.runner import RefuseToStart, Runner
    from ftmo_bot.execution.state import StateStore
    from ftmo_bot.risk.guard import utc_now
    from ftmo_bot.strategy.asian_breakout import AsianBreakout

    params, profile = _configs(args)
    state = Path(args.state_dir)
    _setup_logging(state / "logs" / "runner.log", args.verbose)
    cache = Path(args.calendar_dir)
    try:
        calendar.fetch_week(cache, datetime.now(UTC))
    except Exception as exc:
        log.error("news calendar fetch failed: %s", exc)
    news = calendar.load_cache(cache) if cache.exists() else []
    if not news:
        log.warning("NO NEWS EVENTS LOADED — the news filter is inactive")
    notifier = Notifier.from_env("[runner] ")
    client = _mt5_from_env("MT5_", profile)
    store = StateStore(state)
    limits = engine_limits(profile, params)
    router = OrderRouter(
        client, store, limits, profile, risk_amount(profile, params), notifier, utc_now
    )
    runner = Runner(
        client,
        store,
        router,
        AsianBreakout(params, news),
        params,
        profile,
        limits,
        notifier,
        utc_now,
        require_demo=require_demo,
    )
    try:
        runner.run()
    except RefuseToStart as exc:
        notifier.send(f"REFUSED TO START: {exc}")
        print(f"REFUSED TO START: {exc}", file=sys.stderr)
        return 3
    return 0


def cmd_paper(args: argparse.Namespace) -> int:
    return _run_strategy(args, require_demo=True)


def cmd_live(args: argparse.Namespace) -> int:
    return _run_strategy(args, require_demo=False)


# ------------------------------------------------------------------ parser


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ftmo-bot", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--config-dir", default=str(DEFAULT_CONFIG_DIR))
    p.add_argument("--profile", default="ftmo_2step.yaml")
    p.add_argument("--raw-dir", default=str(ROOT / "data" / "raw"))
    p.add_argument("--bars-dir", default=str(ROOT / "data" / "bars"))
    p.add_argument("--integrity-dir", default=str(ROOT / "data" / "integrity"))
    p.add_argument("--calendar-dir", default=str(ROOT / "data" / "calendar"))
    p.add_argument("--reports-dir", default=str(ROOT / "reports"))
    p.add_argument("--state-dir", default=str(ROOT / "state"))
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("download", help="Dukascopy ticks → parquet per symbol-day")
    d.add_argument("--symbol")
    d.add_argument("--from", dest="from_", required=True)
    d.add_argument("--to")
    d.add_argument("--rate-limit", type=float, default=0.25, help="min seconds between requests")
    d.set_defaults(fn=cmd_download)

    r = sub.add_parser("resample", help="ticks → 15m / 4H bars tagged in CE(S)T")
    r.add_argument("--symbol")
    r.set_defaults(fn=cmd_resample)

    i = sub.add_parser("integrity", help="tick integrity report; failing days excluded")
    i.add_argument("--symbol")
    i.set_defaults(fn=cmd_integrity)

    b = sub.add_parser("backtest", help="tick backtest + rolling FTMO replay for one split")
    b.add_argument("--split", required=True, choices=["insample", "oos", "holdout"])
    b.add_argument("--news-csv", help="historical high-impact events: ts_utc,currency,impact,title")
    b.set_defaults(fn=cmd_backtest)

    m = sub.add_parser("montecarlo", help="10,000 stressed session-bootstrap challenge paths")
    m.add_argument("--split", default="oos", choices=["insample", "oos", "holdout"])
    m.add_argument("--paths", type=int, default=10_000)
    m.add_argument("--seed", type=int, default=20261005)
    m.set_defaults(fn=cmd_montecarlo)

    rep = sub.add_parser("report", help="rebuild the HTML report and gate checklist")
    rep.add_argument("--coverage-json", help="pytest-cov JSON for the ftmo_rules coverage gate")
    rep.set_defaults(fn=cmd_report)

    sub.add_parser("guard", help="Process 1: live kill switch").set_defaults(fn=cmd_guard)
    sub.add_parser("paper", help="Process 2 on a DEMO account only").set_defaults(fn=cmd_paper)
    sub.add_parser("live", help="Process 2: strategy runner").set_defaults(fn=cmd_live)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd not in ("guard", "paper", "live"):
        _setup_logging(verbose=args.verbose)
    rc: int = args.fn(args)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
