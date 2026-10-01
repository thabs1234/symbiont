# collective.md — shared agent state

> A2A broker: `127.0.0.1:20129` (SQLite `a2a.db`). Agents read each other's messages here only via
> the broker; this file is the durable, human-readable layer both agents can poll.

## Fleet (as of 2026-09-29)

| Agent | Registered | Capabilities | Reaches the broker via |
|---|---|---|---|
| `hermes` | yes | converse, code, messaging, memory | gateway + `hermes` CLI |
| `claude` | yes | converse, code, review, memory | Claude Code CLI |
| `telegram` | on bridge start | messaging | `telegram_bridge.js` |
| `chatgpt` | **retired** | — | ChatGPT Desktop uninstalled 2026-09-29 |

Tokens live in `.agent_tokens.json` (gitignored). Re-registering an existing name is idempotent —
the broker returns the existing token rather than minting a new one.

## Current goal

Symbiosis wired around **claude + hermes**, one shared objective. Neither agent needs to be running
continuously: both register on demand and read the broker when started.

## Session log

| Date | Agent | Change |
|---|---|---|
| 2026-09-29 | claude | Rebuilt fleet after ChatGPT Desktop uninstall. Registered `hermes` + `claude`, fanned Telegram inbound out to both, created this file and `goals.md`. |

## ASR path (established this session)

Local transcription works via `uv run --python 3.12 --with faster-whisper`, decoding audio with
stdlib `wave` into a numpy float32 array and passing the array to `transcribe()`. Do not pass a
file path — `faster_whisper.audio.decode_audio` raises
`TypeError: open() got an unexpected keyword argument 'metadata_errors'` from a PyAV version clash.

Rejected routes, don't retry them:
- 9router STT (`nvidia/parakeet-ctc-1.1b-asr`, `cl/openai/gpt-audio-mini`) → `provider does not support STT`
- 9router `whisper-1` / `openai/whisper-large-v3` → no openai credentials on the router
- hermes venv → Python 3.14 interpreter against 3.12 numpy wheels; `numpy._core` import fails
