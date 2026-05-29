"""
Supertrend Strategy.

Supertrend indicator (Olivier Seban) with ATR-based dynamic support/resistance.
- Buy when price crosses above Supertrend line
- Sell when price crosses below Supertrend line
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy
from utils.logger import get_logger

logger = get_logger(__name__)


def _supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0):
    high = df["high"].to_numpy(dtype=np.float64)
    low = df["low"].to_numpy(dtype=np.float64)
    close = df["close"].to_numpy(dtype=np.float64)
    n = len(close)

    # ATR via Wilder
    tr = np.maximum(high[1:] - low[1:],
           np.maximum(np.abs(high[1:] - close[:-1]),
                      np.abs(low[1:] - close[:-1])))
    atr = np.zeros(n)
    if n <= period:
        return np.zeros(n), np.zeros(n, dtype=int)
    atr[period] = np.mean(tr[:period])
    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i - 1]) / period

    hl2 = (high + low) / 2
    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    supertrend = np.zeros(n)
    direction = np.zeros(n, dtype=int)  # 1=up(bullish), -1=down(bearish)

    for i in range(period, n):
        if i == period:
            supertrend[i] = upper_band[i]
            direction[i] = -1
            continue

        prev_upper = supertrend[i - 1] if direction[i - 1] == -1 else upper_band[i]
        prev_lower = supertrend[i - 1] if direction[i - 1] == 1 else lower_band[i]

        final_upper = upper_band[i] if upper_band[i] < prev_upper or close[i - 1] > prev_upper else prev_upper
        final_lower = lower_band[i] if lower_band[i] > prev_lower or close[i - 1] < prev_lower else prev_lower

        if direction[i - 1] == -1:
            if close[i] > final_upper:
                direction[i] = 1
                supertrend[i] = final_lower
            else:
                direction[i] = -1
                supertrend[i] = final_upper
        else:
            if close[i] < final_lower:
                direction[i] = -1
                supertrend[i] = final_upper
            else:
                direction[i] = 1
                supertrend[i] = final_lower

    return supertrend, direction


class SupertrendStrategy(BaseStrategy):
    """Trend-following strategy using the Supertrend indicator."""

    def __init__(self, period: int = 10, multiplier: float = 3.0) -> None:
        self.period = period
        self.multiplier = multiplier

    def compute_signal(self, df: pd.DataFrame) -> int:
        if len(df) < self.period + 5:
            return 0

        _, direction = _supertrend(df, self.period, self.multiplier)

        prev_dir = direction[-2]
        curr_dir = direction[-1]

        if prev_dir == -1 and curr_dir == 1:
            logger.info("Supertrend: bullish crossover")
            return 1
        if prev_dir == 1 and curr_dir == -1:
            logger.info("Supertrend: bearish crossover")
            return -1
        return 0

    def should_exit(self, df: pd.DataFrame, current_position: int) -> bool:
        if current_position == 0:
            return False
        _, direction = _supertrend(df, self.period, self.multiplier)
        curr_dir = direction[-1]
        if current_position == 1 and curr_dir == -1:
            return True
        if current_position == -1 and curr_dir == 1:
            return True
        return False
