"""Dual momentum (Phase 4).

Cross-sectional: rank risk assets by lookback-minus-skip trailing return
(classic 12-1). Absolute: a winner whose own trailing return is <= 0 sends
its allocation to the defensive asset; if the defensive asset is also
negative, that share stays in cash.

Parameters are read from config [strategy] and were fixed by the published
literature BEFORE this backtest — the sensitivity grid in the Phase 4
report exists to check robustness, never to pick a better cell (§10).
"""
from __future__ import annotations

from datetime import date

import pandas as pd

TRADING_DAYS_PER_MONTH = 21


class DualMomentum:
    def __init__(self, universe: tuple[str, ...], params: dict):
        self.lookback_months = int(params.get("lookback_months", 12))
        self.skip_months = int(params.get("skip_months", 1))
        self.top_n = int(params.get("top_n", 1))
        self.defensive = params.get("defensive_symbol")
        self.absolute_filter = bool(params.get("absolute_momentum_filter", True))
        self.risk_assets = [s for s in universe if s != self.defensive]
        if self.top_n < 1 or self.top_n > len(self.risk_assets):
            raise ValueError(f"top_n {self.top_n} out of range for {len(self.risk_assets)} risk assets")

    def _momentum(self, prices: pd.DataFrame, symbol: str) -> float | None:
        """Academic L-S momentum: the return from t-L to t-S (an (L-S)-month
        window ending S months ago). The first cut of this code measured
        t-(L+S) to t-S — a 13-month span for '12-1' — which is NOT the
        configuration the literature's evidence belongs to (audit round 1).

        The window must be contiguous: positional indexing over dropna()'d
        data silently stretched 'trading days' across calendar months.
        """
        if symbol not in prices.columns:
            return None
        skip = self.skip_months * TRADING_DAYS_PER_MONTH
        look = self.lookback_months * TRADING_DAYS_PER_MONTH
        window = prices[symbol].iloc[-(look + 1):]
        if len(window) < look + 1:
            return None
        # Tolerate isolated data holes (holidays, feed glitches) but refuse
        # a window that is materially incomplete or starts/ends unknown.
        if window.isna().mean() > 0.05:
            return None
        window = window.ffill()
        if window.isna().iloc[0] or pd.isna(window.iloc[-1 - skip]):
            return None
        end = window.iloc[-1 - skip]
        start = window.iloc[0]
        if start <= 0:
            return None
        return float(end / start - 1.0)

    def target_weights(self, prices: pd.DataFrame, today: date) -> dict[str, float]:
        moms = {s: self._momentum(prices, s) for s in self.risk_assets}
        scored = {s: m for s, m in moms.items() if m is not None}
        if len(scored) < len(self.risk_assets):
            # Not enough history for a fair cross-section: stay in cash
            # rather than rank a partial menu.
            return {}
        winners = sorted(scored, key=scored.get, reverse=True)[: self.top_n]
        slice_w = 1.0 / self.top_n
        weights: dict[str, float] = {}
        defensive_share = 0.0
        for w in winners:
            if self.absolute_filter and scored[w] <= 0.0:
                defensive_share += slice_w
            else:
                weights[w] = weights.get(w, 0.0) + slice_w
        if defensive_share > 0 and self.defensive:
            dmom = self._momentum(prices, self.defensive)
            if dmom is not None and (not self.absolute_filter or dmom > 0.0):
                weights[self.defensive] = weights.get(self.defensive, 0.0) + defensive_share
            # else: that share stays in cash
        return weights
