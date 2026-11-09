"""python -m ftmo_bot {preflight|plan|run|flat} --config deploy/ftmo/config.yaml [--execute]

* preflight: read-only checks (terminal, account, server clock, the
             initial balance with its loss line and target, symbols,
             indicators).
* plan:      read-only; prints the FAST-4 exits and entries from the last
             completed session, i.e. what the bot does at the next open.
* run:       the daily loop. Orders are only logged unless the config says
             ``dry_run: false`` AND ``--execute`` is given (two opt-ins),
             and they go only to the account the config names in
             ``login`` (the terminal may be on another account).
* flat:      close every bot position and drop the pending plan (FTMO pays
             out only on a flat account); same opt-ins as ``run``.
             Stop ``run`` first: only one of them may hold the state file
             (``lock.py``), so ``flat`` refuses while ``run`` is going.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import fast4, lock, sessions
from .runner import BAR_COUNT, MIN_SESSIONS, Runner, cap_rule, exit_rule
from .config import load


def rules_line(r: Runner) -> str:
    """The numbers to compare with FTMO's dashboard."""
    cfg, st = r.cfg, r.st
    ib = st.initial_balance
    goal = (f"profit target {ib * (1 + cfg.profit_target):,.2f}"
            if cfg.profit_target is not None else "no profit target (funded)")
    return (f"rules: initial balance {ib:,.2f} (from {r.balance_source}), max-loss "
            f"line {r.limits.total_floor():,.2f}, {goal}, trading days "
            f"{len(st.trading_days)} of {cfg.min_trading_days}"
            + (f"; HALTED: {st.halted}" if st.halted
               else "; target locked" if st.target_locked else ""))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ftmo_bot")
    ap.add_argument("command", choices=["preflight", "plan", "run", "flat"])
    ap.add_argument("--config", required=True)
    ap.add_argument("--execute", action="store_true",
                    help="send real orders (also needs dry_run: false in the config)")
    a = ap.parse_args(argv)
    try:
        cfg = load(a.config)        # a YAML error arrives as a ValueError without the line
    except (OSError, ValueError, TypeError) as e:
        print(f"FAIL config {a.config}: {e}")
        return 1
    if a.command not in ("run", "flat") or not a.execute:
        cfg.dry_run = True
    Path(cfg.log_path).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(cfg.log_path, encoding="utf-8")])
    from .broker_mt5 import MT5Broker
    try:
        b = MT5Broker(cfg.mt5_path, probe=cfg.symbols[cfg.keepalive_symbol],
                      strict=a.command == "run", rule=cfg.server_clock, login=cfg.login)
        acct = b.account()
    except ImportError as e:
        print(f"FAIL the MetaTrader5 package is missing from this Python ({e}): "
              "run deploy\\ftmo\\setup.ps1, then start the bot with deploy\\ftmo\\run.ps1")
        return 1
    except RuntimeError as e:
        print(f"FAIL cannot reach the MT5 terminal: {str(e).rstrip('.')}. With several "
              "MT5 terminals installed, set mt5_path in the config to FTMO's terminal64.exe.")
        return 1
    print(f"account {acct.login} on {acct.server}, {acct.currency} "
          f"balance {acct.balance:,.2f} equity {acct.equity:,.2f}, "
          f"algo trading {'ON' if acct.trade_allowed else 'OFF'}")
    print(f"server clock: {b.clock_status()}")
    if cfg.login is not None and acct.login != cfg.login:
        print(f"FAIL the terminal is on account {acct.login} ({acct.server}) but "
              f"{a.config} is for account {cfg.login}: log the terminal into "
              f"{cfg.login}, or set login: to this account in the config")
        return 1
    if not cfg.dry_run and cfg.login is None:        # orders could go out
        print(f"REFUSED: orders go only to the account named in the config. If "
              f"{acct.login} on {acct.server} is the account to trade, set "
              f"`login: {acct.login}` in {a.config} (replace the `login: null` line) "
              "and start again.")
        return 1
    if a.command == "plan":
        try:
            r = Runner(cfg, b, readonly=True)   # reads state; never moves or saves it
        except RuntimeError as e:
            print(f"FAIL {e}")
            return 1
        held = r.st.held
        print(f"held by the bot: {held or 'nothing'}")
        print(f"exits for new positions: {exit_rule(cfg)}")
        res = r.compute_plan(b.now())
        if res is None:
            print("no plan: symbols do not share a completed session (see log)")
            return 1
        day, p = res
        print(f"plan from the {day} session, for the next open (09:31-10:30 NY):")
        print(f"  exits:   {', '.join(p.exits) or 'none'}")
        for s in p.entries:
            _, ask = b.quote(cfg.symbols[s])
            print(f"  entry:   {s} at ~{ask:.2f}, stop ~"
                  f"{ask - cfg.atr_stop_mult * p.atr[s]:.2f} "
                  f"({cfg.risk_per_trade:.0%} of balance at risk)")
        if not p.entries:
            print("  entries: none")
        return 0
    if a.command == "preflight":
        now = b.now()
        ok = True
        try:
            r = Runner(cfg, b, readonly=True)       # the start-up checks of `run`
        except RuntimeError as e:
            print(f"FAIL {e}")
            ok = False
        else:                                       # compare with FTMO's dashboard
            print(rules_line(r))
            print(f"exits for new positions: {exit_rule(cfg)}")
            print(f"risk cap: {cap_rule(cfg)}")
        if cfg.login is None:
            print(f"WARN: login not set; run.ps1 -Live and -Flat need `login: "
                  f"{acct.login}` in {a.config} (replace the `login: null` line; "
                  "the account this terminal is on)")
        for s, sym in cfg.symbols.items():
            spec = b.spec(sym)
            if not spec.exists:
                print(f"FAIL {s}: symbol {sym} not found in Market Watch")
                ok = False
                continue
            ss = [x for x in sessions.build(b.bars(sym, 30, BAR_COUNT), 30, now)
                  if x.complete]
            if len(ss) < 2:
                print(f"FAIL {s}: {len(ss)} completed sessions in the terminal's history")
                ok = False
                continue
            ind = fast4.indicators(ss)
            verdict = "PASS" if len(ss) >= MIN_SESSIONS else "FAIL"
            print(f"{verdict} {s} ({sym}): lots {spec.volume_min}-{spec.volume_max} "
                  f"step {spec.volume_step}; {len(ss)} sessions, last "
                  f"{ss[-1].day} close {ind.close:.2f}, SMA200 "
                  f"{ind.sma200 if ind.sma200 is None else round(ind.sma200, 2)}, "
                  f"RSI2 {ind.rsi2:.1f}, ATR {ind.atr14:.2f}"
                  + ("  <- ENTRY SIGNAL" if ind.sma200 and ind.close > ind.sma200
                     and ind.rsi2 < 10 else ""))
            if len(ss) < MIN_SESSIONS:
                print(f"FAIL {s}: only {len(ss)} sessions; need {MIN_SESSIONS}+ "
                      "(raise Tools > Options > Charts > Max bars in chart)")
                ok = False
        if b.verified_at is None:
            print("WARN: server clock unverified (no fresh tick); run the preflight "
                  "again while the index CFDs are trading")
        if not acct.trade_allowed:
            print("WARN: enable Algo Trading in the terminal before `run --execute`")
        return 0 if ok else 1
    guard = lock.for_state(cfg.state_path)
    if not guard.acquire():
        print("another ftmo_bot process holds this state file (is `run` still "
              "going?). Stop it first (Ctrl+C in its window), then try again.")
        return 1
    try:
        try:
            r = Runner(cfg, b, readonly=a.command == "flat" and cfg.dry_run)
        except RuntimeError as e:
            print(f"FAIL {e}")
            if a.command == "flat":
                print("nothing was closed (open positions keep their stop-losses); "
                      "fix that and run flat again")
            return 1
        if a.command == "flat":
            live = b.positions(cfg.magic)
            if cfg.dry_run:
                print(f"DRY-RUN: {len(live)} bot position(s) would be closed; "
                      "nothing sent, state unchanged")
                r.stand_down(b.now(), live)          # logs only
                return 1 if live else 0
            print(f"closing {len(live)} bot position(s)")
            r.stand_down(b.now(), live)
            left = b.positions(cfg.magic)
            print("flat" if not left else
                  f"{len(left)} position(s) still open; run flat again")
            return 0 if not left else 1
        print(rules_line(r))
        r.run()
        return 0
    finally:
        guard.release()


if __name__ == "__main__":
    sys.exit(main())
