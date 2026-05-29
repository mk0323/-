"""
Flask web dashboard for Gate.io futures trading bot.
Supports running multiple bots simultaneously, one per symbol.
"""

import os
import sys
import subprocess
import threading
from collections import deque
from flask import Flask, jsonify, render_template, request

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

from dotenv import load_dotenv
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
# Multi-bot state
# Each key is a bot_id = "<symbol>_<strategy>" (e.g. "BTC_USDT_vol_breakout")
# ---------------------------------------------------------------------------
bots: dict[str, dict] = {}   # bot_id → {process, params, log_buffer, lock}
bots_lock = threading.Lock()

capital_config: dict = {}


def _make_bot_id(symbol: str, strategy: str) -> str:
    return f"{symbol}__{strategy}"


def _read_output(bot_id: str, proc: subprocess.Popen) -> None:
    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            with bots_lock:
                if bot_id in bots:
                    bots[bot_id]["log_buffer"].append(line)
    except Exception:
        pass


def _make_futures_api():
    import config as cfg
    from gate_api import ApiClient, Configuration, FuturesApi
    configuration = Configuration(key=cfg.GATE_API_KEY, secret=cfg.GATE_API_SECRET)
    configuration.verify_ssl = False
    return FuturesApi(ApiClient(configuration)), cfg


def _get_balance() -> float | None:
    try:
        futures_api, cfg = _make_futures_api()
        if not cfg.GATE_API_KEY or not cfg.GATE_API_SECRET:
            return None
        account = futures_api.list_futures_accounts("usdt")
        return float(account.available)
    except Exception:
        return None


def _get_position(symbol: str) -> str:
    try:
        futures_api, cfg = _make_futures_api()
        if not cfg.GATE_API_KEY or not cfg.GATE_API_SECRET:
            return "없음"
        try:
            positions = futures_api.get_position("usdt", symbol)
        except Exception as inner:
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


