"""
Database layer for the AI Receptionist platform.

Three tables:
  tenants        — one row per client business using the platform
  conversations  — one row per ongoing chat thread (one external user <-> one tenant)
  messages       — every individual message in a conversation, in order

Uses SQLite for local development (a plain file, zero setup). In production
(Render), set DATABASE_URL and this switches to Postgres automatically —
SQLite files don't survive restarts/redeploys on most cloud platforms, so
this matters the moment this stops running only on your own laptop.

The rest of the codebase (engine.py, dashboard.py, telegram_bot.py) never
needs to know which one is active — they just call these functions.
"""

import os
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


def _using_postgres() -> bool:
    return bool(os.environ.get("DATABASE_URL"))


class _PGConn:
    """Thin wrapper so Postgres can be used with the same execute()-then-
    fetchone()/fetchall() calling style the rest of this file already uses
    for sqlite3.Connection. Converts '?' placeholders to psycopg2's '%s'."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, query: str, params=()):
        cur = self._conn.cursor()
        cur.execute(query.replace("?", "%s"), params)
        return cur

    def executescript(self, script: str):
        cur = self._conn.cursor()
        cur.execute(script)


@contextmanager
def get_conn():
    if _using_postgres():
        import psycopg2
        import psycopg2.extras

        conn = psycopg2.connect(
            os.environ["DATABASE_URL"],
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
        wrapper = _PGConn(conn)
        try:
            yield wrapper
            conn.commit()
        finally:
            conn.close()
    else:
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


def list_conversations_with_counts(tenant_id: str) -> list[sqlite3.Row]:
    """Same as list_conversations, but includes a message_count column — used by the dashboard."""
    with get_conn() as conn:
        return conn.execute(
            """SELECT c.*, COUNT(m.id) AS message_count
               FROM conversations c
               LEFT JOIN messages m ON m.conversation_id = c.id
               WHERE c.tenant_id = ?
               GROUP BY c.id
               ORDER BY c.last_message_at DESC""",
            (tenant_id,),
        ).fetchall()


def count_conversations_by_status(tenant_id: str) -> dict:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) as n FROM conversations WHERE tenant_id = ? GROUP BY status",
            (tenant_id,),
        ).fetchall()
    return {r["status"]: r["n"] for r in rows}


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
