#!/usr/bin/env python3
"""
Web dashboard for the AI Receptionist platform.

Read-mostly view over the same database the CLI and Telegram bot write to:
  /                          — list of tenants
  /tenant/new                — form to create a new tenant
  /tenant/<id>                — list of that tenant's conversations
  /tenant/<id>/conversation/<conv_id> — full message thread for one conversation

Run:
    pip install -r requirements.txt
    python dashboard.py
Then open http://localhost:5050
"""

import os

from flask import Flask, render_template, request, redirect, url_for

from core import db

app = Flask(__name__)
db.init_db()


@app.route("/")
def tenants_list():
    db.init_db()
    tenants = db.list_tenants()
    tenant_stats = {}
    for t in tenants:
        counts = db.count_conversations_by_status(t["id"])
        tenant_stats[t["id"]] = {
            "total": sum(counts.values()),
            "escalated": counts.get("escalated", 0),
            "active": counts.get("active", 0),
        }
    return render_template("tenants.html", tenants=tenants, stats=tenant_stats)


@app.route("/tenant/new", methods=["GET", "POST"])
def new_tenant():
    if request.method == "POST":
        name = request.form["name"].strip()
        system_prompt = request.form["system_prompt"].strip()
        if name and system_prompt:
            db.create_tenant(name=name, system_prompt=system_prompt)
        return redirect(url_for("tenants_list"))
    return render_template("new_tenant.html")


@app.route("/tenant/<tenant_id>")
def tenant_conversations(tenant_id):
    tenant = db.get_tenant(tenant_id)
    if tenant is None:
        return "Tenant not found", 404

    status_filter = request.args.get("status", "all")
    conversations = db.list_conversations_with_counts(tenant_id)
    if status_filter != "all":
        conversations = [c for c in conversations if c["status"] == status_filter]

    counts = db.count_conversations_by_status(tenant_id)

    return render_template(
        "conversations.html",
        tenant=tenant,
        conversations=conversations,
        status_filter=status_filter,
        counts=counts,
    )


@app.route("/tenant/<tenant_id>/conversation/<conversation_id>")
def conversation_thread(tenant_id, conversation_id):
    tenant = db.get_tenant(tenant_id)
    conversation = db.get_conversation(conversation_id)
    if tenant is None or conversation is None or conversation["tenant_id"] != tenant_id:
        return "Conversation not found", 404

    messages = db.get_history(conversation_id, limit=200)

    return render_template(
        "conversation.html",
        tenant=tenant,
        conversation=conversation,
        messages=messages,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    debug_mode = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
