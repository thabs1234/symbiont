#!/usr/bin/env python3
"""Hermes A2A Bridge - Connect Hermes agent to symbiosis broker on :20129.

Polls the A2A broker for messages/tasks assigned to 'hermes', dispatches them
to Hermes CLI ('hermes chat'), and posts responses back to the broker.

Usage:
  python hermes_a2a_bridge.py once       # Run a single poll & process cycle
  python hermes_a2a_bridge.py loop       # Run continuous polling daemon
  python hermes_a2a_bridge.py send "<msg>" # Send message from Hermes to Claude
"""
import sys
import os
import time
import subprocess
import json
from a2a_client import A2AClient

HERMES_AGENT = "hermes"


def run_hermes_cli(prompt, max_turns=6):
    """Invoke Hermes CLI in one-shot query mode and return output."""
    cmd = [
        "hermes",
        "chat",
        "-q",
        prompt,
        "-Q",
        "--max-turns",
        str(max_turns),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if proc.returncode == 0 and out:
            return out
        return out if out else f"Hermes exit {proc.returncode}: {err}"
    except subprocess.TimeoutExpired:
        return "Hermes CLI timed out after 120s"
    except FileNotFoundError:
        return "Hermes CLI executable not found on PATH"
    except Exception as e:
        return f"Hermes execution error: {e}"


class HermesA2ABridge:
    def __init__(self):
        self.client = A2AClient(agent=HERMES_AGENT)

    def process_messages(self):
        """Fetch and process unread messages for Hermes."""
        res = self.client.messages(unread=True)
        msgs = res.get("messages", [])
        if not msgs:
            return 0

        print(f"[{HERMES_AGENT}] Processing {len(msgs)} message(s)...")
        read_ids = []
        for m in msgs:
            mid = m["id"]
            sender = m.get("from", "unknown")
            content = m.get("content", "")
            channel = m.get("channel", "general")
            print(f"[{HERMES_AGENT}] From {sender} ({channel}): {content[:80]}")

            # Get Hermes response
            prompt = (
                f"You received an A2A message from '{sender}' in channel '{channel}':\n"
                f"{content}\n\n"
                f"Provide a terse, direct response or action."
            )
            reply = run_hermes_cli(prompt)
            print(f"[{HERMES_AGENT}] Reply to {sender}: {reply[:80]}")

            # Send reply back to broker
            self.client.send(to=sender, content=reply, channel=channel)
            read_ids.append(mid)

        if read_ids:
            self.client.mark_read(read_ids)
        return len(msgs)

    def process_tasks(self):
        """Claim and execute pending tasks for Hermes."""
        claim_res = self.client.claim_next()
        task = claim_res.get("task")
        task_id = claim_res.get("task_id")
        if not task or not task_id:
            return False

        content = task.get("content", "")
        from_agent = task.get("from", "claude")
        channel = task.get("channel", "general")
        print(f"[{HERMES_AGENT}] Claimed task {task_id} from {from_agent}: {content[:80]}")

        prompt = (
            f"You have been assigned task {task_id} by '{from_agent}' in channel '{channel}':\n"
            f"{content}\n\n"
            f"Execute or resolve this task and return your final answer."
        )
        result = run_hermes_cli(prompt)
        print(f"[{HERMES_AGENT}] Completed task {task_id}: {result[:80]}")

        done_res = self.client.done(task_id, result=result)
        print(f"[{HERMES_AGENT}] Filed completion: {done_res}")
        return True

    def poll_cycle(self):
        m_count = self.process_messages()
        t_claimed = self.process_tasks()
        return m_count > 0 or t_claimed


def main():
    args = sys.argv[1:]
    mode = args[0] if args else "once"
    bridge = HermesA2ABridge()

    if mode == "once":
        active = bridge.poll_cycle()
        print(f"Hermes A2A cycle finished. Active work: {active}")
    elif mode == "loop":
        interval = int(args[1]) if len(args) > 1 else 5
        print(f"Hermes A2A daemon running (interval {interval}s). Ctrl+C to stop.")
        try:
            while True:
                bridge.poll_cycle()
                time.sleep(interval)
        except KeyboardInterrupt:
            print("Daemon stopped.")
    elif mode == "send":
        if len(args) < 2:
            print("Usage: hermes_a2a_bridge.py send \"<message>\"")
            return 1
        msg = " ".join(args[1:])
        res = bridge.client.send(to="claude", content=msg)
        print(json.dumps(res, indent=2))
    else:
        print(f"Unknown mode: {mode}. Use 'once', 'loop', or 'send'.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
