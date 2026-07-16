"""
Conversation engine — the core of the platform.

Given a tenant, a channel, and an external user id, this module:
  1. Finds or creates the right conversation thread (memory).
  2. Builds a Claude API call using the tenant's own system prompt
     plus the conversation history.
  3. Asks Claude to reply AND self-assess whether a human should take over.
  4. Persists both sides of the exchange.

Returns a plain dict so callers (Telegram bot, webhook, CLI, dashboard)
don't need to know anything about the database.
"""

import json
import os

from . import db

RESPONSE_INSTRUCTIONS = """
You are the AI receptionist for this business. Respond to the customer's
latest message, using the conversation history for context. Always reply
in the same language the customer is writing in.

After crafting your reply, assess your own confidence in handling this
without human help. Escalate when: the customer is angry or frustrated,
asks something outside what you know about this business, requests a
refund/complaint, or you are not confident your answer is correct.

Respond with ONLY a JSON object, no markdown, no extra text:
{
  "reply": "<your reply to the customer, in their language>",
  "should_escalate": true | false,
  "escalation_reason": "<short reason, or empty string if not escalating>"
}
"""


def _mock_response(user_message: str) -> dict:
    lowered = user_message.lower()
    angry_words = ["ужас", "верните деньги", "разочарован", "жалоба", "refund", "terrible", "angry"]
    if any(w in lowered for w in angry_words):
        return {
            "reply": "Понимаю ваше недовольство, подключаю коллегу, который поможет решить вопрос лично.",
            "should_escalate": True,
            "escalation_reason": "[MOCK] Customer appears frustrated / requesting refund.",
        }
    return {
        "reply": "[MOCK] Спасибо за сообщение! Уточните, пожалуйста, какой у вас вопрос — помогу разобраться.",
        "should_escalate": False,
        "escalation_reason": "",
    }


def _call_claude(system_prompt: str, history: list[dict]) -> dict:
    from anthropic import Anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Export it before running with real API calls:\n"
            "  export ANTHROPIC_API_KEY='sk-ant-...'"
        )

    client = Anthropic(api_key=api_key)

    full_system = system_prompt.strip() + "\n\n" + RESPONSE_INSTRUCTIONS

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system=full_system,
        messages=history,
    )

    raw_text = response.content[0].text.strip()
    return json.loads(raw_text)


def handle_message(
    tenant_id: str,
    channel: str,
    external_user_id: str,
    user_message: str,
    mock: bool = False,
) -> dict:
    """
    Process one incoming message end to end.

    Returns:
        {
          "conversation_id": str,
          "reply": str,
          "should_escalate": bool,
          "escalation_reason": str,
        }
    """
    tenant = db.get_tenant(tenant_id)
    if tenant is None:
        raise ValueError(f"No tenant found with id={tenant_id!r}")

    conversation_id = db.get_or_create_conversation(tenant_id, channel, external_user_id)
    db.add_message(conversation_id, "user", user_message)

    history_rows = db.get_history(conversation_id, limit=20)
    history = [{"role": r["role"], "content": r["content"]} for r in history_rows if r["role"] in ("user", "assistant")]

    result = _mock_response(user_message) if mock else _call_claude(tenant["system_prompt"], history)

    db.add_message(conversation_id, "assistant", result["reply"])

    new_status = "escalated" if result["should_escalate"] else "active"
    db.touch_conversation(conversation_id, status=new_status)

    return {
        "conversation_id": conversation_id,
        "reply": result["reply"],
        "should_escalate": result["should_escalate"],
        "escalation_reason": result.get("escalation_reason", ""),
    }
