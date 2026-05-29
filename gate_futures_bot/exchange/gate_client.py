"""
Gate.io API wrapper for USDT-margined perpetual futures.

Uses the official `gate_api` Python SDK.
Settle currency is always "usdt".
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from utils.logger import get_logger

logger = get_logger(__name__)

try:
    import gate_api
    from gate_api import ApiClient, Configuration, FuturesApi
    from gate_api.exceptions import ApiException
    _GATE_API_AVAILABLE = True
except ImportError:  # pragma: no cover
    _GATE_API_AVAILABLE = False
    ApiException = Exception

SETTLE = "usdt"


class GateClient:
    """Thin wrapper around :class:`gate_api.FuturesApi`."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        dry_run: bool = True,
    ) -> None:
        self.dry_run = dry_run

        if not _GATE_API_AVAILABLE:
            raise ImportError("gate_api is not installed. Run: pip install gate-api")

        config = Configuration(
            key=api_key,
            secret=api_secret,
        )
        config.verify_ssl = False  # workaround for proxy SSL in cloud environments
        self._client = ApiClient(configuration=config)
        self._api = FuturesApi(self._client)
        logger.info("GateClient initialised (Perpetual Futures)", extra={"dry_run": dry_run})

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def get_balance(self) -> float:
        """Return the available USDT balance in the perpetual futures account."""
        try:
            account = self._api.list_futures_accounts(SETTLE)
            available = float(account.available)
            logger.info("Fetched balance", extra={"available_usdt": available})
            return available
        except ApiException as exc:
            logger.error("get_balance failed", extra={"error": str(exc)})
            return np.nan

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def get_candles(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 500,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV candlestick data.

        Returns
        -------
        pd.DataFrame
            Columns: [time, open, high, low, close, volume]
        """
        try:
            candles = self._api.list_futures_candlesticks(
                settle=SETTLE,
                contract=symbol,
                interval=interval,
                limit=limit,
            )
        except ApiException as exc:
            logger.error("get_candles failed", extra={"symbol": symbol, "error": str(exc)})
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

        records = []
        for c in candles:
            records.append(
                {
                    "time": pd.Timestamp(c.t, unit="s", tz="UTC"),
                    "open": float(c.o),
                    "high": float(c.h),
                    "low": float(c.l),
                    "close": float(c.c),
                    "volume": float(c.v),
                }
            )

        df = pd.DataFrame(records)
        df.sort_values("time", inplace=True)
        df.reset_index(drop=True, inplace=True)
        logger.info(
            "Fetched candles",
            extra={"symbol": symbol, "interval": interval, "rows": len(df)},
        )
        return df

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------

    def get_position(self, symbol: str) -> dict:
        """
        Return current position for *symbol*.

        Keys
        ----
        size        : float  (positive = long, negative = short, 0 = flat)
        entry_price : float
        """
        try:
            pos = self._api.get_position(settle=SETTLE, contract=symbol)
            return {
                "size": float(pos.size),
                "entry_price": float(pos.entry_price),
            }
        except ApiException as exc:
            logger.error("get_position failed", extra={"symbol": symbol, "error": str(exc)})
            return {"size": 0.0, "entry_price": 0.0}

    def set_leverage(self, symbol: str, leverage: int) -> None:
        """Set leverage for *symbol*."""
        if self.dry_run:
            logger.info(
                "[DRY RUN] set_leverage skipped",
                extra={"symbol": symbol, "leverage": leverage},
            )
            return
        try:
            self._api.update_position_leverage(
                settle=SETTLE,
                contract=symbol,
                leverage=str(leverage),
            )
            logger.info("Leverage set", extra={"symbol": symbol, "leverage": leverage})
        except ApiException as exc:
            logger.error("set_leverage failed", extra={"symbol": symbol, "error": str(exc)})

    def place_order(
        self,
        symbol: str,
        size: float,
        reduce_only: bool = False,
    ) -> None:
        """
        Place a market order.

        Parameters
        ----------
        symbol      : Contract name, e.g. ``"BTC_USDT_20260925"``.
        size        : Contract quantity (positive = long, negative = short).
        reduce_only : If True, only reduces an existing position.
        """
        size_int = int(size)
        direction = "long" if size_int > 0 else "short"

        if self.dry_run:
            logger.info(
                "[DRY RUN] place_order",
                extra={
                    "symbol": symbol,
                    "size": size_int,
                    "direction": direction,
                    "reduce_only": reduce_only,
                },
            )
            return

        try:
            order = gate_api.FuturesOrder(
                contract=symbol,
                size=size_int,
                price="0",    # 0 = market order
                tif="ioc",    # Immediate-or-cancel
                reduce_only=reduce_only,
            )
            result = self._api.create_futures_order(settle=SETTLE, futures_order=order)
            logger.info(
                "Order placed",
                extra={
                    "symbol": symbol,
                    "order_id": result.id,
                    "size": size_int,
                    "direction": direction,
                },
            )
        except ApiException as exc:
            logger.error("place_order failed", extra={"symbol": symbol, "error": str(exc)})

    def close_position(self, symbol: str) -> None:
        """Close any open position for *symbol* with a reduce-only market order."""
        position = self.get_position(symbol)
        current_size = position["size"]

        if current_size == 0.0:
            logger.info("No open position to close", extra={"symbol": symbol})
            return

        close_size = -current_size
        logger.info(
            "Closing position",
            extra={"symbol": symbol, "current_size": current_size, "close_size": close_size},
        )
        self.place_order(symbol, close_size, reduce_only=True)
