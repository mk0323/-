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
import os
import sys
import time
import warnings

# Quiet the noisy "InsecureRequestWarning" so the web log box stays readable.
warnings.filterwarnings("ignore")
try:
    import urllib3
    urllib3.disable_warnings()
except Exception:
    pass

from dotenv import load_dotenv

# Load .env from cwd and from the project root (one level up), so the bot works
# whether launched from the repo root or from inside gate_futures_bot/.
load_dotenv()
_HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_HERE, ".env"))
load_dotenv(os.path.join(os.path.dirname(_HERE), ".env"))

import config
from exchange.gate_client import GateClient
from risk.position_sizing import check_drawdown, kelly_size
from strategies.bbands_rsi import BBandsRSIStrategy
from strategies.base import BaseStrategy
from strategies.dca_momentum import DCAMomentumStrategy
from strategies.dual_ma import DualMAStrategy
from strategies.ema_ribbon import EMARibbonStrategy
from strategies.ichimoku import IchimokuStrategy
from strategies.rsi_divergence import RSIDivergenceStrategy
from strategies.supertrend import SupertrendStrategy
from strategies.tsmom import TSMOMStrategy
from strategies.vol_breakout import VolBreakoutStrategy
from strategies.vwap_reversion import VWAPReversionStrategy
from utils.logger import get_logger

# Honor settings passed from the web dashboard (env vars override config defaults).
_dry_run_env = os.getenv("DRY_RUN")
if _dry_run_env is not None:
    config.DRY_RUN = _dry_run_env.strip().lower() in ("1", "true", "yes")

if os.getenv("LEVERAGE"):
    try:
        config.LEVERAGE = int(float(os.getenv("LEVERAGE")))
    except ValueError:
        pass

if os.getenv("CAPITAL_MODE"):
    config.CAPITAL_MODE = os.getenv("CAPITAL_MODE")
if os.getenv("CAPITAL_PERCENT"):
    try:
        config.CAPITAL_PERCENT = float(os.getenv("CAPITAL_PERCENT"))
    except ValueError:
        pass
if os.getenv("CAPITAL_FIXED"):
    try:
        config.CAPITAL_FIXED = float(os.getenv("CAPITAL_FIXED"))
    except ValueError:
        pass

logger = get_logger(__name__)

STRATEGIES: dict[str, type[BaseStrategy]] = {
    "tsmom": TSMOMStrategy,
    "dual_ma": DualMAStrategy,
    "bbands_rsi": BBandsRSIStrategy,
    "vol_breakout": VolBreakoutStrategy,
    "rsi_divergence": RSIDivergenceStrategy,
    "supertrend": SupertrendStrategy,
    "ema_ribbon": EMARibbonStrategy,
    "vwap_reversion": VWAPReversionStrategy,
    "ichimoku": IchimokuStrategy,
    "dca_momentum": DCAMomentumStrategy,
}

# Accept the names the web dashboard sends as well as the canonical keys.
STRATEGY_ALIASES: dict[str, str] = {
    "tsmom": "tsmom",
    "dualma": "dual_ma",
    "dual_ma": "dual_ma",
    "bbandsrsi": "bbands_rsi",
    "bbands_rsi": "bbands_rsi",
    "vol_breakout": "vol_breakout",
    "volbreakout": "vol_breakout",
    "rsi_divergence": "rsi_divergence",
    "rsidivergence": "rsi_divergence",
    "supertrend": "supertrend",
    "ema_ribbon": "ema_ribbon",
    "emaribbon": "ema_ribbon",
    "vwap_reversion": "vwap_reversion",
    "vwapreversion": "vwap_reversion",
    "ichimoku": "ichimoku",
    "dca_momentum": "dca_momentum",
    "dcamomentum": "dca_momentum",
    "dca": "dca_momentum",
}

# Minimum candles needed per strategy to avoid warm-up issues
MIN_CANDLES: dict[str, int] = {
    "tsmom": config.TSMOM_LOOKBACK_DAYS + config.TSMOM_VOL_WINDOW + 10,
    "dual_ma": config.DUAL_MA_SLOW_PERIOD * 3 + 10,
    "bbands_rsi": max(config.BBANDS_RSI_BB_PERIOD, config.BBANDS_RSI_RSI_PERIOD) + 10,
    "vol_breakout": config.VOL_BREAKOUT_ATR_PERIOD + 30,
    "rsi_divergence": 50,
    "supertrend": 30,
    "ema_ribbon": 100,
    "vwap_reversion": 30,
    "ichimoku": 100,
    "dca_momentum": 70,
}


