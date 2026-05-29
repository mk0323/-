"""
Abstract base class for all trading strategies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class BaseStrategy(ABC):
    """All strategies must implement this interface."""

    @abstractmethod
    def compute_signal(self, df: pd.DataFrame) -> int:
        """
        Compute the directional signal given OHLCV history.

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV DataFrame with columns [time, open, high, low, close, volume].

        Returns
        -------
        int
            ``1``  — go long
            ``-1`` — go short
            ``0``  — stay flat / no signal
        """

    @abstractmethod
    def should_exit(self, df: pd.DataFrame, current_position: int) -> bool:
        """
        Determine whether the current open position should be closed.

        Parameters
        ----------
        df               : Latest OHLCV DataFrame.
        current_position : ``1`` (long), ``-1`` (short), or ``0`` (flat).

        Returns
        -------
        bool
            ``True`` if the position should be closed before placing a new one.
        """
