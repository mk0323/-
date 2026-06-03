"""
Trade history logger — appends each entry/exit to a CSV file so realized PnL
and win-rate can be analyzed later and shown in the dashboard.
"""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone

from utils.logger import get_logger

logger = get_logger(__name__)

FIELDS = [
    "timestamp", "symbol", "strategy", "event", "direction",
    "price", "contracts", "notional_usdt", "pnl_usdt", "balance",
]


def _ensure_header(path: str) -> None:
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()


def record_trade(
    path: str,
    symbol: str,
    strategy: str,
    event: str,            # "entry" | "exit"
    direction: str,        # "long" | "short"
    price: float,
    contracts: int = 0,
    notional_usdt: float = 0.0,
    pnl_usdt: float = 0.0,
    balance: float = 0.0,
) -> None:
    """Append one trade event to the CSV log."""
    try:
        _ensure_header(path)
        with open(path, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writerow({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "symbol": symbol,
                "strategy": strategy,
                "event": event,
                "direction": direction,
                "price": round(price, 4),
                "contracts": contracts,
                "notional_usdt": round(notional_usdt, 4),
                "pnl_usdt": round(pnl_usdt, 4),
                "balance": round(balance, 4),
            })
    except Exception as exc:  # noqa: BLE001
        logger.warning("Trade log write failed", extra={"error": str(exc)})


def read_trades(path: str) -> list[dict]:
    """Read all trade rows from the CSV. Returns [] if the file doesn't exist."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Trade log read failed", extra={"error": str(exc)})
        return []
