#!/usr/bin/env python3
"""
Telegram channel for the AI Receptionist platform.

This file does NOT contain any conversation logic itself — it just
receives messages from Telegram and forwards them into the same
core.engine.handle_message() used by the CLI. That's the whole point
of building the engine as a separate module: adding a new channel
means writing an adapter, not rewriting the brain.

Setup:
    export TELEGRAM_BOT_TOKEN='123456789:AA...'
    export ANTHROPIC_API_KEY='sk-ant-...'
    export OWNER_TELEGRAM_CHAT_ID='<your own Telegram numeric id>'   # for escalation alerts
    export TENANT_ID='<id printed by chat_cli.py setup>'   # optional, see below
    python telegram_bot.py

If OWNER_TELEGRAM_CHAT_ID is not set, escalations are still detected and
logged to the console, but no alert message is sent anywhere.

If TENANT_ID is not set, the bot uses the first tenant found in the
database (fine for single-tenant testing; Session 3's dashboard will
make tenant routing configurable per Telegram bot).
"""

import logging
import os

from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, ContextTypes, filters

from core import db, engine, notifier, telegram_api

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("telegram_bot")


def resolve_tenant_id() -> str:
    tenant_id = os.environ.get("TENANT_ID")
    if tenant_id:
        return tenant_id

    tenants = db.list_tenants()
    if not tenants:
        raise RuntimeError(
            "No tenants exist yet. Run 'python chat_cli.py setup' first to create one, "
            "or set TENANT_ID to an existing tenant's id."
        )
    return tenants[0]["id"]


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! I'm an AI assistant here to help. Ask me anything about the business."
    )


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tenant_id = context.bot_data["tenant_id"]
    user_message = update.message.text
    telegram_user_id = str(update.effective_user.id)

    logger.info("Message from %s: %s", telegram_user_id, user_message[:80])

    try:
        result = engine.handle_message(
            tenant_id=tenant_id,
            channel="telegram",
            external_user_id=telegram_user_id,
            user_message=user_message,
        )
    except Exception:
        logger.exception("Error handling message")
        await update.message.reply_text(
            "Sorry, something went wrong on my end. Please try again in a moment."
        )
        return

    await update.message.reply_text(
        telegram_api.render_for_telegram(result["reply"]),
        parse_mode="HTML",
    )

    if result["should_escalate"]:
        tenant = db.get_tenant(tenant_id)
        alert_text = notifier.format_escalation_message(
            tenant_id=tenant_id,
            tenant_name=tenant["name"],
            channel="telegram",
            external_user_id=telegram_user_id,
            user_message=user_message,
            reason=result["escalation_reason"],
            conversation_id=result["conversation_id"],
        )
        delivered = notifier.send_owner_alert(alert_text)
        logger.warning(
            "ESCALATION FLAGGED — conversation=%s user=%s reason=%s (owner notified: %s)",
            result["conversation_id"],
            telegram_user_id,
            result["escalation_reason"],
            delivered,
        )


def main():
    db.init_db()

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. Export it before running:\n"
            "  export TELEGRAM_BOT_TOKEN='123456789:AA...'"
        )

    tenant_id = resolve_tenant_id()
    tenant = db.get_tenant(tenant_id)
    if tenant is None:
        raise RuntimeError(f"TENANT_ID={tenant_id!r} does not exist in the database.")

    logger.info("Starting bot for tenant: %s (id=%s)", tenant["name"], tenant_id)

    app = Application.builder().token(token).build()
    app.bot_data["tenant_id"] = tenant_id

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    logger.info("Bot is polling. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
