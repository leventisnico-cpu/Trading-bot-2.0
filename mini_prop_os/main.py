"""Mini-Prop OS entry point.

Usage::

    python -m mini_prop_os                # uses mini_prop_os/config.yaml
    python -m mini_prop_os --config path/to/config.yaml

Lifecycle: load config -> configure logging -> connect to IBKR -> run the
event loop -> on SIGINT/SIGTERM cancel working orders (and flatten, if
``execution.flatten_on_shutdown``) -> disconnect -> exit.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import logging.handlers
import signal
import sys
from pathlib import Path
from typing import Optional

from .app import TradingApp, kill_marker_path, run_preflight
from .core.config import (AppConfig, ConfigError, default_config_path,
                          load_config)
from .core.killfile import clear_kill_marker, read_kill_marker

log = logging.getLogger("mini_prop_os")


def setup_logging(cfg: AppConfig) -> None:
    """Console + rotating-file logging per config."""
    level = getattr(logging, cfg.logging.level.upper())
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)
    log_path = Path(cfg.logging.file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fileh = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=10_000_000, backupCount=5)
    fileh.setFormatter(fmt)
    root.addHandler(fileh)
    # ib_insync is chatty at DEBUG; keep it at INFO unless we are debugging.
    if level > logging.DEBUG:
        logging.getLogger("ib_insync").setLevel(logging.INFO)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mini_prop_os",
        description="Autonomous IBKR trading system (paper by default).")
    parser.add_argument(
        "--config", type=Path, default=None,
        help="path to config.yaml (default: $MINI_PROP_OS_CONFIG, ./config.yaml, "
             "or the packaged mini_prop_os/config.yaml)")
    parser.add_argument(
        "--preflight", action="store_true",
        help="read-only go/no-go check of the IBKR setup (connection, "
             "contract, market data, account equity); places no orders")
    parser.add_argument(
        "--reset-kill-switch", metavar="OPERATOR", default=None,
        help="clear a persisted kill-switch halt, attributed to OPERATOR; "
             "review state/executions.jsonl and the account first")
    return parser.parse_args(argv)


def _run_preflight(cfg: AppConfig) -> int:
    marker = read_kill_marker(kill_marker_path(cfg))
    results = asyncio.run(run_preflight(cfg))
    results.append(("no persisted kill-switch halt", marker is None,
                    marker.get("reason", "") if marker else "clear"))
    width = max(len(name) for name, _, _ in results)
    print("\nMini-Prop OS preflight:")
    for name, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:<{width}}  {detail}")
    go = all(ok for _, ok, _ in results)
    print(f"\n{'GO — ready to trade on this setup.' if go else 'NO-GO — fix the failed checks above before trading.'}")
    return 0 if go else 1


async def _run(app: TradingApp) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, app.request_shutdown)
        except NotImplementedError:  # pragma: no cover (non-POSIX)
            signal.signal(sig, lambda *_: app.request_shutdown())
    try:
        await app.run()
    finally:
        await app.shutdown()


def main(argv: Optional[list[str]] = None) -> int:
    """Synchronous entry point; returns a process exit code."""
    args = parse_args(argv)
    config_path = args.config or default_config_path()
    if config_path is None:
        print("error: no config.yaml found (use --config)", file=sys.stderr)
        return 2
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    setup_logging(cfg)
    log.info("loaded config from %s", config_path)
    if args.reset_kill_switch is not None:
        try:
            cleared = clear_kill_marker(kill_marker_path(cfg),
                                        args.reset_kill_switch)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print("kill-switch marker cleared" if cleared
              else "no kill-switch marker present")
        return 0
    if args.preflight:
        return _run_preflight(cfg)
    marker = read_kill_marker(kill_marker_path(cfg))
    if marker is not None:
        log.critical(
            "REFUSING TO START: persisted kill-switch halt from %s (%s). "
            "Review the account and state/executions.jsonl, then clear it "
            "with: python -m mini_prop_os --reset-kill-switch <your-name>",
            marker.get("tripped_at", "unknown time"),
            marker.get("reason", "no reason recorded"))
        return 3
    if cfg.connection.port in (7496, 4001):
        log.warning("LIVE trading port %d configured — this is not paper. "
                    "Ensure this is intentional.", cfg.connection.port)
    app = TradingApp(cfg)
    try:
        asyncio.run(_run(app))
    except KeyboardInterrupt:  # pragma: no cover (second Ctrl-C)
        log.warning("forced exit")
        return 130
    except Exception:
        log.exception("fatal error")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
