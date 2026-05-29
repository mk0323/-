"""
EMA Ribbon Strategy.

Uses multiple EMAs (8, 13, 21, 34, 55, 89) — a Fibonacci ribbon.
- Long when all fast EMAs > slow EMAs (ribbon aligned bullishly)
- Short when all fast EMAs < slow EMAs (ribbon aligned bearishly)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy
from utils.logger import get_logger

logger = get_logger(__name__)

EMA_PERIODS = [8, 13, 21, 34, 55, 89]


class EMARibbonStrategy(BaseStrategy):
    """Multi-EMA ribbon trend-following strategy."""

    def __init__(self, periods: list[int] | None = None) -> None:
        self.periods = periods or EMA_PERIODS

    def _calc_emas(self, close: pd.Series) -> list[float]:
        return [float(close.ewm(span=p, adjust=False).mean().iloc[-1]) for p in self.periods]

    def compute_signal(self, df: pd.DataFrame) -> int:
        if len(df) < max(self.periods) + 5:
            return 0

        emas = self._calc_emas(df["close"])

        # All EMAs sorted descending = bullish alignment
        if all(emas[i] > emas[i + 1] for i in range(len(emas) - 1)):
            logger.info("EMA Ribbon: bullish alignment")
            return 1
        # All EMAs sorted ascending = bearish alignment
        if all(emas[i] < emas[i + 1] for i in range(len(emas) - 1)):
            logger.info("EMA Ribbon: bearish alignment")
            return -1
        return 0

    def should_exit(self, df: pd.DataFrame, current_position: int) -> bool:
        if current_position == 0:
            return False
        emas = self._calc_emas(df["close"])
        if current_position == 1:
            # Exit long if shortest EMA drops below longest
            return emas[0] < emas[-1]
        if current_position == -1:
            return emas[0] > emas[-1]
        return False
