"""
Trading configuration for the Gate.io USDT perpetual futures bot.
All sensitive values are loaded from environment variables.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- API Credentials ---
GATE_API_KEY: str = os.getenv("GATE_API_KEY", "")
GATE_API_SECRET: str = os.getenv("GATE_API_SECRET", "")

# --- Trading Pair & Leverage ---
SYMBOL: str = "BTC_USDT"
LEVERAGE: int = 3
DRY_RUN: bool = True  # Paper trading by default — set to False for live trading

# --- Time-Series Momentum (Moskowitz, Ooi, Pedersen 2012) ---
TSMOM_LOOKBACK_DAYS: int = 252   # 12-month lookback for signal
TSMOM_VOL_WINDOW: int = 20       # Rolling window (days) for realized volatility
TSMOM_VOL_TARGET: float = 0.15   # Annualised volatility target (15 %)

# --- Dual EMA Crossover (Faber 2007) ---
DUAL_MA_FAST_PERIOD: int = 20
DUAL_MA_SLOW_PERIOD: int = 60

# --- Bollinger Bands + RSI (mean-reversion) ---
BBANDS_RSI_BB_PERIOD: int = 20
BBANDS_RSI_BB_STD: float = 2.0
BBANDS_RSI_RSI_PERIOD: int = 14
BBANDS_RSI_RSI_OVERSOLD: int = 35
BBANDS_RSI_RSI_OVERBOUGHT: int = 65

# --- Kelly / Risk Management ---
KELLY_MAX_POSITION_PCT: float = 0.20   # Maximum position as fraction of balance
KELLY_MAX_DRAWDOWN_PCT: float = 0.15   # Halt trading if drawdown exceeds 15 %

# --- Bot Loop ---
LOOP_INTERVAL_SECONDS: int = 3600  # Re-evaluate every hour
