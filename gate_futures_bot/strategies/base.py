"""
Abstract base class for all trading strategies.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import pandas as pd

logger = logging.getLogger(__name__)


class BaseStrategy(ABC):
    """All strategies must implement this interface."""

    def safe_compute_signal(self, df: pd.DataFrame) -> int:
        """Wrapper that catches any exception and returns 0 (flat) on error."""
        try:
            return self.compute_signal(df)
        except Exception as exc:
            import traceback
            logger.error(
                "compute_signal error in %s: %s\n%s",
                self.__class__.__name__, exc, traceback.format_exc(),
            )
            return 0

    def safe_should_exit(self, df: pd.DataFrame, current_position: int) -> bool:
        """Wrapper that catches any exception and returns False on error."""
        try:
            return self.should_exit(df, current_position)
        except Exception as exc:
            import traceback
            logger.error(
                "should_exit error in %s: %s\n%s",
                self.__class__.__name__, exc, traceback.format_exc(),
            )
            return False

    @abstractmethod
    def compute_signal(self, df: pd.DataFrame) -> int:
        """
        Compute the directional signal given OHLCV history.

        Returns 1 (long), -1 (short), or 0 (flat).
        """

    @abstractmethod
    def should_exit(self, df: pd.DataFrame, current_position: int) -> bool:
        """
        Determine whether the current open position should be closed.
        """
