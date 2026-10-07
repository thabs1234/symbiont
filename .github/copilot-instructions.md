# Copilot instructions — symbiont

A2A agent-to-agent broker (SQLite) plus Telegram bridge, in plain Python.

## Layout
- `a2a_broker.py` — ThreadingHTTPServer broker, SQLite persistence, token-gated routes
- `a2a_client.py`, `a2a_remote.py`, `a2a_session_start.py` — client side
- `telegram_bridge.py` — Telegram transport
- `build.py` — build/scraping pipeline (yt-dlp, faster-whisper, sqlite)
- `collective.md`, `goals.md` — shared memory read by every agent in the mesh
- `a2a.db` — broker state; gitignored, so never treat it as source of truth
- Scratch files prefixed `_` (`_batch*.py`, `_*.txt`) are throwaway runs. Do not
  refactor them, do not promote them to tracked code without being asked.

## Runtime
- Python, no packaging manifest and no venv in-tree. Scripts run with bare
  `python <file>.py`; do not add `pyproject.toml`, `requirements.txt` or a
  `requirements.txt`-as-code habit unless asked.
- Third-party deps already present: `yt_dlp`, `faster_whisper`, `numpy`, `httpx`-free
  stdlib `http.server` for the broker. Prefer those over adding anything new.
- Paths are absolute `C:/Users/Thabang/...` Windows forward-slash strings, as in
  `DB_PATH`. Match that, not `pathlib` or relative paths.

## Broker rules (security-sensitive)
- `PUBLIC_PATHS` is the complete unauthenticated allowlist. Anything not listed is
  gated by `require_auth()`. New routes default to authenticated — do not add to
  `PUBLIC_PATHS` without an explicit reason.
- Tokens come from `.agent_tokens.json` (gitignored). Never log them, echo them into
  error messages, or copy them into a new file.
- Use the existing `_connect()` helper for every DB connection so the 30s timeout
  stays uniform. Do not open `sqlite3.connect(DB_PATH)` inline.
- Keep the `ponytail:` comment convention where a deliberate ceiling exists; extend
  the comment rather than silently replacing it.

## Verification
There is no test suite. For a broker change, the narrow check is a live probe:

```
curl -sS -m 5 http://127.0.0.1:20129/health/queue
curl -sS -m 5 http://127.0.0.1:20129/status
```

Both are public routes. A `python -c "import ast,ast.parse..."` syntax check does
not prove the broker starts — say plainly what you ran and what stayed unverified.
Report the real output; never describe an endpoint as working without hitting it.
