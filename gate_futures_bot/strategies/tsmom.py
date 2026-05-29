"""
Time-Series Momentum strategy.

Reference
---------
Moskowitz, T., Ooi, Y. H., & Pedersen, L. H. (2012).
"Time Series Momentum." Journal of Financial Economics, 104(2), 228-250.

Signal logic
------------
- Compute the sign of the log return over LOOKBACK_DAYS candles.
- Position size is scaled by inverse realised volatility relative to a
  volatility target (vol targeting overlay).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy
from utils.logger import get_logger
import config

logger = get_logger(__name__)


class TSMOMStrategy(BaseStrategy):
    """Time-Series Momentum with volatility targeting."""

    def __init__(
        self,
        lookback_days: int = config.TSMOM_LOOKBACK_DAYS,
        vol_window: int = config.TSMOM_VOL_WINDOW,
        vol_target: float = config.TSMOM_VOL_TARGET,
    ) -> None:
        self.lookback_days = lookback_days
        self.vol_window = vol_window
        self.vol_target = vol_target

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_signal(self, df: pd.DataFrame) -> int:
        """
        Return 1 (long) or -1 (short) based on the sign of the 12-month
        log return.  Returns 0 if there is insufficient history.
        """
        if len(df) < self.lookback_days + 1:
            logger.warning(
                "Insufficient data for TSMOM signal",
                extra={"required": self.lookback_days + 1, "available": len(df)},
            )
            return 0

        close = df["close"].to_numpy(dtype=np.float64)
        log_ret_12m = np.log(close[-1] / close[-(self.lookback_days + 1)])
        signal = int(np.sign(log_ret_12m))

        logger.info(
            "TSMOM signal computed",
            extra={"log_ret_12m": float(log_ret_12m), "signal": signal},
        )
        return signal

    def compute_vol_scalar(self, df: pd.DataFrame) -> float:
        """
        Compute the volatility scalar used to size positions.

        Returns
        -------
        float
            ``VOL_TARGET / realised_vol``, capped at 2.0.
            Returns 1.0 if volatility cannot be estimated.
        """
        if len(df) < self.vol_window + 1:
            logger.warning("Insufficient data for vol scalar; defaulting to 1.0")
            return 1.0

        close = df["close"].to_numpy(dtype=np.float64)
        log_rets = np.log(close[1:] / close[:-1])
        realised_vol = float(np.std(log_rets[-self.vol_window:], ddof=1) * np.sqrt(252))

        if realised_vol <= 0.0:
            logger.warning("Realised vol is zero; defaulting scalar to 1.0")
            return 1.0

        scalar = min(self.vol_target / realised_vol, 2.0)
        logger.info(
            "Vol scalar computed",
            extra={
                "realised_vol": realised_vol,
                "vol_target": self.vol_target,
                "scalar": scalar,
            },
        )
        return scalar

    def should_exit(self, df: pd.DataFrame, current_position: int) -> bool:
        """
        Exit if the signal has flipped (momentum reversal).
        """
        if current_position == 0:
            return False
        new_signal = self.compute_signal(df)
        # Exit when new signal is non-zero and opposite to current position
        return new_signal != 0 and new_signal != current_position
