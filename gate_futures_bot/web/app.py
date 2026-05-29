"""
Flask web dashboard for Gate.io futures trading bot.
"""

import os
import sys
import subprocess
import threading
from collections import deque
from flask import Flask, jsonify, render_template, request

# Ensure gate_futures_bot/ is on sys.path for config imports
BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

from dotenv import load_dotenv
# Try .env in BOT_DIR and one level up
load_dotenv(os.path.join(BOT_DIR, ".env"))
load_dotenv(os.path.join(os.path.dirname(BOT_DIR), ".env"))

app = Flask(__name__)

@app.after_request
def add_csp(response):
    response.headers["Content-Security-Policy"] = (
        "default-src 'self' 'unsafe-inline' 'unsafe-eval' https://unpkg.com https://cdn.jsdelivr.net; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://unpkg.com https://cdn.jsdelivr.net; "
        "img-src * data:; connect-src *;"
    )
    return response

# ---------------------------------------------------------------------------
# Global bot process state
# ---------------------------------------------------------------------------
bot_process: subprocess.Popen | None = None
log_buffer: deque = deque(maxlen=200)
bot_params: dict = {}
log_lock = threading.Lock()

# Runtime capital allocation overrides (not persisted to file)
capital_config: dict = {}


def _read_output(proc: subprocess.Popen) -> None:
    """Background thread: continuously read subprocess stdout/stderr into buffer."""
    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            with log_lock:
                log_buffer.append(line)
    except Exception:
        pass


def _make_futures_api():
    import config as cfg
    from gate_api import ApiClient, Configuration, FuturesApi
    configuration = Configuration(key=cfg.GATE_API_KEY, secret=cfg.GATE_API_SECRET)
    configuration.verify_ssl = False
    return FuturesApi(ApiClient(configuration)), cfg


def _get_balance() -> float | None:
    """Try to fetch USDT balance via Gate.io API; return None on error."""
    try:
        futures_api, cfg = _make_futures_api()
        if not cfg.GATE_API_KEY or not cfg.GATE_API_SECRET:
            return None
        account = futures_api.list_futures_accounts("usdt")
        return float(account.available)
    except Exception:
        return None


def _get_position(symbol: str = "BTC_USDT") -> str:
    """Try to fetch current position; return placeholder on error."""
    try:
        futures_api, cfg = _make_futures_api()
        if not cfg.GATE_API_KEY or not cfg.GATE_API_SECRET:
            return "없음"
        try:
            positions = futures_api.get_position("usdt", symbol)
        except Exception as inner:
            # 404 = no position exists
            err_str = str(inner)
            if "404" in err_str or "POSITION_NOT_FOUND" in err_str or "not found" in err_str.lower():
                return "없음"
            raise
        size = float(positions.size)
        if size > 0:
            return "Long"
        elif size < 0:
            return "Short"
        return "없음"
    except Exception:
        return "없음"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    global bot_process, bot_params
    running = bot_process is not None and bot_process.poll() is None
    with log_lock:
        recent_logs = list(log_buffer)[-50:]

    symbol = bot_params.get("symbol", "BTC_USDT")
    balance = _get_balance()
    position = _get_position(symbol)

    # Try to read leverage and capital config
    try:
        import config as cfg
        leverage = cfg.LEVERAGE
        capital_mode = capital_config.get("mode", cfg.CAPITAL_MODE)
        capital_percent = capital_config.get("percent", cfg.CAPITAL_PERCENT)
        capital_fixed = capital_config.get("fixed", cfg.CAPITAL_FIXED)
    except Exception:
        leverage = "N/A"
        capital_mode = capital_config.get("mode", "percent")
        capital_percent = capital_config.get("percent", 50.0)
        capital_fixed = capital_config.get("fixed", 500.0)

    return jsonify({
        "running": running,
        "strategy": bot_params.get("strategy", ""),
        "symbol": symbol,
        "interval": bot_params.get("interval", ""),
        "dry_run": bot_params.get("dry_run", True),
        "balance": balance,  # raw float or null — formatted in JS
        "position": position,
        "leverage": leverage,
        "recent_logs": recent_logs,
        "capital_mode": capital_mode,
        "capital_percent": capital_percent,
        "capital_fixed": capital_fixed,
    })


