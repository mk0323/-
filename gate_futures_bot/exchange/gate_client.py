"""
Gate.io API wrapper for USDT-margined delivery futures.

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

    def get_contract_multiplier(self, symbol: str) -> float:
        """
        Return the quanto multiplier for *symbol* (size of 1 contract in coin units).
        e.g. BTC_USDT perpetual = 0.0001 BTC per contract. Returns 1.0 on error.
        """
        try:
            contract = self._api.get_futures_contract(settle=SETTLE, contract=symbol)
            mult = float(contract.quanto_multiplier)
            return mult if mult > 0 else 1.0
        except ApiException as exc:
            logger.error("get_contract_multiplier failed", extra={"symbol": symbol, "error": str(exc)})
            return 1.0

    def get_funding_rate(self, symbol: str) -> float:
        """Return the latest funding rate for *symbol*. Returns 0.0 on error."""
        try:
            rates = self._api.list_futures_funding_rate_history(
                settle=SETTLE,
                contract=symbol,
                limit=1,
            )
            if rates:
                return float(rates[0].r)
            return 0.0
        except ApiException as exc:
            logger.error("get_funding_rate failed", extra={"symbol": symbol, "error": str(exc)})
            return 0.0

    def get_balance(self) -> float:
        """Return the available USDT balance in the delivery futures account."""
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

    def _place_trigger_order(
        self, symbol: str, trigger_price: float, contracts: int,
        position_dir: int, rule: int, label: str,
    ) -> None:
        """
        Internal: register a reduce-only price-triggered market order.

        position_dir : 1 (long) or -1 (short) — the position being protected.
        rule         : 1 = trigger when price >= trigger_price, 2 = when price <= trigger_price.
        """
        if self.dry_run:
            logger.info(
                f"[DRY RUN] {label} skipped",
                extra={"symbol": symbol, "trigger_price": trigger_price, "contracts": contracts},
            )
            return
        try:
            close_size = -abs(contracts) if position_dir == 1 else abs(contracts)
            price_trigger = gate_api.FuturesPriceTrigger(
                strategy_type=0, price_type=0,
                price=str(trigger_price), rule=rule, expiration=86400,
            )
            initial_order = gate_api.FuturesInitialOrder(
                contract=symbol, size=close_size, price="0", tif="ioc", reduce_only=True,
            )
            trigger_order = gate_api.FuturesPriceTriggeredOrder(initial=initial_order, trigger=price_trigger)
            result = self._api.create_price_triggered_order(
                settle=SETTLE, futures_price_triggered_order=trigger_order
            )
            logger.info(f"{label} order placed",
                        extra={"symbol": symbol, "trigger_price": trigger_price, "order_id": result.id})
        except ApiException as exc:
            logger.error(f"{label} failed", extra={"symbol": symbol, "error": str(exc)})

    def set_stop_loss(self, symbol: str, stop_price: float, contracts: int, position_dir: int = 1) -> None:
        """
        Register a stop-loss on the exchange. Survives bot/PC shutdown.
        Long  → trigger when price drops to stop_price (rule 2).
        Short → trigger when price rises to stop_price (rule 1).
        """
        rule = 2 if position_dir == 1 else 1
        self._place_trigger_order(symbol, stop_price, contracts, position_dir, rule, "Stop-loss")

    def set_take_profit(self, symbol: str, tp_price: float, contracts: int, position_dir: int = 1) -> None:
        """
        Register a take-profit on the exchange. Survives bot/PC shutdown.
        Long  → trigger when price rises to tp_price (rule 1).
        Short → trigger when price drops to tp_price (rule 2).
        """
        rule = 1 if position_dir == 1 else 2
        self._place_trigger_order(symbol, tp_price, contracts, position_dir, rule, "Take-profit")

    def cancel_all_stop_orders(self, symbol: str) -> None:
        """Cancel all pending price-triggered (stop) orders for *symbol*."""
        if self.dry_run:
            return
        try:
            self._api.cancel_price_triggered_order_list(settle=SETTLE, contract=symbol)
            logger.info("Cancelled all stop orders", extra={"symbol": symbol})
        except ApiException as exc:
            logger.error("cancel_all_stop_orders failed", extra={"symbol": symbol, "error": str(exc)})