def _launch_bot(bot_id: str, params: dict) -> subprocess.Popen:
    env = os.environ.copy()
    env["DRY_RUN"] = "true" if params["dry_run"] else "false"
    env["PYTHONUNBUFFERED"] = "1"
    env["LEVERAGE"] = str(params["leverage"])
    env["CAPITAL_MODE"] = params["capital_mode"]
    if params["capital_mode"] == "fixed":
        env["CAPITAL_FIXED"] = str(params["capital_value"])
    else:
        env["CAPITAL_PERCENT"] = str(params["capital_value"])

    proc = subprocess.Popen(
        [sys.executable, "-u", "main.py",
         "--strategy", params["strategy"],
         "--symbol",   params["symbol"],
         "--interval", params["interval"]],
        cwd=BOT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    t = threading.Thread(target=_read_output, args=(bot_id, proc), daemon=True)
    t.start()
    return proc


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    balance = _get_balance()

    try:
        import config as cfg
        capital_mode    = capital_config.get("mode", cfg.CAPITAL_MODE)
        capital_percent = capital_config.get("percent", cfg.CAPITAL_PERCENT)
        capital_fixed   = capital_config.get("fixed", cfg.CAPITAL_FIXED)
    except Exception:
        capital_mode    = capital_config.get("mode", "percent")
        capital_percent = capital_config.get("percent", 50.0)
        capital_fixed   = capital_config.get("fixed", 500.0)

    bots_status = []
    with bots_lock:
        for bot_id, info in list(bots.items()):
            running = info["process"].poll() is None
            recent_logs = list(info["log_buffer"])[-30:]
            bots_status.append({
                "bot_id":   bot_id,
                "running":  running,
                "symbol":   info["params"]["symbol"],
                "strategy": info["params"]["strategy"],
                "interval": info["params"]["interval"],
                "dry_run":  info["params"]["dry_run"],
                "leverage": info["params"]["leverage"],
                "recent_logs": recent_logs,
            })

    return jsonify({
        "balance": balance,
        "bots": bots_status,
        "capital_mode":    capital_mode,
        "capital_percent": capital_percent,
        "capital_fixed":   capital_fixed,
    })


@app.route("/api/start", methods=["POST"])
def api_start():
    data = request.get_json(force=True, silent=True) or {}
    strategy     = data.get("strategy", "TSMOM")
    symbols_raw  = data.get("symbols", data.get("symbol", "BTC_USDT"))
    interval     = data.get("interval", "1h")
    dry_run      = data.get("dry_run", True)
    leverage     = int(data.get("leverage", 10) or 10)
    capital_mode = data.get("capital_mode", "percent")
    capital_value = float(data.get("capital_value", 0) or 0)

    # Accept comma-separated symbols or a list
    if isinstance(symbols_raw, list):
        symbols = [s.strip() for s in symbols_raw if s.strip()]
    else:
        symbols = [s.strip() for s in str(symbols_raw).split(",") if s.strip()]

    started = []
    skipped = []
    errors  = []

    for symbol in symbols:
        bot_id = _make_bot_id(symbol, strategy)
        with bots_lock:
            existing = bots.get(bot_id)
            if existing and existing["process"].poll() is None:
                skipped.append(bot_id)
                continue

        params = {
            "strategy": strategy, "symbol": symbol, "interval": interval,
            "dry_run": dry_run, "leverage": leverage,
            "capital_mode": capital_mode, "capital_value": capital_value,
        }
        try:
            proc = _launch_bot(bot_id, params)
            buf = deque(maxlen=300)
            buf.append(f"[WEB] Started: {symbol} / {strategy} / {interval} / {'DRY' if dry_run else 'LIVE'} / {leverage}x")
            with bots_lock:
                bots[bot_id] = {"process": proc, "params": params, "log_buffer": buf}
            started.append(bot_id)
        except Exception as e:
            errors.append({"bot_id": bot_id, "error": str(e)})

    return jsonify({"ok": True, "started": started, "skipped": skipped, "errors": errors})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    data = request.get_json(force=True, silent=True) or {}
    bot_id = data.get("bot_id")

    with bots_lock:
        if bot_id:
            targets = [bot_id] if bot_id in bots else []
        else:
            targets = list(bots.keys())

    stopped = []
    for bid in targets:
        with bots_lock:
            info = bots.get(bid)
        if not info:
            continue
        try:
            info["process"].terminate()
            info["process"].wait(timeout=10)
        except Exception:
            try: info["process"].kill()
            except Exception: pass
        with bots_lock:
            if bid in bots:
                bots[bid]["log_buffer"].append("[WEB] Bot stopped.")
        stopped.append(bid)

    return jsonify({"ok": True, "stopped": stopped})


@app.route("/api/stop_all", methods=["POST"])
def api_stop_all():
    with bots_lock:
        targets = list(bots.keys())
    stopped = []
    for bid in targets:
        with bots_lock:
            info = bots.get(bid)
        if not info:
            continue
        try:
            info["process"].terminate()
            info["process"].wait(timeout=10)
        except Exception:
            try: info["process"].kill()
            except Exception: pass
        stopped.append(bid)
    return jsonify({"ok": True, "stopped": stopped})


@app.route("/api/set_capital", methods=["POST"])
def api_set_capital():
    global capital_config
    data  = request.get_json(force=True, silent=True) or {}
    mode  = data.get("mode", "percent")
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


@app.route("/api/logs")
def api_logs():
    bot_id = request.args.get("bot_id")
    with bots_lock:
        if bot_id and bot_id in bots:
            lines = list(bots[bot_id]["log_buffer"])[-50:]
        else:
            # Merge all logs if no specific bot requested
            all_lines = []
            for info in bots.values():
                all_lines.extend(info["log_buffer"])
            lines = all_lines[-50:]
    return jsonify(lines)


def _get_strategy_classes():
    from strategies.tsmom import TSMOMStrategy
    from strategies.dual_ma import DualMAStrategy
    from strategies.bbands_rsi import BBandsRSIStrategy
    from strategies.vol_breakout import VolBreakoutStrategy
    from strategies.rsi_divergence import RSIDivergenceStrategy
    from strategies.supertrend import SupertrendStrategy
    from strategies.ema_ribbon import EMARibbonStrategy
    from strategies.vwap_reversion import VWAPReversionStrategy
    from strategies.ichimoku import IchimokuStrategy
    from strategies.dca_momentum import DCAMomentumStrategy
    return {
        "tsmom": TSMOMStrategy, "dual_ma": DualMAStrategy,
        "bbands_rsi": BBandsRSIStrategy, "vol_breakout": VolBreakoutStrategy,
        "rsi_divergence": RSIDivergenceStrategy, "supertrend": SupertrendStrategy,
        "ema_ribbon": EMARibbonStrategy, "vwap_reversion": VWAPReversionStrategy,
        "ichimoku": IchimokuStrategy, "dca_momentum": DCAMomentumStrategy,
    }


@app.route("/api/backtest", methods=["POST"])
def api_backtest():
    data     = request.get_json(force=True, silent=True) or {}
    symbol   = data.get("symbol", "BTC_USDT")
    interval = data.get("interval", "5m")
    limit    = int(data.get("limit", 500))

    try:
        import config as cfg
        from exchange.gate_client import GateClient
        from backtest.engine import run_backtest

        client = GateClient(api_key=cfg.GATE_API_KEY, api_secret=cfg.GATE_API_SECRET, dry_run=True)
        df = client.get_candles(symbol, interval=interval, limit=limit)
        if df.empty:
            return jsonify({"ok": False, "error": "No candle data returned"}), 500

        strategy_classes = _get_strategy_classes()
        results = {}
        for name, cls in strategy_classes.items():
            try:
                metrics = run_backtest(strategy=cls(), df=df, initial_capital=1000.0, leverage=cfg.LEVERAGE)
                results[name] = {
                    "total_return_pct": metrics["total_return_pct"],
                    "win_rate":         metrics["win_rate"],
                    "sharpe_ratio":     metrics["sharpe_ratio"],
                    "max_drawdown_pct": metrics["max_drawdown_pct"],
                    "num_trades":       metrics["num_trades"],
                }
            except Exception:
                pass

        if results:
            best = max(results, key=lambda k: results[k]["sharpe_ratio"])
            results["recommended"] = best
        return jsonify(results)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/recommend")
def api_recommend():
    WATCHLIST = [
        "BTC_USDT", "ETH_USDT", "SOL_USDT", "BNB_USDT", "XRP_USDT",
        "DOGE_USDT", "ADA_USDT", "AVAX_USDT", "LINK_USDT", "DOT_USDT",
        "OP_USDT", "ARB_USDT", "SUI_USDT", "APT_USDT", "INJ_USDT",
    ]
    try:
        import config as cfg
        from exchange.gate_client import GateClient
        client = GateClient(api_key=cfg.GATE_API_KEY, api_secret=cfg.GATE_API_SECRET, dry_run=True)
        scores = []
        for symbol in WATCHLIST:
            try:
                df = client.get_candles(symbol, interval="1h", limit=48)
                if df.empty or len(df) < 24:
                    continue
                close = df["close"].to_numpy(dtype=float)
                high  = df["high"].to_numpy(dtype=float)
                low   = df["low"].to_numpy(dtype=float)

                momentum_24h = (close[-1] - close[-24]) / close[-24] * 100
                tr = [max(high[i] - low[i],
                          abs(high[i] - close[i-1]),
                          abs(low[i]  - close[i-1])) for i in range(1, len(close))]
                atr_pct = float(sum(tr[-14:]) / 14) / close[-1] * 100
                vol = df["volume"].to_numpy(dtype=float)
                vol_ratio = vol[-6:].mean() / (vol[-12:-6].mean() + 1e-10)
                score = abs(momentum_24h) * vol_ratio / (atr_pct + 0.01)
                rec_leverage = max(2, min(10, int(round(1.5 / (atr_pct + 0.01)))))
                scores.append({
                    "symbol": symbol,
                    "momentum_24h": round(momentum_24h, 2),
                    "atr_pct":      round(atr_pct, 3),
                    "vol_ratio":    round(vol_ratio, 2),
                    "score":        round(score, 3),
                    "rec_leverage": rec_leverage,
                    "direction":    "long" if momentum_24h > 0 else "short",
                })
            except Exception:
                continue
        scores.sort(key=lambda x: x["score"], reverse=True)
        return jsonify({"ok": True, "recommendations": scores[:8]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/trades")
def api_trades():
    symbol        = request.args.get("symbol", "BTC_USDT")
    interval      = request.args.get("interval", "5m")
    strategy_name = request.args.get("strategy", "dual_ma")
    limit         = int(request.args.get("limit", 200))
    try:
        import config as cfg
        from exchange.gate_client import GateClient
        from backtest.engine import run_backtest

        strategy_classes = _get_strategy_classes()
        strategy_cls = strategy_classes.get(strategy_name, list(strategy_classes.values())[0])

        client = GateClient(api_key=cfg.GATE_API_KEY, api_secret=cfg.GATE_API_SECRET, dry_run=True)
        df = client.get_candles(symbol, interval=interval, limit=limit)
        if df.empty:
            return jsonify([])

        metrics = run_backtest(strategy=strategy_cls(), df=df, initial_capital=1000.0, leverage=cfg.LEVERAGE)
        trades = metrics.get("trades", [])
        result = []
        for t in trades:
            result.append({
                "time":       t["entry_time"],
                "price":      t["entry_price"],
                "direction":  t["direction"],
                "exit_time":  t.get("exit_time"),
                "exit_price": t.get("exit_price"),
                "pnl_pct":    t.get("pnl_pct"),
            })
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/candles")
def api_candles():
    symbol   = request.args.get("symbol", "BTC_USDT")
    interval = request.args.get("interval", "5m")
    limit    = int(request.args.get("limit", 200))
    try:
        import config as cfg
        from exchange.gate_client import GateClient
        client = GateClient(api_key=cfg.GATE_API_KEY, api_secret=cfg.GATE_API_SECRET, dry_run=True)
        df = client.get_candles(symbol, interval=interval, limit=limit)
        if df.empty:
            return jsonify([])
        records = []
        for _, row in df.iterrows():
            ts = row["time"]
            unix_ts = int(ts.timestamp()) if hasattr(ts, "timestamp") else int(ts)
            records.append({
                "time":  unix_ts,
                "open":  float(row["open"]),
                "high":  float(row["high"]),
                "low":   float(row["low"]),
                "close": float(row["close"]),
            })
        return jsonify(records)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
