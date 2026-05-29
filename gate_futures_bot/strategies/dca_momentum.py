"""
DCA Momentum Strategy (Partial/Scaled Entry).

Designed for 10x leverage: instead of all-in entry, scales into positions
in 3 tranches (33% each) as momentum confirms.

Entry logic:
- Tranche 1: EMA20 crosses EMA50 (initial signal)
- Tranche 2: Price pulls back to EMA20 after initial breakout
- Tranche 3: RSI crosses above 50 from below (momentum confirmation)

This gives an average entry price better than all-in, reducing liquidation risk.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy
from utils.logger import get_logger

logger = get_logger(__name__)


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    return 100 - 100 / (1 + rs)


class DCAMomentumStrategy(BaseStrategy):
    """Scaled entry momentum strategy for high-leverage trading."""

    def __init__(self) -> None:
        self._tranche = 0      # 0 = flat, 1-3 = tranches filled
        self._direction = 0
        self._entry_prices: list[float] = []

    @property
    def avg_entry_price(self) -> float:
        if not self._entry_prices:
            return 0.0
        return sum(self._entry_prices) / len(self._entry_prices)

    @property
    def tranche(self) -> int:
        return self._tranche

    def compute_signal(self, df: pd.DataFrame) -> int:
        if len(df) < 60:
            return 0

        close = df["close"]
        ema20 = _ema(close, 20)
        ema50 = _ema(close, 50)
        rsi = _rsi(close)
        price = float(close.iloc[-1])

        e20 = float(ema20.iloc[-1])
        e50 = float(ema50.iloc[-1])
        e20_prev = float(ema20.iloc[-2])
        e50_prev = float(ema50.iloc[-2])
        rsi_curr = float(rsi.iloc[-1])
        rsi_prev = float(rsi.iloc[-2])

        # ── Tranche 1: EMA crossover ──────────────────────────────────
        if self._tranche == 0:
            if e20_prev <= e50_prev and e20 > e50:
                self._tranche = 1
                self._direction = 1
                self._entry_prices = [price]
                logger.info("DCA Momentum: Tranche 1 LONG (EMA crossover)", extra={"price": price})
                return 1
            if e20_prev >= e50_prev and e20 < e50:
                self._tranche = 1
                self._direction = -1
                self._entry_prices = [price]
                logger.info("DCA Momentum: Tranche 1 SHORT (EMA crossover)", extra={"price": price})
                return -1

        # ── Tranche 2: Pullback to EMA20 ──────────────────────────────
        elif self._tranche == 1:
            if self._direction == 1 and price <= e20 * 1.002 and price >= e20 * 0.998:
                self._tranche = 2
                self._entry_prices.append(price)
                logger.info("DCA Momentum: Tranche 2 LONG (pullback)", extra={"price": price})
                return 1
            if self._direction == -1 and price >= e20 * 0.998 and price <= e20 * 1.002:
                self._tranche = 2
                self._entry_prices.append(price)
                logger.info("DCA Momentum: Tranche 2 SHORT (pullback)", extra={"price": price})
                return -1

        # ── Tranche 3: RSI confirmation ───────────────────────────────
        elif self._tranche == 2:
            if self._direction == 1 and rsi_prev < 50 and rsi_curr >= 50:
                self._tranche = 3
                self._entry_prices.append(price)
                logger.info("DCA Momentum: Tranche 3 LONG (RSI confirm)", extra={"price": price, "avg": self.avg_entry_price})
                return 1
            if self._direction == -1 and rsi_prev > 50 and rsi_curr <= 50:
                self._tranche = 3
                self._entry_prices.append(price)
                logger.info("DCA Momentum: Tranche 3 SHORT (RSI confirm)", extra={"price": price, "avg": self.avg_entry_price})
                return -1

        return 0

    def should_exit(self, df: pd.DataFrame, current_position: int) -> bool:
        if current_position == 0:
            return False

        close = df["close"]
        ema20 = _ema(close, 20)
        ema50 = _ema(close, 50)
        price = float(close.iloc[-1])
        e20 = float(ema20.iloc[-1])
        e50 = float(ema50.iloc[-1])

        exit_signal = False
        if current_position == 1 and e20 < e50:
            exit_signal = True
        if current_position == -1 and e20 > e50:
            exit_signal = True

        if exit_signal:
            self._tranche = 0
            self._direction = 0
            self._entry_prices = []

        return exit_signal
