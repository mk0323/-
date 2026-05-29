"""
RSI Divergence Strategy.

Detects bullish/bearish divergence between price and RSI:
- Bullish divergence: price makes lower low, RSI makes higher low → long
- Bearish divergence: price makes higher high, RSI makes lower high → short
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy
from utils.logger import get_logger

logger = get_logger(__name__)


def _calc_rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    delta = np.diff(close)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    rsi = np.full(len(close), np.nan)
    if len(gain) < period:
        return rsi
    avg_gain = np.mean(gain[:period])
    avg_loss = np.mean(loss[:period])
    for i in range(period, len(delta)):
        avg_gain = (avg_gain * (period - 1) + gain[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss[i]) / period
        rs = avg_gain / (avg_loss + 1e-10)
        rsi[i + 1] = 100 - 100 / (1 + rs)
    return rsi


class RSIDivergenceStrategy(BaseStrategy):
    """Detect price/RSI divergence for counter-trend entries."""

    def __init__(self, rsi_period: int = 14, lookback: int = 20) -> None:
        self.rsi_period = rsi_period
        self.lookback = lookback

    def compute_signal(self, df: pd.DataFrame) -> int:
        if len(df) < self.rsi_period + self.lookback + 5:
            return 0

        close = df["close"].to_numpy(dtype=np.float64)
        rsi = _calc_rsi(close, self.rsi_period)

        window = min(self.lookback, len(close) - 1)
        recent_close = close[-window:]
        recent_rsi = rsi[-window:]

        valid = ~np.isnan(recent_rsi)
        if valid.sum() < 4:
            return 0

        rc = recent_close[valid]
        rr = recent_rsi[valid]

        # Bearish divergence: price higher high, RSI lower high
        if rc[-1] > rc[:-1].max() and rr[-1] < rr[:-1].max():
            logger.info("RSI Divergence: bearish divergence detected")
            return -1

        # Bullish divergence: price lower low, RSI higher low
        if rc[-1] < rc[:-1].min() and rr[-1] > rr[:-1].min():
            logger.info("RSI Divergence: bullish divergence detected")
            return 1

        return 0

    def should_exit(self, df: pd.DataFrame, current_position: int) -> bool:
        if current_position == 0:
            return False
        close = df["close"].to_numpy(dtype=np.float64)
        rsi = _calc_rsi(close, self.rsi_period)
        last_rsi = rsi[~np.isnan(rsi)][-1] if (~np.isnan(rsi)).any() else 50.0
        if current_position == 1 and last_rsi > 70:
            return True
        if current_position == -1 and last_rsi < 30:
            return True
        return False
