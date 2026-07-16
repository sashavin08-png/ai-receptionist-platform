#!/usr/bin/env python3
"""
Interactive CLI for testing the AI receptionist engine locally.

Usage:
    python chat_cli.py setup                 # create a demo tenant, print its id
    python chat_cli.py chat <tenant_id>       # start an interactive chat (real API)
    python chat_cli.py chat <tenant_id> --mock  # same, without calling Claude
"""

import sys

if sys.stdout.encoding is None or sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from core import db, engine

DEMO_SYSTEM_PROMPT = """You are the AI receptionist for "Luna Skincare", a small
online skincare store. You help customers with questions about orders,
shipping times (3-5 business days), returns (14-day return window, item
must be unopened), and product recommendations for the store's Korean
skincare line. You are friendly, concise, and never make up information
about products you don't know about — say you'll check and follow up
instead."""


def setup():
    db.init_db()
    tenant_id = db.create_tenant(name="Luna Skincare", system_prompt=DEMO_SYSTEM_PROMPT)
    print(f"Created demo tenant 'Luna Skincare' with id: {tenant_id}")
    print(f"Run: python chat_cli.py chat {tenant_id}")


def chat(tenant_id: str, mock: bool = False):
    db.init_db()
    tenant = db.get_tenant(tenant_id)
    if tenant is None:
        print(f"No tenant with id {tenant_id}. Run 'python chat_cli.py setup' first.")
        return

    print(f"Chatting as a customer with: {tenant['name']} {'[MOCK MODE]' if mock else ''}")
    print("Type 'exit' to quit.\n")

    external_user_id = "cli-test-user"

    while True:
        try:
            user_message = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if user_message.lower() in ("exit", "quit"):
            break
        if not user_message:
            continue

        result = engine.handle_message(
            tenant_id=tenant_id,
            channel="cli",
            external_user_id=external_user_id,
            user_message=user_message,
            mock=mock,
        )

        print(f"Bot: {result['reply']}")
        if result["should_escalate"]:
            print(f"  [ESCALATION FLAG] {result['escalation_reason']}")
        print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    if command == "setup":
        setup()
    elif command == "chat":
        if len(sys.argv) < 3:
            print("Usage: python chat_cli.py chat <tenant_id> [--mock]")
            sys.exit(1)
        tenant_id = sys.argv[2]
        mock = "--mock" in sys.argv
        chat(tenant_id, mock=mock)
    else:
        print(__doc__)
        sys.exit(1)