def _normalize_strategy(name: str) -> str:
    key = STRATEGY_ALIASES.get(name.strip().lower())
    if key is None:
        raise SystemExit(
            f"Unknown strategy '{name}'. Choose one of: {', '.join(STRATEGIES.keys())}"
        )
    return key


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gate.io USDT perpetual futures bot")
    parser.add_argument(
        "--strategy",
        required=True,
        help="Trading strategy: tsmom | dual_ma | bbands_rsi | vol_breakout",
    )
    parser.add_argument("--symbol", default=config.SYMBOL, help="Contract, e.g. BTC_USDT")
    parser.add_argument("--interval", default="1h", help="Candle interval, e.g. 1h, 4h, 1d")
    args = parser.parse_args()
    args.strategy = _normalize_strategy(args.strategy)
    return args


def get_capital(balance: float) -> float:
    """Return the capital to use for position sizing based on config settings."""
    if config.CAPITAL_MODE == "fixed":
        return min(config.CAPITAL_FIXED, balance)
    # default: "percent"
    return balance * config.CAPITAL_PERCENT / 100.0


def contracts_from_usdt(
    size_usdt: float, last_price: float, leverage: int, multiplier: float = 1.0
) -> int:
    """
    Convert a USDT margin amount to an integer contract count.

    On Gate.io, 1 contract = ``multiplier`` units of the coin (e.g. BTC_USDT
    perpetual = 0.0001 BTC), so the USDT value of one contract is
    ``last_price * multiplier``. Target notional = margin * leverage.
    """
    if last_price <= 0 or multiplier <= 0:
        return 0
    notional_per_contract = last_price * multiplier
    target_notional = size_usdt * leverage
    contracts = int(target_notional / notional_per_contract)
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

    # Startup diagnostics — surfaced in the web log box.
    if not config.GATE_API_KEY or not config.GATE_API_SECRET:
        logger.error("API key/secret missing. Check your .env (GATE_API_KEY / GATE_API_SECRET).")
    else:
        logger.info("API key detected", extra={"key_prefix": config.GATE_API_KEY[:6]})

    client.set_leverage(args.symbol, config.LEVERAGE)

    # Contract spec — how many coin units one contract represents.
    multiplier = client.get_contract_multiplier(args.symbol)
    logger.info("Contract multiplier", extra={"symbol": args.symbol, "multiplier": multiplier})

    peak_balance = client.get_balance()
    if peak_balance != peak_balance:  # NaN check
        logger.error(
            "Could not fetch balance from Gate.io. "
            "Check API permissions (Perpetual Futures) and IP allowlist."
        )
        peak_balance = 0.0
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
            if balance != balance:  # NaN — API failure this cycle
                logger.warning("Balance fetch failed this cycle; retrying.")
                time.sleep(config.LOOP_INTERVAL_SECONDS)
                continue
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

                # ── 포지션 사이징 ────────────────────────────────────────
                # capital = 사용자가 설정한 마진 금액 (고정 USDT 또는 잔고 %)
                # 고정 금액 모드: 500 USDT를 그대로 마진으로 사용 (Kelly로 재축소 안 함)
                # 비율 모드: Kelly로 적절한 비중 산출 (잔고의 최대 KELLY_MAX_POSITION_PCT)
                capital = get_capital(balance)

                if config.CAPITAL_MODE == "fixed":
                    # 사용자가 직접 지정한 금액 = 마진 그대로 사용
                    size_usdt = capital
                else:
                    # 비율 모드: Kelly로 포지션 크기 계산
                    size_usdt = kelly_size(
                        balance=capital,
                        win_rate=0.55,
                        avg_win=0.02,
                        avg_loss=0.015,
                        max_pct=config.KELLY_MAX_POSITION_PCT,
                    )

                # 안전장치: 잔고 대비 최대 비율 초과 방지
                max_allowed = balance * config.KELLY_MAX_POSITION_PCT * 5  # 최대 100%
                size_usdt = min(size_usdt, max_allowed)

                # Apply vol scalar if strategy supports it (TSMOM)
                if hasattr(strategy, "compute_vol_scalar"):
                    scalar = strategy.compute_vol_scalar(df)
                    size_usdt *= scalar

                n_contracts = contracts_from_usdt(
                    size_usdt, last_price, config.LEVERAGE, multiplier
                )
                signed_contracts = n_contracts * signal

                logger.info(
                    "Placing order",
                    extra={
                        "size_usdt": size_usdt,
                        "notional_usdt": size_usdt * config.LEVERAGE,
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
