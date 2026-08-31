#!/usr/bin/env python3
"""Fetch daily adjusted closes for the CAD universe and a long-history US
proxy universe. Runs on GitHub Actions (this repo's dev container has no
market-data egress).

Adjusted closes approximate total return (distributions reinvested) — the
standard assumption; stated in the report.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import yfinance as yf

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from engine.config import load_config  # noqa: E402

US_PROXY = ["SPY", "EFA", "EEM", "AGG"]   # long history: US, intl dev, EM, bonds


def fetch(symbols: list[str], out_csv: Path) -> pd.DataFrame:
    df = yf.download(symbols, start="1999-01-01", interval="1d",
                     auto_adjust=True, progress=False)["Close"]
    if isinstance(df, pd.Series):
        df = df.to_frame(symbols[0])
    df = df[symbols].dropna(how="all")
    missing = [s for s in symbols if s not in df.columns or df[s].dropna().empty]
    if missing:
        raise SystemExit(f"no data for {missing} — refusing to write a partial file")
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, float_format="%.6f")
    return df


def main() -> None:
    cfg = load_config(REPO / "config" / "engine.toml")
    cad = fetch(list(cfg.universe), REPO / "data" / "prices_cad.csv")
    us = fetch(US_PROXY, REPO / "data" / "prices_us.csv")
    meta = {
        "fetched": date.today().isoformat(),
        "source": "yahoo finance adjusted close (total-return approximation)",
        "cad": {"symbols": list(cad.columns), "rows": len(cad),
                "start": str(cad.index[0].date()), "end": str(cad.index[-1].date()),
                "common_start": str(cad.dropna().index[0].date())},
        "us": {"symbols": list(us.columns), "rows": len(us),
               "start": str(us.index[0].date()), "end": str(us.index[-1].date()),
               "common_start": str(us.dropna().index[0].date())},
    }
    (REPO / "data" / "meta.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
