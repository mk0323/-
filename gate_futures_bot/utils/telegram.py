"""
Telegram notification helper.

Sends trade/alert messages to a Telegram chat if TELEGRAM_BOT_TOKEN and
TELEGRAM_CHAT_ID are configured. Silently no-ops otherwise, so the bot keeps
running even when notifications aren't set up.
"""

from __future__ import annotations

import urllib.parse
import urllib.request

from utils.logger import get_logger

logger = get_logger(__name__)


def send_telegram(token: str, chat_id: str, message: str) -> bool:
    """Send *message* to Telegram. Returns True on success, False otherwise."""
    if not token or not chat_id:
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
        }).encode()
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as exc:  # noqa: BLE001
        logger.warning("Telegram send failed", extra={"error": str(exc)})
        return False


class Notifier:
    """Thin wrapper that remembers token/chat_id and formats common events."""

    def __init__(self, token: str, chat_id: str, enabled: bool = True) -> None:
        self.token = token
        self.chat_id = chat_id
        self.enabled = enabled and bool(token) and bool(chat_id)

    def _send(self, msg: str) -> None:
        if self.enabled:
            send_telegram(self.token, self.chat_id, msg)

    def entry(self, symbol: str, direction: str, price: float, contracts: int, notional: float) -> None:
        emoji = "🟢📈" if direction == "long" else "🔴📉"
        self._send(
            f"{emoji} <b>진입 ({direction.upper()})</b>\n"
            f"심볼: {symbol}\n진입가: ${price:,.2f}\n"
            f"수량: {contracts} 계약\n주문금액: ${notional:,.2f}"
        )

    def exit(self, symbol: str, reason: str, price: float, pnl: float | None = None) -> None:
        pnl_str = f"\n손익: {pnl:+.4f} USDT" if pnl is not None else ""
        self._send(f"⚪ <b>청산</b> ({reason})\n심볼: {symbol}\n가격: ${price:,.2f}{pnl_str}")

    def kill_switch(self, symbol: str, loss_pct: float) -> None:
        self._send(
            f"🛑 <b>일일 손실 한도 도달 — 거래 중단</b>\n"
            f"심볼: {symbol}\n손실: -{loss_pct:.2f}%"
        )

    def error(self, symbol: str, message: str) -> None:
        self._send(f"⚠️ <b>에러</b>\n심볼: {symbol}\n{message}")
