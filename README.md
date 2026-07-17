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

## What's next

- Let the dashboard actually configure which tenant a given Telegram bot
  routes to, instead of the current TENANT_ID env var
- Basic auth on the dashboard (right now anyone with the URL can see all
  conversations — fine for a personal demo, not fine for a real client)

---

## Session 5: Deploying to the cloud

Two pieces now need to run 24/7 instead of just on your laptop:

- **`dashboard.py`** — a normal web service (has a URL people visit)
- **`telegram_bot.py`** — a background worker (polls Telegram forever, no URL)

And the database needs to switch from a local SQLite file (which doesn't
survive a restart on most cloud platforms) to a real Postgres database.
`core/db.py` already supports both — it switches automatically based on
whether a `DATABASE_URL` environment variable is set.

⚠️ Note: the Postgres code path was reviewed carefully but could not be
tested against a real Postgres server in the environment this was built in
— test it for real once it's connected below, the same way earlier
sessions were verified.

### Step 1 — Create a Postgres database on Render

1. On [dashboard.render.com](https://dashboard.render.com), **New +** → **Postgres**
2. Give it a name, choose the **Free** plan, create it
3. Once it's up, copy the **Internal Database URL** (starts with `postgres://`)
   — use the *internal* one if your other services are also on Render, it's
   faster and doesn't count against external bandwidth

### Step 2 — Deploy the dashboard as a Web Service

1. Push this project to GitHub first (same flow as the lead qualifier:
   `git remote add origin ...`, `git push -u origin main`)
2. On Render: **New +** → **Web Service** → connect this repo
3. Settings:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn dashboard:app --bind 0.0.0.0:$PORT`
4. Environment variables:
   - `DATABASE_URL` = the Postgres URL from Step 1
5. Deploy. Note the public URL Render gives you (e.g.
   `https://ai-receptionist-xxxx.onrender.com`) — you'll need it in Step 3.

### Step 3 — Deploy the Telegram bot as a Background Worker

1. Same repo, **New +** → **Background Worker**
2. Settings:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python telegram_bot.py`
3. Environment variables:
   - `DATABASE_URL` = same Postgres URL as Step 2
   - `TELEGRAM_BOT_TOKEN` = your bot token
   - `ANTHROPIC_API_KEY` = your Claude API key
   - `OWNER_TELEGRAM_CHAT_ID` = your numeric Telegram id
   - `DASHBOARD_URL` = the public dashboard URL from Step 2 (this is the
     "look nicer" fix — escalation alerts will now link to the real
     dashboard instead of `localhost`)
4. Deploy.

### What to test

- Create a tenant via the *deployed* dashboard URL (not localhost)
- Message the *deployed* bot on Telegram
- Confirm the conversation shows up on the deployed dashboard
- Trigger an escalation — the alert you receive should link to the
  **real** dashboard URL, not localhost
- Restart the Background Worker service on Render (Manual Deploy →
  redeploy) and confirm past conversations are still there — that's the
  proof Postgres is actually being used instead of a SQLite file that
  would've been wiped

---

## Session 4: Real escalation delivery

**`core/notifier.py`** — sends a real Telegram message to the business
owner's own chat the moment `should_escalate=True`. No new bot needed —
it reuses the same bot token, just sends the alert to a different chat
(yours) instead of the customer's.

This is intentionally dependency-free (plain `urllib`, not the
`python-telegram-bot` library) so any future channel — the dashboard, an
email channel, etc. — can call `notifier.send_owner_alert()` directly
without needing a running bot instance.

### Setup

1. Get your own numeric Telegram id: message **[@userinfobot](https://t.me/userinfobot)**
   on Telegram — it replies instantly with your id.
2. ```bash
   export TELEGRAM_BOT_TOKEN='123456789:AA...'
   export ANTHROPIC_API_KEY='sk-ant-...'
   export OWNER_TELEGRAM_CHAT_ID='<the id @userinfobot gave you>'
   python telegram_bot.py
   ```

If `OWNER_TELEGRAM_CHAT_ID` isn't set, escalations are still detected and
logged to the console exactly like Session 2 — nothing breaks, you just
don't get the alert message.

### What to test

Message your bot something that should escalate (the refund/complaint
test again). You should get a **separate message from the same bot**,
sent to you directly, containing:
- which business it's for
- the reason for escalating
- what the customer actually said
- a link straight to that conversation in the dashboard (Session 3)

Note: the dashboard link only works if `dashboard.py` (Session 3) is
running locally at the same time — otherwise the link just won't load
anything yet, which is expected until Session 5's deployment.

---

## Session 3: Web dashboard

**`dashboard.py`** — a Flask app that reads from the same database the CLI
and Telegram bot write to. No new conversation logic here either — it's a
window into what's already happening.

Pages:
- `/` — list of businesses (tenants), with conversation counts
- `/tenant/new` — form to add a new business without touching code
- `/tenant/<id>` — that business's conversations, filterable by status
  (active / escalated / closed)
- `/tenant/<id>/conversation/<id>` — the full message thread, chat-bubble style

### Setup

```bash
pip install -r requirements.txt
python dashboard.py
```

Then open **http://localhost:5050**

### What to test

- Open it while the Telegram bot or CLI has already logged some
  conversations — you should see them listed, oldest activity first... actually
  most recent activity first.
- Click into a conversation you had escalate (the refund/complaint test from
  Session 1/2) — it should show the "escalated" badge and the full thread.
- Try the "+ Add business" form — create a second tenant with a different
  system prompt, confirm it shows up on the tenants list.

Note: creating a tenant here doesn't yet let you *route* a specific Telegram
bot to it — `telegram_bot.py` still uses `TENANT_ID`/first-tenant logic from
Session 2. Wiring "one dashboard, many bots" together is a natural Session 5
if you want to keep going after escalation delivery.

---

## Session 2: Telegram bot

**`telegram_bot.py`** — a real Telegram channel. It has zero conversation logic
of its own; it just receives messages and forwards them into the same
`core.engine.handle_message()` the CLI uses. That's the point of separating
the engine from the channel: adding Telegram didn't require touching the
brain at all.

### Setup

1. Create a bot via [@BotFather](https://t.me/BotFather) on Telegram (`/newbot`),
   get the token it gives you.
2. ```bash
   pip install -r requirements.txt
   export TELEGRAM_BOT_TOKEN='123456789:AA...'
   export ANTHROPIC_API_KEY='sk-ant-...'
   python chat_cli.py setup          # if you haven't already created a tenant
   python telegram_bot.py
   ```
3. Open your bot in Telegram and start chatting.

By default the bot uses the first tenant in the database. To pin it to a
specific one, set `TENANT_ID` to the id printed by `chat_cli.py setup`.

### What to test

Same as Session 1 — multi-turn memory and escalation — but now for real,
inside actual Telegram. Also worth testing: message the bot from two
different Telegram accounts (or ask a friend to) and confirm each gets
their own independent conversation thread, not a shared one.

Escalations aren't delivered anywhere yet — they're just logged to the
console (`ESCALATION FLAGGED ...`). Session 4 wires this up to a real
notification.

## Stack

Python, SQLite, Anthropic Claude API
