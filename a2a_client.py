#!/usr/bin/env python3
"""A2A Client - Agent-to-Agent interface for the symbiosis broker on :20129.

Stdlib only. Usable as CLI and Python module.
"""
import sys
import os
import json
import urllib.request
import urllib.error

BROKER_URL = os.environ.get("A2A_BROKER", "http://127.0.0.1:20129")
TOKENS_PATH = os.environ.get("A2A_TOKENS", r"C:/Users/Thabang/symbiont/.agent_tokens.json")
DEFAULT_AGENT = os.environ.get("A2A_AGENT", "claude")


class A2AClient:
    def __init__(self, agent=DEFAULT_AGENT, broker=BROKER_URL, tokens_path=TOKENS_PATH):
        self.agent = agent
        self.broker = broker.rstrip("/")
        self.tokens_path = tokens_path
        self._token = None

    @property
    def token(self):
        if not self._token:
            if os.path.exists(self.tokens_path):
                with open(self.tokens_path, "r", encoding="utf-8-sig") as f:
                    tokens = json.load(f)
                    self._token = tokens.get(self.agent)
        return self._token

    def _request(self, path, method="GET", data=None, auth=True):
        url = f"{self.broker}{path}"
        headers = {"Content-Type": "application/json"}
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.agent}:{self.token}"

        body = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8")
            try:
                err_json = json.loads(err_body)
                return {"error": err_json.get("error", str(e)), "code": e.code}
            except Exception:
                return {"error": err_body or str(e), "code": e.code}
        except Exception as e:
            return {"error": str(e), "code": 500}

    def status(self):
        return self._request("/status", auth=False)

    def queue_health(self):
        return self._request("/health/queue", auth=False)

    def send(self, to, content, channel="general"):
        return self._request("/send", method="POST", data={"to": to, "content": content, "channel": channel})

    def messages(self, unread=True, channel=None):
        path = f"/messages?agent={self.agent}&unread={'true' if unread else 'false'}"
        if channel:
            path += f"&channel={channel}"
        return self._request(path)

    def mark_read(self, message_ids):
        return self._request("/read", method="POST", data={"message_ids": message_ids})

    def create_task(self, to, content, channel="general"):
        return self._request("/task", method="POST", data={"to": to, "content": content, "channel": channel})

    def claim_next(self):
        return self._request("/task/claim-next", method="POST", data={})

    def claim(self, task_id):
        return self._request("/task/claim", method="POST", data={"task_id": int(task_id)})

    def done(self, task_id, result=""):
        return self._request("/task/complete", method="POST", data={"task_id": int(task_id), "result": result})

    def memory_store(self, key, value):
        return self._request("/memory/store", method="POST", data={"key": key, "value": value})

    def memory_get(self, search=None):
        path = f"/memory?agent={self.agent}"
        if search:
            path += f"&search={search}"
        return self._request(path)


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print("Usage:")
        print("  a2a_client.py claim                  # Claim next pending task for this agent")
        print("  a2a_client.py done <task_id> <result># Complete task")
        print("  a2a_client.py send <to> <content>    # Send A2A message")
        print("  a2a_client.py messages [--unread]    # Fetch messages")
        print("  a2a_client.py task <to> <content>    # Create a task")
        print("  a2a_client.py status                 # Broker status + queue health")
        return 0

    cmd = args[0]
    client = A2AClient()

    if cmd == "claim":
        res = client.claim_next()
        print(json.dumps(res, indent=2))
    elif cmd == "done":
        if len(args) < 2:
            print("Error: task_id required", file=sys.stderr)
            return 1
        task_id = args[1]
        res_str = " ".join(args[2:]) if len(args) > 2 else "done"
        res = client.done(task_id, res_str)
        print(json.dumps(res, indent=2))
    elif cmd == "send":
        if len(args) < 3:
            print("Error: to and content required", file=sys.stderr)
            return 1
        to = args[1]
        content = " ".join(args[2:])
        res = client.send(to, content)
        print(json.dumps(res, indent=2))
    elif cmd == "messages":
        unread = "--all" not in args
        res = client.messages(unread=unread)
        print(json.dumps(res, indent=2))
    elif cmd == "task":
        if len(args) < 3:
            print("Error: to and content required", file=sys.stderr)
            return 1
        to = args[1]
        content = " ".join(args[2:])
        res = client.create_task(to, content)
        print(json.dumps(res, indent=2))
    elif cmd == "status":
        s = client.status()
        q = client.queue_health()
        print(json.dumps({"status": s, "queue": q}, indent=2))
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
