#!/usr/bin/env python3
"""A2A client for a REMOTE Hermes broker over Tailscale serve (HTTPS).

Copy this file to the Claude Code node, set two env vars, done:
    A2A_BROKER=https://desktop-u4s5sqt.tail7fdf03.ts.net
    A2A_TOKEN=<token from C:/Users/Thabang/symbiont/.agent_tokens.json on the server>

Auth header is `Bearer <name>:<token>` -- the broker splits on the first colon,
so a bare token 401s on every write path.

Use this over a2a_client.py (the local-only variant) whenever the broker is not
on 127.0.0.1. Only difference: BROKER is env-driven and tokens come from the
environment instead of the local .agent_tokens.json file.
"""
import json, os, sys, time, urllib.request, urllib.error

BROKER = os.environ.get("A2A_BROKER", "http://127.0.0.1:20129").rstrip("/")
AGENT = os.environ.get("A2A_AGENT", "claude")


def token(name=None):
    name = name or AGENT
    t = os.environ.get(f"A2A_TOKEN_{name.upper()}") or os.environ.get("A2A_TOKEN")
    if not t:
        raise SystemExit(f"set A2A_TOKEN (or A2A_TOKEN_{name.upper()}) for agent '{name}'")
    return t


def call(path, body=None, agent=None, method=None, timeout=30):
    """Single request helper. Returns parsed JSON, or {'error': ...} on HTTP error.

    ponytail: retry only on 5xx and transport failure, not on 4xx -- a 401 or 409
    is a real answer and must reach the caller instead of being retried.
    """
    agent = agent or AGENT
    url = BROKER + path
    data = json.dumps(body).encode() if body is not None else None
    attempts = 3 if method != "POST" or path == "/heartbeat" else 2
    last = None
    for i in range(attempts):
        req = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"))
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {agent}:{token(agent)}")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            body_txt = e.read().decode(errors="replace")
            if e.code < 500:
                return {"error": body_txt or str(e), "status": e.code}
            last = {"error": body_txt or str(e), "status": e.code}
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = {"error": f"transport: {e}"}
        if i < attempts - 1:
            time.sleep(1.5 * (i + 1))
    return last or {"error": "unreachable"}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print(f"broker: {BROKER}   agent: {AGENT}")
        print("usage: a2a_remote.py <cmd> [args]")
        print("  send <to> <text> | inbox [--unread] | read <id...> | agents | tasks")
        print("  task <to> <text> | review <to> <text> | claim | done <id> [result]")
        print("  watch [secs] | register <name> | tool <name> <desc> <cmd> | use <tool> <args>")
        return 1

    cmd, rest = sys.argv[1], sys.argv[2:]

    if cmd == "send":
        print(json.dumps(call("/send", {"to": rest[0], "content": " ".join(rest[1:]),
                                        "channel": os.environ.get("A2A_CHANNEL", "general")})))
    elif cmd == "inbox":
        q = f"/messages?agent={AGENT}" + ("&unread=true" if "--unread" in rest else "")
        for m in call(q).get("messages", []):
            print(f"[{m['id']}] {m['from']} ({m.get('channel','')}): {m['content']}")
        else:
            if not call(q).get("messages"):
                print("(empty)")
    elif cmd == "read":
        print(json.dumps(call("/read", {"message_ids": [int(i) for i in rest]})))
    elif cmd == "agents":
        print(json.dumps(call("/agents"), indent=2))
    elif cmd == "tasks":
        print(json.dumps(call("/tasks"), indent=2))
    elif cmd == "task":
        print(json.dumps(call("/task", {"to": rest[0], "content": " ".join(rest[1:]),
                                        "channel": os.environ.get("A2A_CHANNEL", "general")})))
    elif cmd == "review":
        # channel=review makes the broker auto-file a task back to claude on
        # completion -- but only when the completer is NOT claude (loop guard).
        print(json.dumps(call("/task", {"to": rest[0], "content": " ".join(rest[1:]),
                                        "channel": "review"})))
    elif cmd == "claim":
        for t in call("/tasks").get("tasks", []):
            if t["status"] == "pending" and t["to_agent"] in (None, "", AGENT):
                r = call("/task/claim", {"task_id": t["id"]})
                if "task_id" in r:
                    print(json.dumps(r))
                    break
        else:
            print(json.dumps({"error": "no pending task"}))
    elif cmd == "done":
        print(json.dumps(call("/task/complete",
                              {"task_id": int(rest[0]), "result": " ".join(rest[1:]) or None})))
    elif cmd == "watch":
        # Long-poll unread, auto-mark so the same message isn't re-delivered.
        # seen is per-process only: a restart re-reads, which is safer than
        # silently dropping a message the agent never saw.
        seen = set()
        while True:
            for m in call(f"/messages?agent={AGENT}&unread=true").get("messages", []):
                if m["id"] not in seen:
                    seen.add(m["id"])
                    print(f"[{m['id']}] {m['from']}: {m['content']}", flush=True)
                    call("/read", {"message_ids": [m["id"]]})
            time.sleep(float(rest[0]) if rest else 2)
    elif cmd == "register":
        # Needs A2A_REGISTRATION_KEY; the broker never discloses an existing token.
        name = rest[0] if rest else AGENT
        r = call("/register", {"name": name,
                               "registration_key": os.environ.get("A2A_REGISTRATION_KEY")},
                 agent=name, method="POST")
        print(json.dumps(r))
    elif cmd == "tool":
        print(json.dumps(call("/tool", {"name": rest[0], "description": " ".join(rest[1:2]),
                                        "command": " ".join(rest[2:]) or ""})))
    elif cmd == "use":
        print(json.dumps(call("/tools/invoke", {"tool": rest[0], "args": " ".join(rest[1:])})))
    else:
        print(f"unknown cmd: {cmd}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
