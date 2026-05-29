"""
Gate.io USDT Perpetual Futures Trading Bot — entry point.

Usage
-----
    python main.py --strategy tsmom   [--symbol BTC_USDT] [--interval 1h]
    python main.py --strategy dual_ma
    python main.py --strategy bbands_rsi
"""

from __future__ import annotations

import argparse
import sys
import time

from dotenv import load_dotenv

import config
from exchange.gate_client import GateClient
from risk.position_sizing import check_drawdown, kelly_size
from strategies.bbands_rsi import BBandsRSIStrategy
from strategies.base import BaseStrategy
from strategies.dual_ma import DualMAStrategy
from strategies.tsmom import TSMOMStrategy
from utils.logger import get_logger

load_dotenv()

logger = get_logger(__name__)

STRATEGIES: dict[str, type[BaseStrategy]] = {
    "tsmom": TSMOMStrategy,
    "dual_ma": DualMAStrategy,
    "bbands_rsi": BBandsRSIStrategy,
}

# Minimum candles needed per strategy to avoid warm-up issues
MIN_CANDLES: dict[str, int] = {
    "tsmom": config.TSMOM_LOOKBACK_DAYS + config.TSMOM_VOL_WINDOW + 10,
    "dual_ma": config.DUAL_MA_SLOW_PERIOD * 3 + 10,
    "bbands_rsi": max(config.BBANDS_RSI_BB_PERIOD, config.BBANDS_RSI_RSI_PERIOD) + 10,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gate.io USDT perpetual futures bot")
    parser.add_argument(
        "--strategy",
        choices=list(STRATEGIES.keys()),
        required=True,
        help="Trading strategy to use",
    )
    parser.add_argument("--symbol", default=config.SYMBOL, help="Contract, e.g. BTC_USDT")
    parser.add_argument("--interval", default="1h", help="Candle interval, e.g. 1h, 4h, 1d")
    return parser.parse_args()


def contracts_from_usdt(size_usdt: float, last_price: float, leverage: int) -> int:
    """Convert a USDT notional size to integer contract count."""
    if last_price <= 0:
        return 0
    notional_per_contract = last_price  # 1 contract = 1 unit of the coin at Gate.io
    contracts = int((size_usdt * leverage) / notional_per_contract)
    return max(contracts, 1)


def run(args: argparse.Namespace) -> None:
    strategy_cls = STRATEGIES[args.strategy]
    strategy = strategy_cls()
    limit = MIN_CANDLES[args.strategy]

    client = GateClient(
        api_key=config.GATE_API_KEY,
        api_secret=config.GATE_API_SECRET,
        dry_run=config.DRY_RUN,
    )

    client.set_leverage(args.symbol, config.LEVERAGE)

    peak_balance: float = client.get_balance()
    current_position: int = 0  # tracked locally; 1=long, -1=short, 0=flat

    logger.info(
        "Bot started",
        extra={
            "strategy": args.strategy,
            "symbol": args.symbol,
            "interval": args.interval,
            "dry_run": config.DRY_RUN,
            "initial_balance": peak_balance,
        },
    )

    while True:
        try:
            # ── 1. Drawdown guard ────────────────────────────────────────
            balance = client.get_balance()
            if balance > peak_balance:
                peak_balance = balance

            if check_drawdown(peak_balance, balance, config.KELLY_MAX_DRAWDOWN_PCT):
                logger.warning("Drawdown limit hit — closing position and sleeping")
                if current_position != 0:
                    client.close_position(args.symbol)
                    current_position = 0
                time.sleep(config.LOOP_INTERVAL_SECONDS)
                continue

            # ── 2. Fetch candles ─────────────────────────────────────────
            df = client.get_candles(args.symbol, interval=args.interval, limit=limit)
            if df.empty:
                logger.warning("Empty candle data; retrying next cycle")
                time.sleep(config.LOOP_INTERVAL_SECONDS)
                continue

            # ── 3. Compute signal ────────────────────────────────────────
            signal = strategy.compute_signal(df)
            last_price = float(df["close"].iloc[-1])

            logger.info(
                "Signal",
                extra={
                    "strategy": args.strategy,
                    "signal": signal,
                    "current_position": current_position,
                    "last_price": last_price,
                },
            )

            # ── 4. Exit logic ────────────────────────────────────────────
            if current_position != 0 and strategy.should_exit(df, current_position):
                logger.info("Exit condition met — closing position")
                client.close_position(args.symbol)
                current_position = 0

            # ── 5. Entry logic ───────────────────────────────────────────
            if signal != 0 and signal != current_position:
                # Close any existing opposite position first
                if current_position != 0:
                    client.close_position(args.symbol)
                    current_position = 0

                # Size using Kelly (conservative defaults when no trade history)
                size_usdt = kelly_size(
                    balance=balance,
                    win_rate=0.55,       # conservative prior
                    avg_win=0.02,
                    avg_loss=0.015,
                    max_pct=config.KELLY_MAX_POSITION_PCT,
                )

                # Apply vol scalar if strategy supports it (TSMOM)
                if hasattr(strategy, "compute_vol_scalar"):
                    scalar = strategy.compute_vol_scalar(df)
                    size_usdt *= scalar

                n_contracts = contracts_from_usdt(size_usdt, last_price, config.LEVERAGE)
                signed_contracts = n_contracts * signal

                logger.info(
                    "Placing order",
                    extra={
                        "size_usdt": size_usdt,
                        "contracts": signed_contracts,
                        "direction": "long" if signal == 1 else "short",
                    },
                )
                client.place_order(args.symbol, signed_contracts)
                current_position = signal

        except KeyboardInterrupt:
            logger.info("Shutdown requested — closing position")
            if current_position != 0:
                client.close_position(args.symbol)
            sys.exit(0)
        except Exception as exc:  # noqa: BLE001
            logger.error("Unexpected error in main loop", extra={"error": str(exc)})

        time.sleep(config.LOOP_INTERVAL_SECONDS)


if __name__ == "__main__":
    run(parse_args())
