"""
Database layer for the AI Receptionist platform.

Three tables:
  tenants        — one row per client business using the platform
  conversations  — one row per ongoing chat thread (one external user <-> one tenant)
  messages       — every individual message in a conversation, in order

Uses SQLite for local development. The schema is deliberately simple and
portable — moving to Postgres later just means swapping the connection
layer, not the data model.
"""

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "platform.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    system_prompt   TEXT NOT NULL,
    escalation_rule TEXT DEFAULT 'low_confidence',
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id               TEXT PRIMARY KEY,
    tenant_id        TEXT NOT NULL REFERENCES tenants(id),
    channel          TEXT NOT NULL,           -- e.g. 'telegram', 'web', 'cli'
    external_user_id TEXT NOT NULL,           -- id of the human on that channel
    status           TEXT NOT NULL DEFAULT 'active',  -- active | escalated | closed
    created_at       TEXT NOT NULL,
    last_message_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role            TEXT NOT NULL,            -- 'user' | 'assistant' | 'system_note'
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversations_tenant ON conversations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


# ---------- Tenants ----------

def create_tenant(name: str, system_prompt: str, escalation_rule: str = "low_confidence") -> str:
    tenant_id = new_id()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO tenants (id, name, system_prompt, escalation_rule, created_at) VALUES (?, ?, ?, ?, ?)",
            (tenant_id, name, system_prompt, escalation_rule, now_iso()),
        )
    return tenant_id


def get_tenant(tenant_id: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()


def list_tenants() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM tenants ORDER BY created_at DESC").fetchall()


# ---------- Conversations ----------

def get_or_create_conversation(tenant_id: str, channel: str, external_user_id: str) -> str:
    """Find an existing active conversation for this user on this channel, or start one."""
    with get_conn() as conn:
        row = conn.execute(
            """SELECT id FROM conversations
               WHERE tenant_id = ? AND channel = ? AND external_user_id = ? AND status != 'closed'
               ORDER BY last_message_at DESC LIMIT 1""",
            (tenant_id, channel, external_user_id),
        ).fetchone()
        if row:
            return row["id"]

        conv_id = new_id()
        conn.execute(
            """INSERT INTO conversations
               (id, tenant_id, channel, external_user_id, status, created_at, last_message_at)
               VALUES (?, ?, ?, ?, 'active', ?, ?)""",
            (conv_id, tenant_id, channel, external_user_id, now_iso(), now_iso()),
        )
        return conv_id


def touch_conversation(conversation_id: str, status: str | None = None):
    with get_conn() as conn:
        if status:
            conn.execute(
                "UPDATE conversations SET last_message_at = ?, status = ? WHERE id = ?",
                (now_iso(), status, conversation_id),
            )
        else:
            conn.execute(
                "UPDATE conversations SET last_message_at = ? WHERE id = ?",
                (now_iso(), conversation_id),
            )


def get_conversation(conversation_id: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()


def list_conversations(tenant_id: str) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM conversations WHERE tenant_id = ? ORDER BY last_message_at DESC",
            (tenant_id,),
        ).fetchall()


# ---------- Messages ----------

def add_message(conversation_id: str, role: str, content: str) -> str:
    msg_id = new_id()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO messages (id, conversation_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (msg_id, conversation_id, role, content, now_iso()),
        )
    return msg_id


def get_history(conversation_id: str, limit: int = 20) -> list[sqlite3.Row]:
    """Return the last `limit` messages, oldest first — ready to feed into the Claude API."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM messages WHERE conversation_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (conversation_id, limit),
        ).fetchall()
    return list(reversed(rows))
