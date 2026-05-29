"""
Backtest engine for Gate.io futures trading strategies.

Signal is computed on data up to bar t; trade executes at bar t+1 open.
No lookahead bias.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from strategies.base import BaseStrategy


def run_backtest(
    strategy: "BaseStrategy",
    df: pd.DataFrame,
    initial_capital: float = 1000.0,
    leverage: int = 1,
) -> dict:
    """
    Simulate trades for a strategy on historical OHLCV data.

    Parameters
    ----------
    strategy        : Any strategy implementing BaseStrategy interface.
    df              : OHLCV DataFrame with columns [time, open, high, low, close, volume].
    initial_capital : Starting capital in USDT.
    leverage        : Leverage multiplier.

    Returns
    -------
    dict with keys:
        total_return_pct, win_rate, avg_win, avg_loss,
        max_drawdown_pct, sharpe_ratio, num_trades, equity_curve
    """
    n = len(df)

    if n < 3:
        return _empty_metrics(initial_capital)

    equity = initial_capital
    equity_curve = []
    trade_log = []  # list of (pnl_pct) per completed trade

    current_position = 0  # 1=long, -1=short, 0=flat
    entry_price = 0.0

    for t in range(n - 1):
        # Compute signal on data up to and including bar t (no lookahead)
        sub_df = df.iloc[: t + 1]
        try:
            signal = strategy.compute_signal(sub_df)
        except Exception:
            signal = 0

        # Bar t+1 open price — execution price
        exec_price = float(df["open"].iloc[t + 1])
        if exec_price <= 0:
            equity_curve.append(equity)
            continue

        # --- Exit existing position ---
        if current_position != 0:
            should_exit = False
            try:
                should_exit = strategy.should_exit(sub_df, current_position)
            except Exception:
                pass

            if should_exit or (signal != 0 and signal != current_position):
                # Close at exec_price
                pnl_pct = current_position * (exec_price - entry_price) / entry_price * leverage
                trade_pnl = equity * pnl_pct
                equity += trade_pnl
                equity = max(equity, 0.0)
                trade_log.append(pnl_pct)
                current_position = 0
                entry_price = 0.0

        # --- Enter new position ---
        if signal != 0 and current_position == 0:
            current_position = signal
            entry_price = exec_price

        equity_curve.append(equity)

    # Close any open position at the last bar's close
    if current_position != 0 and entry_price > 0.0:
        last_price = float(df["close"].iloc[-1])
        if last_price > 0:
            pnl_pct = current_position * (last_price - entry_price) / entry_price * leverage
            trade_pnl = equity * pnl_pct
            equity += trade_pnl
            equity = max(equity, 0.0)
            trade_log.append(pnl_pct)

    equity_curve.append(equity)

    return _compute_metrics(initial_capital, equity, equity_curve, trade_log)


def _compute_metrics(
    initial_capital: float,
    final_equity: float,
    equity_curve: list,
    trade_log: list,
) -> dict:
    ec = np.array(equity_curve, dtype=np.float64)
    num_trades = len(trade_log)

    # Total return
    total_return_pct = (final_equity - initial_capital) / initial_capital * 100.0

    # Win rate
    if num_trades == 0:
        win_rate = 0.0
        avg_win = 0.0
        avg_loss = 0.0
    else:
        tl = np.array(trade_log, dtype=np.float64)
        wins = tl[tl > 0]
        losses = tl[tl < 0]
        win_rate = float(len(wins) / num_trades)
        avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.0
        avg_loss = float(np.mean(np.abs(losses))) if len(losses) > 0 else 0.0

    # Max drawdown
    if len(ec) < 2:
        max_drawdown_pct = 0.0
    else:
        peak = np.maximum.accumulate(ec)
        dd = np.where(peak > 0, (peak - ec) / peak, 0.0)
        max_drawdown_pct = float(np.max(dd) * 100.0)

    # Sharpe ratio (annualised, 0 risk-free rate)
    # Use bar-to-bar equity returns
    if len(ec) < 2:
        sharpe_ratio = 0.0
    else:
        bar_returns = np.diff(ec) / np.where(ec[:-1] > 0, ec[:-1], np.nan)
        bar_returns = bar_returns[np.isfinite(bar_returns)]
        if len(bar_returns) < 2:
            sharpe_ratio = 0.0
        else:
            std = float(np.std(bar_returns, ddof=1))
            if std <= 0.0:
                sharpe_ratio = 0.0
            else:
                mean_ret = float(np.mean(bar_returns))
                # Annualise assuming ~252 trading days
                sharpe_ratio = float(mean_ret / std * np.sqrt(252))

    return {
        "total_return_pct": round(total_return_pct, 4),
        "win_rate": round(win_rate, 4),
        "avg_win": round(avg_win, 6),
        "avg_loss": round(avg_loss, 6),
        "max_drawdown_pct": round(max_drawdown_pct, 4),
        "sharpe_ratio": round(sharpe_ratio, 4),
        "num_trades": num_trades,
        "equity_curve": [round(float(v), 4) for v in ec],
    }


def _empty_metrics(initial_capital: float) -> dict:
    return {
        "total_return_pct": 0.0,
        "win_rate": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "max_drawdown_pct": 0.0,
        "sharpe_ratio": 0.0,
        "num_trades": 0,
        "equity_curve": [initial_capital],
    }
