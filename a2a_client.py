#!/usr/bin/env python3
"""A2A broker client. stdlib only.

Auth header is `Bearer <name>:<token>` — the broker splits on the first colon
(a2a_broker.py:184), so a bare token 401s on every write path.
"""
import json, sys, time, urllib.request, urllib.error

BROKER = "http://127.0.0.1:20129"
TOKENS = r"C:/Users/Thabang/symbiont/.agent_tokens.json"


def token(name):
    with open(TOKENS, encoding="utf-8-sig") as f:
        return json.load(f)[name]


def call(path, body=None, agent=None, method=None):
    url = BROKER + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"))
    req.add_header("Content-Type", "application/json")
    if agent:
        req.add_header("Authorization", f"Bearer {agent}:{token(agent)}")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("usage: a2a_client.py <cmd> [args]   (agent name from $A2A_AGENT, default claude)")
        return 1

    cmd = sys.argv[1]
    import os
    me = os.environ.get("A2A_AGENT", "claude")
    rest = sys.argv[2:]

    if cmd == "send":
        print(json.dumps(call("/send", {"to": rest[0], "content": " ".join(rest[1:])}, agent=me)))
    elif cmd == "inbox":
        msgs = call(f"/messages?agent={me}{'&unread=true' if '--unread' in rest else ''}", agent=me)["messages"]
        for m in msgs:
            print(f"[{m['id']}] {m['from']} ({m['channel']}): {m['content']}")
        if not msgs:
            print("(empty)")
    elif cmd == "read":
        ids = [int(i) for i in rest]
        print(json.dumps(call("/read", {"message_ids": ids}, agent=me)))
    elif cmd == "agents":
        print(json.dumps(call("/agents", agent=me), indent=2))
    elif cmd == "tasks":
        print(json.dumps(call("/tasks", agent=me), indent=2))
    elif cmd == "task":
        print(json.dumps(call("/task", {"to": rest[0], "content": " ".join(rest[1:]),
                                        "channel": os.environ.get("A2A_CHANNEL", "general")},
                              agent=me)))
    elif cmd == "review":
        # Request the return trip. channel=review is what makes the broker auto-file
        # a task back to claude when this task is completed.
        print(json.dumps(call("/task", {"to": rest[0], "content": " ".join(rest[1:]),
                                        "channel": "review"}, agent=me)))
    elif cmd == "tools":
        found = call("/tools", agent=me)["tools"]
        for t in found:
            mine = " (mine)" if t["owner"] == me else ""
            print(f"{t['name']} -> {t['owner']}{mine}: {t['description']}")
        if not found:
            print("(no tools registered)")
    elif cmd == "regtool":
        print(json.dumps(call("/tool", {"name": rest[0], "description": " ".join(rest[1:2]),
                                        "command": rest[2] if len(rest) > 2 else ""}, agent=me)))
    elif cmd == "use":
        # Shared tool call. Owned by you -> we hand you the command to run.
        # Owned by someone else -> it becomes a task for them and you get the id back.
        print(json.dumps(call("/tools/invoke", {"tool": rest[0], "args": " ".join(rest[1:])}, agent=me)))
    elif cmd == "claim":
        # Broker has no "next for me" endpoint: pick locally, claim by id.
        # 409 means another agent won the race, so keep walking the list.
        for t in call("/tasks", agent=me)["tasks"]:
            if t["status"] == "pending" and t["to_agent"] in (None, "", me):
                r = call("/task/claim", {"task_id": t["id"]}, agent=me)
                if "task_id" in r:
                    print(json.dumps(r))
                    break
        else:
            print(json.dumps({"error": "no pending task"}))
    elif cmd == "done":
        print(json.dumps(call("/task/complete",
                              {"task_id": int(rest[0]), "result": " ".join(rest[1:]) or None},
                              agent=me)))
    elif cmd == "watch":
        # long-poll unread, auto-mark so the same message isn't re-delivered
        seen = set()
        while True:
            for m in call(f"/messages?agent={me}&unread=true", agent=me)["messages"]:
                if m["id"] not in seen:
                    seen.add(m["id"])
                    print(f"[{m['id']}] {m['from']}: {m['content']}", flush=True)
                    call("/read", {"message_ids": [m["id"]]}, agent=me)
            time.sleep(float(rest[0]) if rest else 2)
    else:
        print(f"unknown cmd: {cmd}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
