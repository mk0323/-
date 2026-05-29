"""
Dual EMA Crossover strategy.

Reference
---------
Faber, M. T. (2007). "A Quantitative Approach to Tactical Asset Allocation."
Journal of Wealth Management.

Signal logic
------------
- Long  when fast EMA > slow EMA (uptrend)
- Short when fast EMA < slow EMA (downtrend)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy
from utils.logger import get_logger
import config

logger = get_logger(__name__)


class DualMAStrategy(BaseStrategy):
    """Dual exponential moving average crossover strategy."""

    def __init__(
        self,
        fast_period: int = config.DUAL_MA_FAST_PERIOD,
        slow_period: int = config.DUAL_MA_SLOW_PERIOD,
    ) -> None:
        if fast_period >= slow_period:
            raise ValueError(
                f"fast_period ({fast_period}) must be less than slow_period ({slow_period})"
            )
        self.fast_period = fast_period
        self.slow_period = slow_period

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_emas(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        close = df["close"].astype(np.float64)
        fast_ema = close.ewm(span=self.fast_period, adjust=False).mean()
        slow_ema = close.ewm(span=self.slow_period, adjust=False).mean()
        return fast_ema, slow_ema

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_signal(self, df: pd.DataFrame) -> int:
        """
        Return 1 (long) or -1 (short) based on the latest EMA crossover.
        Returns 0 if there is insufficient data.
        """
        min_rows = self.slow_period * 3  # need enough warm-up bars
        if len(df) < min_rows:
            logger.warning(
                "Insufficient data for DualMA signal",
                extra={"required": min_rows, "available": len(df)},
            )
            return 0

        fast_ema, slow_ema = self._compute_emas(df)
        latest_fast = float(fast_ema.iloc[-1])
        latest_slow = float(slow_ema.iloc[-1])

        signal = 1 if latest_fast > latest_slow else -1
        logger.info(
            "DualMA signal computed",
            extra={
                "fast_ema": latest_fast,
                "slow_ema": latest_slow,
                "signal": signal,
            },
        )
        return signal

    def should_exit(self, df: pd.DataFrame, current_position: int) -> bool:
        """
        Exit when a crossover occurs in the opposite direction.
        """
        if current_position == 0:
            return False

        fast_ema, slow_ema = self._compute_emas(df)
        if len(fast_ema) < 2:
            return False

        # Detect a crossover on the last bar
        prev_fast, curr_fast = float(fast_ema.iloc[-2]), float(fast_ema.iloc[-1])
        prev_slow, curr_slow = float(slow_ema.iloc[-2]), float(slow_ema.iloc[-1])

        crossed_down = (prev_fast >= prev_slow) and (curr_fast < curr_slow)
        crossed_up = (prev_fast <= prev_slow) and (curr_fast > curr_slow)

        if current_position == 1 and crossed_down:
            logger.info("DualMA exit: fast crossed below slow (long exit)")
            return True
        if current_position == -1 and crossed_up:
            logger.info("DualMA exit: fast crossed above slow (short exit)")
            return True

        return False