@app.route("/api/start", methods=["POST"])
def api_start():
    global bot_process, log_buffer, bot_params
    if bot_process is not None and bot_process.poll() is None:
        return jsonify({"ok": False, "error": "Bot is already running"}), 400

    data = request.get_json(force=True, silent=True) or {}
    strategy = data.get("strategy", "TSMOM")
    symbol = data.get("symbol", "BTC_USDT")
    interval = data.get("interval", "1h")
    dry_run = data.get("dry_run", True)

    bot_params = {
        "strategy": strategy,
        "symbol": symbol,
        "interval": interval,
        "dry_run": dry_run,
    }

    with log_lock:
        log_buffer.clear()
        log_buffer.append(f"[WEB] Starting bot: strategy={strategy}, symbol={symbol}, interval={interval}, dry_run={dry_run}")

    env = os.environ.copy()
    env["DRY_RUN"] = "true" if dry_run else "false"

    try:
        bot_process = subprocess.Popen(
            [
                sys.executable, "main.py",
                "--strategy", strategy,
                "--symbol", symbol,
                "--interval", interval,
            ],
            cwd=BOT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        t = threading.Thread(target=_read_output, args=(bot_process,), daemon=True)
        t.start()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/stop", methods=["POST"])
def api_stop():
    global bot_process
    if bot_process is None or bot_process.poll() is not None:
        return jsonify({"ok": False, "error": "Bot is not running"}), 400
    try:
        bot_process.terminate()
        bot_process.wait(timeout=10)
    except Exception:
        bot_process.kill()
    with log_lock:
        log_buffer.append("[WEB] Bot stopped.")
    return jsonify({"ok": True})


@app.route("/api/set_capital", methods=["POST"])
def api_set_capital():
    global capital_config
    data = request.get_json(force=True, silent=True) or {}
    mode = data.get("mode", "percent")
    value = data.get("value", 50.0)
    if mode not in ("percent", "fixed"):
        return jsonify({"ok": False, "error": "mode must be 'percent' or 'fixed'"}), 400
    try:
        value = float(value)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "value must be a number"}), 400

    if mode == "percent":
        capital_config["mode"] = "percent"
        capital_config["percent"] = value
    else:
        capital_config["mode"] = "fixed"
        capital_config["fixed"] = value
    return jsonify({"ok": True, "capital_config": capital_config})


@app.route("/api/backtest", methods=["POST"])
def api_backtest():
    data = request.get_json(force=True, silent=True) or {}
    symbol = data.get("symbol", "BTC_USDT")
    interval = data.get("interval", "5m")
    limit = int(data.get("limit", 500))

    try:
        import config as cfg
        from exchange.gate_client import GateClient
        from backtest.engine import run_backtest
        from strategies.tsmom import TSMOMStrategy
        from strategies.dual_ma import DualMAStrategy
        from strategies.bbands_rsi import BBandsRSIStrategy
        from strategies.vol_breakout import VolBreakoutStrategy

        client = GateClient(
            api_key=cfg.GATE_API_KEY,
            api_secret=cfg.GATE_API_SECRET,
            dry_run=True,
        )
        df = client.get_candles(symbol, interval=interval, limit=limit)
        if df.empty:
            return jsonify({"ok": False, "error": "No candle data returned"}), 500

        strategies = {
            "tsmom": TSMOMStrategy(),
            "dual_ma": DualMAStrategy(),
            "bbands_rsi": BBandsRSIStrategy(),
            "vol_breakout": VolBreakoutStrategy(),
        }

        results = {}
        for name, strategy in strategies.items():
            metrics = run_backtest(
                strategy=strategy,
                df=df,
                initial_capital=1000.0,
                leverage=cfg.LEVERAGE,
            )
            results[name] = {
                "total_return_pct": metrics["total_return_pct"],
                "win_rate": metrics["win_rate"],
                "sharpe_ratio": metrics["sharpe_ratio"],
                "max_drawdown_pct": metrics["max_drawdown_pct"],
                "num_trades": metrics["num_trades"],
            }

        # Recommend strategy with highest Sharpe ratio
        best = max(results, key=lambda k: results[k]["sharpe_ratio"])
        results["recommended"] = best
        return jsonify(results)

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/logs")
def api_logs():
    with log_lock:
        lines = list(log_buffer)[-50:]
    return jsonify(lines)


@app.route("/api/candles")
def api_candles():
    symbol = request.args.get("symbol", "BTC_USDT")
    interval = request.args.get("interval", "5m")
    limit = int(request.args.get("limit", 200))
    try:
        import config as cfg
        from exchange.gate_client import GateClient
        client = GateClient(
            api_key=cfg.GATE_API_KEY,
            api_secret=cfg.GATE_API_SECRET,
            dry_run=True,
        )
        df = client.get_candles(symbol, interval=interval, limit=limit)
        if df.empty:
            return jsonify([])
        records = []
        for _, row in df.iterrows():
            ts = row["time"]
            if hasattr(ts, "timestamp"):
                unix_ts = int(ts.timestamp())
            else:
                unix_ts = int(ts)
            records.append({
                "time": unix_ts,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            })
        return jsonify(records)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
