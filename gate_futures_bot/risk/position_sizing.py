"""
Position sizing utilities using the Kelly Criterion and drawdown guard.
"""

from __future__ import annotations

import numpy as np

from utils.logger import get_logger

logger = get_logger(__name__)


def kelly_size(
    balance: float,
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    max_pct: float,
) -> float:
    """
    Compute position size in USDT using the Kelly Criterion.

    Kelly formula
    -------------
    f* = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win

    The result is capped at *max_pct* of *balance*.

    Parameters
    ----------
    balance  : Available USDT balance.
    win_rate : Historical fraction of winning trades (0–1).
    avg_win  : Average winning trade return (positive, in price units or pct).
    avg_loss : Average losing trade return (positive magnitude).
    max_pct  : Maximum fraction of balance to risk (e.g. 0.20 = 20 %).

    Returns
    -------
    float
        Position size in USDT (≥ 0).
    """
    balance = np.float64(balance)
    win_rate = np.float64(win_rate)
    avg_win = np.float64(avg_win)
    avg_loss = np.float64(avg_loss)
    max_pct = np.float64(max_pct)

    if avg_win <= 0.0:
        logger.warning("avg_win must be positive; returning 0 size")
        return 0.0

    kelly_fraction = (win_rate * avg_win - (1.0 - win_rate) * avg_loss) / avg_win
    kelly_fraction = float(np.clip(kelly_fraction, 0.0, max_pct))

    size = float(balance * kelly_fraction)
    logger.info(
        "Kelly size computed",
        extra={
            "balance": float(balance),
            "win_rate": float(win_rate),
            "avg_win": float(avg_win),
            "avg_loss": float(avg_loss),
            "kelly_fraction": kelly_fraction,
            "size_usdt": size,
        },
    )
    return size


def check_drawdown(
    peak_balance: float,
    current_balance: float,
    max_dd_pct: float,
) -> bool:
    """
    Check whether the current drawdown exceeds the maximum allowed threshold.

    Parameters
    ----------
    peak_balance    : Highest observed account balance.
    current_balance : Current account balance.
    max_dd_pct      : Maximum drawdown fraction before halting (e.g. 0.15 = 15 %).

    Returns
    -------
    bool
        ``True`` if the drawdown limit has been breached (halt signal).
    """
    peak_balance = np.float64(peak_balance)
    current_balance = np.float64(current_balance)
    max_dd_pct = np.float64(max_dd_pct)

    if peak_balance <= 0.0:
        return False

    drawdown = float((peak_balance - current_balance) / peak_balance)
    breached = drawdown >= float(max_dd_pct)

    logger.info(
        "Drawdown check",
        extra={
            "peak_balance": float(peak_balance),
            "current_balance": float(current_balance),
            "drawdown_pct": drawdown,
            "max_dd_pct": float(max_dd_pct),
            "breached": breached,
        },
    )
    return breached
