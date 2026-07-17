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

- Basic auth on the dashboard (right now anyone with the URL can see all
  conversations — fine for a personal demo, not fine for a real client)

---

## Session 6: Real bot-to-tenant routing

Before this session, the Telegram webhook always answered as whichever
tenant happened to be "first" in the database — fine for one business,
broken the moment a second one existed. Now each business can have its
**own** Telegram bot, and both work independently, at the same time, on
the same free Web Service.

### How it works

- Each tenant can store its own `telegram_bot_token` (set when creating
  the business, or added later via `db.update_tenant_bot_token()`)
- The webhook URL now includes the tenant's id:
  `/telegram/webhook/<tenant_id>` — so the URL itself identifies which
  business a message is for, no guessing needed
- The dashboard's per-business page now shows that exact URL, ready to
  register

### Setup for a new business

1. Create a bot via @BotFather for this business specifically
2. On the dashboard, **+ Add business**, paste that bot's token into
   "Telegram bot token"
3. Open that business's page on the dashboard — copy the webhook URL shown
4. Register it once:
   ```
   https://api.telegram.org/bot<THAT_BUSINESS_BOT_TOKEN>/setWebhook?url=<THE_URL_FROM_STEP_3>
   ```
5. Message that bot — it replies using that business's own instructions
   and memory, completely independent of any other business's bot

### What to test

- Create two businesses with different bot tokens and different system
  prompts (e.g. a skincare shop and a bakery)
- Message each bot separately — confirm each answers according to its own
  instructions, and conversations don't cross over
- Check the dashboard — each business's conversations list stays separate

### Migration note

Existing deployments (the Postgres database already running on Render)
didn't have a `telegram_bot_token` column before this session. `core/db.py`
now runs a small migration automatically on startup — no manual database
changes needed, just redeploy.

⚠️ The webhook URL itself also changed shape (from `/telegram/webhook` to
`/telegram/webhook/<tenant_id>`). If you already had a bot working from
Session 5, its webhook is still pointed at the old URL, which no longer
exists. Re-register it: open that business's page on the dashboard, copy
the new URL shown there, and run `setWebhook` again with it. The bot will
keep working exactly as before — its `telegram_bot_token` field is empty
in the database, so it automatically falls back to the global
`TELEGRAM_BOT_TOKEN` environment variable, same as previously.

---

## Session 5: Deploying to the cloud

Two things needed to change to run this in the cloud instead of just on
your laptop:

- The database needed to move from a local SQLite file (which doesn't
  survive a restart on most cloud platforms) to real Postgres. `core/db.py`
  already supports both — it switches automatically based on whether a
  `DATABASE_URL` environment variable is set.
- The Telegram bot needed to stop *polling* Telegram (which requires a
  long-running process — Render only offers that as a paid "Background
  Worker", no free tier) and instead receive messages via a **webhook**:
  Telegram calls a URL on your existing free dashboard service the moment
  someone messages the bot. No separate paid service required, and it's
  the standard production approach anyway (lower latency than polling).

`telegram_bot.py` (polling) still exists and is the easiest way to test
locally without deploying anything. `dashboard.py` now also exposes a
per-business webhook (`/telegram/webhook/<tenant_id>` — see Session 6
below for why it's per-business), which does the same job for the
deployed version.

### Step 1 — Create a Postgres database on Render

1. On [dashboard.render.com](https://dashboard.render.com), **New +** → **Postgres**
2. Free plan, same region as your other services, create it
3. Copy the **Internal Database URL** from its Connections page

### Step 2 — Deploy the dashboard as a Web Service

1. Push this project to GitHub (`git remote add origin ...`, `git push -u origin main`)
2. On Render: **New +** → **Web Service** → connect the repo
3. Settings:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn dashboard:app --bind 0.0.0.0:$PORT`
4. Environment variables:
   - `DATABASE_URL` = the Postgres URL from Step 1
   - `TELEGRAM_BOT_TOKEN` = your customer-facing bot token
   - `ANTHROPIC_API_KEY` = your Claude API key
   - `OWNER_TELEGRAM_CHAT_ID` = your numeric Telegram id
   - `ADMIN_BOT_TOKEN` = *(recommended)* token of a **second, separate**
     bot used only for escalation alerts — see below for why
5. Deploy, note the public URL Render gives you.

(No need to set `DASHBOARD_URL` — the webhook route figures out its own
public address from the incoming request, so escalation links are always
correct without manual configuration.)

### Why a separate admin bot

Telegram doesn't support separate "threads" within one private chat — if
the owner alert and the customer conversation both come from the same bot
to the same Telegram account (e.g. while testing solo, playing both
roles), they land in the same chat, mixed together. In real use, the
business owner and the customer are different people so this naturally
doesn't happen — but a second bot keeps it clean either way, and makes
testing solo much easier to follow.

To set one up: message **@BotFather** again, `/newbot`, give it a
different name (e.g. "Luna Skincare Admin Alerts"), copy its token into
`ADMIN_BOT_TOKEN`. Message that new bot once yourself so it's allowed to
message you back. If `ADMIN_BOT_TOKEN` isn't set, alerts fall back to
using `TELEGRAM_BOT_TOKEN` (the old behavior).

### Step 3 — Point Telegram at the webhook (one-time, no server needed)

Create at least one business on the deployed dashboard first (**+ Add
business**) — its page will show you the exact webhook URL to use,
including its tenant id. Visit this once in any browser:

```
https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=<URL_SHOWN_ON_DASHBOARD>
```

You should get back `{"ok":true,"result":true,"description":"Webhook was set"}`.
From this point on, Telegram pushes messages straight to your deployed
dashboard — no bot process needs to be running anywhere.

### What to test

- Message the bot on Telegram — it should reply using the deployed service
  (check Render's logs for the `/telegram/webhook/...` request coming in)
- Confirm the conversation shows up on the deployed dashboard
- Trigger an escalation — the alert should arrive in Telegram and link to
  the real dashboard URL, not localhost
- Restart the Web Service on Render (Manual Deploy) and confirm past
  conversations are still there — proof Postgres is actually persisting
  data instead of a SQLite file that would've been wiped

### If you outgrow the free tier later

`telegram_bot.py` (the polling version) is still there if you ever want to
run this as a dedicated worker instead — same `core/engine.py` underneath,
nothing to rewrite.

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
