#!/usr/bin/env python3
"""
Claude-side A2A listener for hub-and-spoke duo.
Uses A2AClient to claim tasks from broker, process them, complete them, and send reply to Hermes.
"""

import sys
import os
import json
import time

sys.path.insert(0, os.path.dirname(__file__))
from a2a_client import A2AClient


MY_NAME = "claude"
TARGET = "hermes"
POLL_INTERVAL = 5  # seconds


def process_task(task_text):
    """Process a task from Hermes and return plain-text answer."""
    if task_text.lower().startswith("ping"):
        return "pong"
    if "task line:" in task_text.lower():
        lines = task_text.split("\n")
        for line in lines:
            if line.lower().startswith("task line:"):
                task = line.split(":", 1)[1].strip()
                return f"Processed: {task}"
    return f"Received: {task_text[:100]}"


def main():
    client = A2AClient(agent=MY_NAME)
    print(f"[{MY_NAME}] Starting A2A task listener on {client.broker}", file=sys.stderr)
    print(f"[{MY_NAME}] Will claim tasks for '{MY_NAME}' and reply to '{TARGET}'", file=sys.stderr)

    # Quick health check
    status = client.status()
    print(f"[{MY_NAME}] Broker status: {status}", file=sys.stderr)

    while True:
        try:
            # Claim next pending task for this agent
            claimed = client.claim_next()

            if claimed.get("task_id"):
                task_id = claimed["task_id"]
                task_content = claimed.get("content", "")
                task_from = claimed.get("from", "unknown")

                print(f"[{MY_NAME}] Claimed task {task_id} from {task_from}: {task_content[:80]}", file=sys.stderr)

                # Process the task
                result = process_task(task_content)

                # Complete the task with result
                done = client.done(task_id, result)
                print(f"[{MY_NAME}] Completed task {task_id}: {result[:80]}", file=sys.stderr)

                # Send reply back to Hermes
                reply_msg = client.send(TARGET, result)
                print(f"[{MY_NAME}] Sent reply to {TARGET}: {result[:80]} (msg_id={reply_msg.get('message_id')})", file=sys.stderr)
            else:
                # No tasks available
                pass

        except Exception as e:
            print(f"[{MY_NAME}] Error: {e}", file=sys.stderr)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()