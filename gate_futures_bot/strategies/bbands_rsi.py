"""
Bollinger Bands + RSI composite mean-reversion strategy.

Signal logic
------------
Long entry  : close <= lower_band  AND  RSI < RSI_OVERSOLD
Short entry : close >= upper_band  AND  RSI > RSI_OVERBOUGHT
Exit        : close crosses (or touches) the middle band
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy
from utils.logger import get_logger
import config

logger = get_logger(__name__)


class BBandsRSIStrategy(BaseStrategy):
    """Bollinger Bands + RSI mean-reversion strategy."""

    def __init__(
        self,
        bb_period: int = config.BBANDS_RSI_BB_PERIOD,
        bb_std: float = config.BBANDS_RSI_BB_STD,
        rsi_period: int = config.BBANDS_RSI_RSI_PERIOD,
        rsi_oversold: int = config.BBANDS_RSI_RSI_OVERSOLD,
        rsi_overbought: int = config.BBANDS_RSI_RSI_OVERBOUGHT,
    ) -> None:
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought

    # ------------------------------------------------------------------
    # Internal helpers (pure numpy/pandas — no external ta library)
    # ------------------------------------------------------------------

    def _compute_indicators(self, df: pd.DataFrame) -> dict:
        """Compute Bollinger Bands and RSI using numpy/pandas."""
        close = df["close"].astype(np.float64)

        # Bollinger Bands
        rolling = close.rolling(self.bb_period)
        middle = rolling.mean()
        std = rolling.std(ddof=0)
        upper = middle + self.bb_std * std
        lower = middle - self.bb_std * std

        # RSI via Wilder smoothing (EWM with com = period-1)
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(com=self.rsi_period - 1, min_periods=self.rsi_period).mean()
        avg_loss = loss.ewm(com=self.rsi_period - 1, min_periods=self.rsi_period).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100.0 - (100.0 / (1.0 + rs))

        return {
            "close": float(close.iloc[-1]),
            "prev_close": float(close.iloc[-2]) if len(close) >= 2 else float(close.iloc[-1]),
            "upper": float(upper.iloc[-1]),
            "middle": float(middle.iloc[-1]),
            "lower": float(lower.iloc[-1]),
            "prev_middle": float(middle.iloc[-2]) if len(close) >= 2 else np.nan,
            "rsi": float(rsi.iloc[-1]),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_signal(self, df: pd.DataFrame) -> int:
        """
        Return 1, -1, or 0 based on Bollinger Bands + RSI conditions.
        """
        min_rows = max(self.bb_period, self.rsi_period) + 5
        if len(df) < min_rows:
            logger.warning(
                "Insufficient data for BBandsRSI signal",
                extra={"required": min_rows, "available": len(df)},
            )
            return 0

        ind = self._compute_indicators(df)

        if np.isnan(ind["upper"]) or np.isnan(ind["rsi"]):
            logger.warning("NaN indicator values; returning flat signal")
            return 0

        if ind["close"] <= ind["lower"] and ind["rsi"] < self.rsi_oversold:
            logger.info(
                "BBandsRSI long signal",
                extra={
                    "close": ind["close"],
                    "lower_bb": ind["lower"],
                    "rsi": ind["rsi"],
                },
            )
            return 1

        if ind["close"] >= ind["upper"] and ind["rsi"] > self.rsi_overbought:
            logger.info(
                "BBandsRSI short signal",
                extra={
                    "close": ind["close"],
                    "upper_bb": ind["upper"],
                    "rsi": ind["rsi"],
                },
            )
            return -1

        return 0

    def should_exit(self, df: pd.DataFrame, current_position: int) -> bool:
        """
        Exit when price crosses (or touches) the middle Bollinger Band.
        """
        if current_position == 0:
            return False

        min_rows = self.bb_period + 2
        if len(df) < min_rows:
            return False

        ind = self._compute_indicators(df)
        if np.isnan(ind["middle"]) or np.isnan(ind["prev_middle"]):
            return False

        close = ind["close"]
        prev_close = ind["prev_close"]
        mid = ind["middle"]
        prev_mid = ind["prev_middle"]

        # Long exit: price crosses above (or reaches) the middle band
        if current_position == 1 and (prev_close < prev_mid) and (close >= mid):
            logger.info("BBandsRSI exit: close crossed middle band (long exit)")
            return True

        # Short exit: price crosses below (or reaches) the middle band
        if current_position == -1 and (prev_close > prev_mid) and (close <= mid):
            logger.info("BBandsRSI exit: close crossed middle band (short exit)")
            return True

        return False
