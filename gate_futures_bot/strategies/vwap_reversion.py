"""
VWAP Reversion Strategy.

Mean-reversion using VWAP + standard deviation bands.
- Long when price dips below VWAP - 1.5σ (oversold)
- Short when price rises above VWAP + 1.5σ (overbought)
- Exit when price returns to VWAP
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy
from utils.logger import get_logger

logger = get_logger(__name__)


def _rolling_vwap(df: pd.DataFrame, window: int) -> tuple[np.ndarray, np.ndarray]:
    """Calculate rolling VWAP and std-dev of price from VWAP."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"]
    tp_vol = tp * vol

    vwap = tp_vol.rolling(window).sum() / vol.rolling(window).sum()
    std = tp.rolling(window).std()
    return vwap.to_numpy(dtype=np.float64), std.to_numpy(dtype=np.float64)


class VWAPReversionStrategy(BaseStrategy):
    """VWAP mean-reversion with sigma bands."""

    def __init__(self, window: int = 20, sigma: float = 1.5) -> None:
        self.window = window
        self.sigma = sigma

    def compute_signal(self, df: pd.DataFrame) -> int:
        if len(df) < self.window + 5:
            return 0

        vwap, std = _rolling_vwap(df, self.window)
        last_price = float(df["close"].iloc[-1])
        v = vwap[-1]
        s = std[-1]

        if np.isnan(v) or np.isnan(s) or s == 0:
            return 0

        upper = v + self.sigma * s
        lower = v - self.sigma * s

        if last_price < lower:
            logger.info("VWAP Reversion: oversold — long signal", extra={"price": last_price, "lower": lower})
            return 1
        if last_price > upper:
            logger.info("VWAP Reversion: overbought — short signal", extra={"price": last_price, "upper": upper})
            return -1
        return 0

    def should_exit(self, df: pd.DataFrame, current_position: int) -> bool:
        if current_position == 0:
            return False
        vwap, _ = _rolling_vwap(df, self.window)
        last_price = float(df["close"].iloc[-1])
        v = vwap[-1]
        if np.isnan(v):
            return False
        # Exit when price crosses back to VWAP
        if current_position == 1 and last_price >= v:
            return True
        if current_position == -1 and last_price <= v:
            return True
        return False
