# AI Receptionist Platform — Session 1: Core Engine

This is the foundation of a multi-tenant AI receptionist platform: multiple
businesses ("tenants"), each with their own system prompt, each getting
persistent conversation memory and human-escalation logic — all through one
shared codebase instead of one script per client.

## What's built so far

- **`core/db.py`** — SQLite schema and data access: tenants, conversations, messages
- **`core/engine.py`** — the actual conversation logic: takes a message, loads
  history for that specific user/tenant, calls Claude with the tenant's own
  system prompt, decides if a human should take over, saves everything
- **`chat_cli.py`** — a terminal chat interface for testing the engine directly,
  without needing Telegram or a web UI yet

## Try it

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY='sk-ant-...'

python chat_cli.py setup                    # creates a demo tenant ("Luna Skincare")
python chat_cli.py chat <tenant_id>          # chat with it for real
python chat_cli.py chat <tenant_id> --mock   # or test without using API credits
```

### What to actually test

Have a multi-turn conversation and use pronouns/references that only make
sense with memory, e.g.:

```
You: do you ship internationally?
Bot: [answers about shipping]
You: how much would that cost roughly?
```

If the second answer correctly refers back to international shipping
(not a generic "could you clarify?"), memory is working.

Also try getting it annoyed on purpose ("this is unacceptable, I want a
refund") — it should flag `should_escalate: true` in the CLI output.

## What's next (Session 2+)

- Telegram bot as a second channel, reusing this same `engine.handle_message()`
- Web dashboard to see conversations and configure tenants without editing code
- Real escalation delivery (Telegram/email notification to the business owner)
- Move from SQLite to Postgres for the Render deployment

## Stack

Python, SQLite, Anthropic Claude API
