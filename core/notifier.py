"""
Escalation delivery.

When the engine flags should_escalate=True, someone needs to actually find
out about it. This module sends a Telegram message to the business owner's
own chat, using the same bot token the channel already has.

Deliberately dependency-free (uses urllib, not the python-telegram-bot
library) so this can be called from anywhere — the Telegram channel, the
dashboard, a future email channel — without needing an async bot instance
running.
"""

import json
import logging
import os
import urllib.parse
import urllib.request

logger = logging.getLogger("notifier")


def send_owner_alert(message: str) -> bool:
    """
    Send a plain-text alert to the configured owner chat via Telegram.

    Requires TELEGRAM_BOT_TOKEN and OWNER_TELEGRAM_CHAT_ID to be set.
    Returns True if delivered, False if not configured or delivery failed
    (never raises — a failed notification shouldn't crash the bot that
    triggered it).
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    owner_chat_id = os.environ.get("OWNER_TELEGRAM_CHAT_ID")

    if not token or not owner_chat_id:
        logger.warning(
            "Escalation alert NOT sent (TELEGRAM_BOT_TOKEN or OWNER_TELEGRAM_CHAT_ID "
            "not set). Message was:\n%s",
            message,
        )
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": owner_chat_id, "text": message}).encode()

    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
            if not body.get("ok"):
                logger.error("Telegram API rejected the alert: %s", body)
                return False
            return True
    except Exception:
        logger.exception("Failed to send escalation alert")
        return False


def format_escalation_message(
    tenant_id: str,
    tenant_name: str,
    channel: str,
    external_user_id: str,
    user_message: str,
    reason: str,
    conversation_id: str,
    dashboard_base_url: str | None = None,
) -> str:
    dashboard_base = dashboard_base_url or os.environ.get("DASHBOARD_URL", "http://localhost:5050")
    link = f"{dashboard_base}/tenant/{tenant_id}/conversation/{conversation_id}"

    excerpt = user_message if len(user_message) <= 300 else user_message[:300] + "..."

    return (
        f"🚨 Escalation — {tenant_name}\n\n"
        f"Channel: {channel} (user: {external_user_id})\n"
        f"Reason: {reason}\n\n"
        f'Customer said: "{excerpt}"\n\n'
        f"View full thread: {link}"
    )
