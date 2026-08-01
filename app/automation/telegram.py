from __future__ import annotations

import json
from dataclasses import dataclass
from urllib import parse, request

from app import config


@dataclass(frozen=True)
class TelegramSendResult:
    enabled: bool
    sent: bool
    message: str


def send_telegram_message(text: str) -> TelegramSendResult:
    if not config.TELEGRAM_ENABLED:
        return TelegramSendResult(False, False, "Telegram notifications are disabled.")
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return TelegramSendResult(True, False, "Telegram bot token or chat id is missing.")

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = parse.urlencode(
        {
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": text,
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    req = request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with request.urlopen(req, timeout=20) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not body.get("ok"):
        return TelegramSendResult(True, False, f"Telegram API returned ok=false: {body}")
    return TelegramSendResult(True, True, "Telegram notification sent.")
