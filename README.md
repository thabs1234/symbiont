# Symbiosis — Agent Bridge Components

## Components

1. **A2A Broker** (`a2a_broker.py`) - Agent-to-Agent message broker on port 20129
2. **Telegram Bridge** (`telegram_bridge.js`) - Node.js Telegram bot, fans out to `hermes` + `claude`

## Fleet

| Agent | Capabilities | Notes |
|-------|--------------|-------|
| `hermes` | converse, code, messaging, memory | gateway + `hermes` CLI |
| `claude` | converse, code, review, memory | Claude Code CLI |
| `telegram` | messaging | registers itself on bridge start |

`chatgpt` was retired on 2026-09-29 — ChatGPT Desktop was uninstalled, so `chatgpt_a2a.py`,
`chatgpt_connect.py` and `a2a_inject.py` are gone and are not to be recreated. Claude Code reaches
the broker over HTTP like any other client; it needs no desktop-injection bridge.

Shared state lives in `collective.md` (fleet + session log) and `goals.md` (current objectives).

## Quick Start

### 1. Start A2A Broker
```powershell
Start-Process python -ArgumentList "a2a_broker.py" -WorkingDirectory "C:/Users/Thabang/symbiont" -WindowStyle Hidden
```
Health check: `curl -s http://127.0.0.1:20129/status`

### 2. Register Agents
```powershell
curl -X POST http://127.0.0.1:20129/register -H "Content-Type: application/json" -d '{"name":"hermes","capabilities":["converse","code","messaging","memory"]}'
curl -X POST http://127.0.0.1:20129/register -H "Content-Type: application/json" -d '{"name":"claude","capabilities":["converse","code","review","memory"]}'
```

Registration is **idempotent** — re-registering an existing name returns the same token rather than
minting a new one, so it is safe to run on every start. Tokens are stored in `.agent_tokens.json`
(gitignored).

### 3. Send / Receive
```powershell
# send (auth header is <agent>:<token>)
curl -X POST http://127.0.0.1:20129/send -H "Content-Type: application/json" `
  -H "Authorization: Bearer hermes:<token>" -d '{"to":"claude","content":"hello","channel":"general"}'

# read inbox (no auth required on /messages)
curl -s "http://127.0.0.1:20129/messages?agent=claude&unread=true"
```

### 4. Telegram Bridge Setup
1. Get bot token from @BotFather on Telegram
2. Set `TELEGRAM_BOT_TOKEN` in the environment (`telegram_bridge.js` reads it from `process.env`)
3. Run: `node "C:/Users/Thabang/symbiont/telegram_bridge.js"`
   - Requires `npm install node-telegram-bot-api`

Inbound messages are fanned out to every agent in the `FANOUT` array at the top of the bridge, so
adding a third agent is a one-line edit.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/register` | POST | Register agent, get auth token (idempotent) |
| `/send` | POST | Send message to another agent |
| `/messages` | GET | Get messages (filter by agent, channel) |
| `/read` | POST | Mark messages as read |
| `/task` | POST | Create a task |
| `/task/claim` | POST | Claim a specific pending task by `task_id` |
| `/task/claim-next` | POST | Atomically claim the oldest task addressed to the caller (or unaddressed). Returns `{"task": null, "status": "empty"}` when the queue is drained. Prefer this over `/task/claim` — see Queue health. |
| `/task/complete` | POST | Complete a task |
| `/mailbox` | GET | Get durable mailbox for an agent |
| `/memory` | GET | Query agent memory |
| `/status` | GET | Health check |
| `/agents` | GET | List agents (auth required) |
| `/health/queue` | GET | Backlog report: `pending`, `claimed`, `by_agent`, `oldest_age_s`, `stalled` |
| `/.well-known/agent.json` | GET | A2A Agent Card — fleet discovery (spec 1.0.0 shape) |

## Queue health

`/health/queue` exists because the backlog went unnoticed for 22 hours. Thirteen
`tools`-channel tasks were queued to `hermes` and never claimed — nothing surfaced the
depth, and `/task/claim` needs an explicit `task_id`, so a worker that never got to the
"which task do I take" decision left them stuck indefinitely.

```bash
curl -s http://127.0.0.1:20129/health/queue
# {"pending":13,"oldest_age_s":79118.3,"claimed":0,
#  "by_agent":[{"agent":"hermes","pending":13,"oldest_age_s":79118.3}],
#  "stalled":true}
```

`stalled` flips when the oldest pending task exceeds `STALL_SECONDS` (900s) — long enough
that a worker mid-job doesn't trip it. Alert on `stalled`, not on raw depth.

Draining is now one call: a worker that can't poll should POST `/task/claim-next`, which
picks the oldest task for it atomically instead of leaving the choice to the worker.

## Integration with 9router

Your 9router is at `127.0.0.1:20128` with `inkling:free` model. Note its speech-to-text route is
not usable — see `collective.md` for the working local ASR path.

## Notes

- The broker uses SQLite at `C:/Users/Thabang/symbiont/a2a.db`
- All agents need auth tokens (format: `Bearer <agent_name>:<token>`)
- `/status` does **not** check auth — anything listening on the port can read broker health.
  `/messages`, `/mailbox`, `/memory`, `/tasks` and `/agents` **do** check auth and answer
  `{"error": "auth required"}` without a `Bearer <agent>:<token>` header. Loopback-only binding
  is still the only thing keeping the remaining unauthenticated surface contained.
