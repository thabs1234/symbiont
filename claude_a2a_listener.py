#!/usr/bin/env python3
"""
Claude-side A2A listener for hub-and-spoke duo — artifact mode.

Hermes writes artifacts (scraped data, JSON/CSV/TXT) to /tmp/scraper_out/.
Claude polls the broker for tasks, processes artifacts, and replies to Hermes.

Pattern: Hermes owns the pipeline → produces artifacts → Claude consumes → Hermes posts.
No ping-pong handoff; Claude never passes tasks back, only results.
"""

import sys
import os
import json
import time
import glob
import re

sys.path.insert(0, os.path.dirname(__file__))
from a2a_client import A2AClient

MY_NAME = "claude"
TARGET = "hermes"
POLL_INTERVAL = 5  # seconds
ARTIFACT_DIR = os.path.join(os.path.dirname(__file__), "scraper_out")

# Ensure artifact directory exists
os.makedirs(ARTIFACT_DIR, exist_ok=True)


def discover_artifacts():
    """Find all artifacts in scraper_out/."""
    patterns = [os.path.join(ARTIFACT_DIR, "*.json"), os.path.join(ARTIFACT_DIR, "*.csv"),
                os.path.join(ARTIFACT_DIR, "*.txt"), os.path.join(ARTIFACT_DIR, "*.md")]
    files = []
    for p in patterns:
        files.extend(glob.glob(p))
    return sorted(files)


def read_artifact(path):
    """Read an artifact file safely."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading {path}: {e}"


def process_task(task_text):
    """Process a task from Hermes — artifact consumer mode."""
    # If Hermes sent a task referencing an artifact, read it
    if "artifact:" in task_text.lower():
        match = re.search(r"artifact:\s*(\S+)", task_text, re.IGNORECASE)
        if match:
            artifact_path = match.group(1)
            if os.path.exists(artifact_path):
                content = read_artifact(artifact_path)
                return f"Processed artifact {artifact_path}: {content[:200]}"
            else:
                return f"Artifact not found: {artifact_path}"

    # Check for recently produced artifacts
    artifacts = discover_artifacts()
    if artifacts:
        latest = artifacts[-1]
        content = read_artifact(latest)
        return f"Consumed latest artifact {os.path.basename(latest)}: {content[:200]}"

    # Fallback: simple task processing
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
    print(f"[{MY_NAME}] Starting A2A artifact listener on {client.broker}", file=sys.stderr)
    print(f"[{MY_NAME}] Hermes writes artifacts to {ARTIFACT_DIR}", file=sys.stderr)
    print(f"[{MY_NAME}] Claude consumes artifacts, replies to '{TARGET}'", file=sys.stderr)

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

                # Process the task (consume artifacts + produce result)
                result = process_task(task_content)

                # Complete the task with result
                done = client.done(task_id, result)
                print(f"[{MY_NAME}] Completed task {task_id}: {result[:80]}", file=sys.stderr)

                # Send reply back to Hermes (Hermes posts to WhatsApp)
                reply_msg = client.send(TARGET, result)
                print(f"[{MY_NAME}] Sent reply to {TARGET}: {result[:80]} (msg_id={reply_msg.get('message_id')})", file=sys.stderr)
            else:
                # No tasks available — just sleep
                pass

        except Exception as e:
            print(f"[{MY_NAME}] Error: {e}", file=sys.stderr)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()