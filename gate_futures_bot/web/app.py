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
load_dotenv(os.path.join(BOT_DIR, ".env"))

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Global bot process state
# ---------------------------------------------------------------------------
bot_process: subprocess.Popen | None = None
log_buffer: deque = deque(maxlen=200)
bot_params: dict = {}
log_lock = threading.Lock()


def _read_output(proc: subprocess.Popen) -> None:
    """Background thread: continuously read subprocess stdout/stderr into buffer."""
    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            with log_lock:
                log_buffer.append(line)
    except Exception:
        pass


def _get_balance() -> str:
    """Try to fetch USDT balance via Gate.io API; return placeholder on error."""
    try:
        import config as cfg
        if not cfg.GATE_API_KEY or not cfg.GATE_API_SECRET:
            return "N/A (no API key)"
        from gate_api import ApiClient, Configuration, FuturesApi
        configuration = Configuration(
            host="https://api.gateio.ws/api/v4",
            key=cfg.GATE_API_KEY,
            secret=cfg.GATE_API_SECRET,
        )
        client = ApiClient(configuration)
        futures_api = FuturesApi(client)
        account = futures_api.list_futures_accounts("usdt")
        return str(account.total)
    except Exception as e:
        return f"N/A ({e})"


def _get_position(symbol: str = "BTC_USDT") -> str:
    """Try to fetch current position; return placeholder on error."""
    try:
        import config as cfg
        if not cfg.GATE_API_KEY or not cfg.GATE_API_SECRET:
            return "없음"
        from gate_api import ApiClient, Configuration, FuturesApi
        configuration = Configuration(
            host="https://api.gateio.ws/api/v4",
            key=cfg.GATE_API_KEY,
            secret=cfg.GATE_API_SECRET,
        )
        client = ApiClient(configuration)
        futures_api = FuturesApi(client)
        positions = futures_api.get_position("usdt", symbol)
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

    # Try to read leverage from config
    try:
        import config as cfg
        leverage = cfg.LEVERAGE
    except Exception:
        leverage = "N/A"

    return jsonify({
        "running": running,
        "strategy": bot_params.get("strategy", ""),
        "symbol": symbol,
        "interval": bot_params.get("interval", ""),
        "dry_run": bot_params.get("dry_run", True),
        "balance": balance,
        "position": position,
        "leverage": leverage,
        "recent_logs": recent_logs,
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


@app.route("/api/logs")
def api_logs():
    with log_lock:
        lines = list(log_buffer)[-50:]
    return jsonify(lines)
