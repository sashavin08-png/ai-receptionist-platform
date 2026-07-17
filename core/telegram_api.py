"""
Minimal, dependency-free Telegram Bot API client for sending messages.

Used by the webhook route (dashboard.py) to reply to customers, and could
be reused anywhere else a message needs to go out to Telegram. Deliberately
plain urllib — no async, no python-telegram-bot — so it works inside a
normal synchronous Flask request handler.
"""

import json
import logging
import os
import re
import urllib.parse
import urllib.request

logger = logging.getLogger("telegram_api")


def render_for_telegram(text: str) -> str:
    """
    Claude naturally writes standard markdown (**bold**, `code`). Telegram's
    own "Markdown" parse mode uses single-asterisk bold and doesn't match
    that, so instead we convert to Telegram's HTML parse mode, which is
    simpler to get right: escape HTML special characters first, then turn
    **bold** and `code` into <b> and <code> tags.
    """
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`([^`]+?)`", r"<code>\1</code>", text)
    return text


def send_message(chat_id: str, text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN not set — cannot send message.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": render_for_telegram(text),
            "parse_mode": "HTML",
        }
    ).encode()

    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
            if not body.get("ok"):
                logger.error("Telegram API rejected sendMessage: %s", body)
                return False
            return True
    except Exception:
        logger.exception("Failed to send Telegram message")
        return False
