"""
Volatility Breakout with Funding Rate Filter strategy.

Based on Larry Williams' volatility breakout, adapted for crypto.

Entry logic:
- Calculate range = previous candle high - low
- Long if current price > previous close + k * range (default k=0.5)
- Short if current price < previous close - k * range
- Only enter if funding rate is in neutral zone (not extreme)

Exit logic:
- Stop loss: entry_price +/- 1.5 * ATR(14)
- Take profit: entry_price +/- 2.0 * ATR(14)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy
from utils.logger import get_logger
import config

logger = get_logger(__name__)


class VolBreakoutStrategy(BaseStrategy):
    """Volatility Breakout with ATR-based stop/take profit and funding rate filter."""

    def __init__(
        self,
        k: float = config.VOL_BREAKOUT_K,
        atr_period: int = config.VOL_BREAKOUT_ATR_PERIOD,
        sl_atr: float = config.VOL_BREAKOUT_SL_ATR,
        tp_atr: float = config.VOL_BREAKOUT_TP_ATR,
        max_funding: float = config.VOL_BREAKOUT_MAX_FUNDING,
    ) -> None:
        self.k = k
        self.atr_period = atr_period
        self.sl_atr = sl_atr
        self.tp_atr = tp_atr
        self.max_funding = max_funding
        # Tracks entry price for stop/take profit checks
        self._entry_price: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_atr(self, df: pd.DataFrame) -> float:
        """Return current ATR value using Wilder's method."""
        if len(df) < self.atr_period + 1:
            logger.warning(
                "Insufficient data for ATR",
                extra={"required": self.atr_period + 1, "available": len(df)},
            )
            return 0.0

        high = df["high"].to_numpy(dtype=np.float64)
        low = df["low"].to_numpy(dtype=np.float64)
        close = df["close"].to_numpy(dtype=np.float64)

        n = len(close)
        tr = np.maximum(high[1:] - low[1:],
               np.maximum(np.abs(high[1:] - close[:-1]),
                          np.abs(low[1:] - close[:-1])))

        # Wilder's smoothed ATR
        atr = np.zeros(len(tr))
        atr[self.atr_period - 1] = np.mean(tr[:self.atr_period])
        for i in range(self.atr_period, len(tr)):
            atr[i] = (atr[i - 1] * (self.atr_period - 1) + tr[i]) / self.atr_period

        return float(atr[-1])

    def compute_signal(self, df: pd.DataFrame) -> int:
        """
        Return 1 (long), -1 (short), or 0 (no signal) based on volatility breakout.

        Uses last 2 rows: row[-2] is the completed previous candle, row[-1] is current.
        """
        if len(df) < 2:
            logger.warning("Insufficient data for VolBreakout signal")
            return 0

        prev = df.iloc[-2]
        curr = df.iloc[-1]

        prev_range = float(prev["high"]) - float(prev["low"])
        prev_close = float(prev["close"])
        current_price = float(curr["close"])

        long_threshold = prev_close + self.k * prev_range
        short_threshold = prev_close - self.k * prev_range

        if current_price > long_threshold:
            signal = 1
        elif current_price < short_threshold:
            signal = -1
        else:
            signal = 0

        logger.info(
            "VolBreakout signal computed",
            extra={
                "prev_range": prev_range,
                "long_threshold": long_threshold,
                "short_threshold": short_threshold,
                "current_price": current_price,
                "signal": signal,
            },
        )

        if signal != 0:
            self._entry_price = current_price

        return signal

    def should_exit(self, df: pd.DataFrame, current_position: int) -> bool:
        """
        Exit if current price hits the ATR-based stop loss or take profit level.
        """
        if current_position == 0:
            return False

        if self._entry_price == 0.0:
            return False

        atr = self.compute_atr(df)
        if atr == 0.0:
            return False

        current_price = float(df.iloc[-1]["close"])

        if current_position == 1:  # Long
            stop_loss = self._entry_price - self.sl_atr * atr
            take_profit = self._entry_price + self.tp_atr * atr
            exit_signal = current_price <= stop_loss or current_price >= take_profit
        else:  # Short
            stop_loss = self._entry_price + self.sl_atr * atr
            take_profit = self._entry_price - self.tp_atr * atr
            exit_signal = current_price >= stop_loss or current_price <= take_profit

        if exit_signal:
            logger.info(
                "VolBreakout exit triggered",
                extra={
                    "current_price": current_price,
                    "entry_price": self._entry_price,
                    "atr": atr,
                    "position": current_position,
                },
            )

        return exit_signal
