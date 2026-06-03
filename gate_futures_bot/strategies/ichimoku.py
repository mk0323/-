"""
Ichimoku Cloud Strategy.

Classic Ichimoku Kinko Hyo signals:
- Long: price above cloud, Tenkan > Kijun, bullish kumo twist ahead
- Short: price below cloud, Tenkan < Kijun, bearish kumo twist ahead
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy
from utils.logger import get_logger

logger = get_logger(__name__)


def _ichimoku(df: pd.DataFrame):
    high = df["high"]
    low = df["low"]
    close = df["close"]

    tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2
    kijun = (high.rolling(26).max() + low.rolling(26).min()) / 2
    senkou_a = ((tenkan + kijun) / 2).shift(26)
    senkou_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)

    return tenkan, kijun, senkou_a, senkou_b


class IchimokuStrategy(BaseStrategy):
    """Ichimoku Cloud trend-following strategy."""

    def compute_signal(self, df: pd.DataFrame) -> int:
        if len(df) < 80:
            return 0

        tenkan, kijun, senkou_a, senkou_b = _ichimoku(df)

        def _safe(v):
            try:
                f = float(v)
                return f if not np.isnan(f) else None
            except (TypeError, ValueError):
                return None

        price = _safe(df["close"].iloc[-1])
        t  = _safe(tenkan.iloc[-1])
        k  = _safe(kijun.iloc[-1])
        sa = _safe(senkou_a.iloc[-1])
        sb = _safe(senkou_b.iloc[-1])

        if any(v is None for v in [price, t, k, sa, sb]):
            return 0

        cloud_top = max(sa, sb)
        cloud_bottom = min(sa, sb)

        # Bullish: price above cloud, tenkan > kijun
        if price > cloud_top and t > k:
            logger.info("Ichimoku: bullish signal")
            return 1
        # Bearish: price below cloud, tenkan < kijun
        if price < cloud_bottom and t < k:
            logger.info("Ichimoku: bearish signal")
            return -1
        return 0

    def should_exit(self, df: pd.DataFrame, current_position: int) -> bool:
        if current_position == 0 or len(df) < 80:
            return False
        tenkan, kijun, _, _ = _ichimoku(df)
        t = float(tenkan.iloc[-1])
        k = float(kijun.iloc[-1])
        if current_position == 1 and t < k:
            return True
        if current_position == -1 and t > k:
            return True
        return False
