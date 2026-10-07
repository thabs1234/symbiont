#!/usr/bin/env python3
"""Claude Code SessionStart hook: inject unread A2A broker messages as context.

Claude Code >=2.1 calls this on session start, feeding the hook JSON on stdin.
Whatever we print on stdout is injected into the session, so the pending
symbiosis queue lands in the model's context without a poller or daemon.

Exit 0 with empty stdout = nothing pending, Claude proceeds normally.
"""
import json
import os
import sqlite3
import sys
import time
import urllib.request

BROKER = "http://127.0.0.1:20129"
TOKENS = r"C:/Users/Thabang/symbiont/.agent_tokens.json"
DB = r"C:/Users/Thabang/symbiont/a2a.db"
ME = os.environ.get("A2A_AGENT", "claude")


def pending():
    """Read straight from the broker's own SQLite.

    No HTTP, no auth header, no network: the file IS the broker's state. This
    keeps the hook dependency-free and immune to broker 5xx during startup.
    """
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=3)
    try:
        return con.execute(
            "SELECT id, sender, content, timestamp FROM messages "
            "WHERE recipient = ? AND read_by IS NULL ORDER BY id",
            (ME,),
        ).fetchall()
    finally:
        con.close()


def pending_tasks():
    """Pending tasks addressed to ME (or unaddressed), oldest first.

    Same read-only SQLite path as pending(): the broker's own file is the state,
    so a task can reach a session even while the broker is briefly 5xx.
    """
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=3)
    try:
        return con.execute(
            "SELECT id, from_agent, content FROM tasks "
            "WHERE status = 'pending' AND (to_agent IS NULL OR to_agent = '' OR to_agent = ?) "
            "ORDER BY id",
            (ME,),
        ).fetchall()
    finally:
        con.close()


def mark_read(ids):
    with open(TOKENS, encoding="utf-8-sig") as f:
        tok = json.load(f)[ME]
    body = json.dumps({"message_ids": ids}).encode()
    req = urllib.request.Request(
        f"{BROKER}/read", data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {ME}:{tok}"},
    )
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:
        pass  # leaving rows unread only means re-delivery, never data loss


def main():
    try:
        rows = pending()
        tasks = pending_tasks()
    except Exception:
        return 0  # never block a Claude session on a broker hiccup

    if not rows and not tasks:
        return 0

    lines = []
    if tasks:
        lines += ["## Symbiosis tasks — claim one, answer it, move on", ""]
        for tid, sender, content in tasks:
            lines.append(f"- **task {tid}** (from {sender}): {content}")
        lines += [
            "",
            "Claim: `python C:/Users/Thabang/symbiont/a2a_client.py claim`",
            "Finish: `python C:/Users/Thabang/symbiont/a2a_client.py done <task_id> \"<your answer>\"`",
            "Do the work, answer in full, then continue your own work. Do not stop to wait.",
            "",
        ]
    if rows:
        lines += ["## Symbiosis queue — unread A2A messages", ""]
        for mid, sender, content, created in rows:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(created))
            lines.append(f"- **{sender}** (msg {mid}, {when}): {content}")
        lines += [
            "",
            "Reply with `python C:/Users/Thabang/symbiont/a2a_client.py send hermes \"<reply>\"` "
            "then continue with your own work; do not stop to wait.",
        ]

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n".join(lines),
        }
    }))
    if rows:
        mark_read([r[0] for r in rows])
    return 0


if __name__ == "__main__":
    sys.exit(main())
