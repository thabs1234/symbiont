#!/usr/bin/env python3
"""A2A Broker v2 - Agent-to-Agent message broker with SQLite persistence"""
import re, sqlite3, json, hashlib, secrets, time, os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import threading

DB_PATH = r"C:/Users/Thabang/symbiont/a2a.db"
# A pending task older than this is treated as stalled. 15 min is long enough that a
# worker mid-job (claude's scrape_build runs take minutes) does not trip it.
STALL_SECONDS = 900

# Routes reachable without a token: cross-agent discovery plus monitoring.
# Everything else is gated by require_auth().
PUBLIC_PATHS = {"/.well-known/agent.json", "/health/queue", "/status"}

def _connect():
    """Every broker connection goes through here.

    ponytail: timeout=30 only. Concurrent workers were hitting the default 5s and
    losing claims; upgrade path is a per-route timeout if any endpoint needs one.
    """
    return sqlite3.connect(DB_PATH, timeout=30)


def init_db():
    conn = _connect()
    # WAL is persistent in the file header, so one call here is enough for every
    # later connection; readers/writers no longer block each other across the
    # claim/complete round trip. Readers opened with mode=ro keep working.
    c = conn.cursor()
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("""CREATE TABLE IF NOT EXISTS agents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        token TEXT,
        capabilities TEXT,
        created_at REAL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender TEXT,
        recipient TEXT,
        content TEXT,
        channel TEXT,
        timestamp REAL,
        read_by TEXT,
        metadata TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel TEXT,
        from_agent TEXT,
        to_agent TEXT,
        content TEXT,
        status TEXT DEFAULT 'pending',
        claimed_by TEXT,
        created_at REAL,
        completed_at REAL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS tools (
        name TEXT PRIMARY KEY,
        owner TEXT,
        description TEXT,
        command TEXT,
        created_at REAL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent TEXT,
        key TEXT,
        value TEXT,
        created_at REAL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS mailbox (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent TEXT,
        message_id TEXT,
        content TEXT,
        delivered_at REAL
    )""")
    # /task/claim sets claimed_at, but the original schema never had the column.
    # CREATE TABLE IF NOT EXISTS won't add it to an existing DB, so migrate.
    cols = {r[1] for r in c.execute("PRAGMA table_info(tasks)")}
    if "claimed_at" not in cols:
        c.execute("ALTER TABLE tasks ADD COLUMN claimed_at REAL")
    # /task/complete stores the worker's answer, which the original schema dropped.
    if "result" not in cols:
        c.execute("ALTER TABLE tasks ADD COLUMN result TEXT")
    conn.commit()
    conn.close()

init_db()

class A2AHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Silent logging

    def send_json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def registration_key_ok(self, supplied):
        """Bootstrap secret gates /register. ponytail: a single shared key in a
        local env file; swap for per-device auth when a second untrusted host
        ever needs its own identity."""
        expected = os.environ.get("A2A_REGISTRATION_KEY", "")
        if not expected:
            return True  # unset = no bootstrap gate (first-run local use)
        return secrets.compare_digest(str(supplied or ""), expected)

    def whoami(self):
        """Return the authenticated agent name, or None if the bearer is missing/invalid."""
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or ":" not in auth:
            return None
        agent, token = auth.replace("Bearer ", "").split(":", 1)
        conn = _connect()
        ok = conn.execute("SELECT name FROM agents WHERE name = ? AND token = ?", (agent, token)).fetchone()
        conn.close()
        return agent if ok else None


    def require_auth(self, path):
        """401 unless the path is public or the bearer token is valid.

        Public routes stay open for monitoring and cross-agent discovery:
        the agent card, /health/queue and /status. Everything else needs a
        valid Bearer <agent>:<token>.
        """
        if path in PUBLIC_PATHS:
            return True
        if self.whoami():
            return True
        self.send_json(401, {"error": "auth required"})
        return False

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = dict(p.split("=") for p in parsed.query.split("&") if "=" in p) if parsed.query else {}

        if not self.require_auth(path):
            return

        if path == "/.well-known/agent.json":
            self.send_json(200, {
                "name": "symbiosis-broker",
                "description": "Agent-to-Agent broker for the local symbiosis fleet (hermes, claude).",
                "version": "2.0",
                "url": "http://127.0.0.1:20129/",
                "preferredTransport": "JSONRPC",
                "capabilities": {"streaming": False, "pushNotifications": False,
                                 "stateTransitionHistory": True},
                "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer",
                                                   "description": "Bearer <agent>:<token>"}},
                "skills": [
                    {"id": "send", "name": "send", "description": "Deliver a message to another agent."},
                    {"id": "task", "name": "task", "description": "Queue work for another agent."},
                    {"id": "tool", "name": "tool", "description": "Register or delegate to a named tool."},
                ],
            })
        elif path == "/health/queue":
            # Backlog went unnoticed for days because nothing surfaced it. Anything
            # reading this should alert when `stalled` is true.
            conn = _connect()
            c = conn.cursor()
            rows = c.execute("""SELECT to_agent, COUNT(*), MIN(created_at)
                                FROM tasks WHERE status = 'pending' GROUP BY to_agent""").fetchall()
            claimed = c.execute("SELECT COUNT(*) FROM tasks WHERE status = 'claimed'").fetchone()[0]
            conn.close()
            now = time.time()
            q = {"pending": 0, "oldest_age_s": 0, "claimed": claimed, "by_agent": [], "stalled": False}
            for agent, n, oldest in rows:
                age = round(now - oldest, 1) if oldest else 0
                q["by_agent"].append({"agent": agent, "pending": n, "oldest_age_s": age})
                q["pending"] += n
                q["oldest_age_s"] = max(q["oldest_age_s"], age)
            q["stalled"] = q["oldest_age_s"] > STALL_SECONDS
            self.send_json(200, q)
        elif path == "/status":
            self.send_json(200, {"status": "ok", "broker": "a2a-broker-v2", "uptime": time.time()})
        elif path == "/channels":
            conn = _connect()
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='channels'")
            channels = [r[0] for r in c.fetchall()]
            conn.close()
            self.send_json(200, {"channels": channels})
        elif path == "/messages":
            agent = params.get("agent")
            unread = params.get("unread", "false").lower() == "true"
            channel = params.get("channel")
            
            conn = _connect()
            c = conn.cursor()
            where = ["recipient = ?", "read_by IS NULL"] if unread else ["recipient = ?"]
            args = [agent]
            if channel:
                where.append("channel = ?")
                args.append(channel)
            c.execute(f"SELECT id, sender, content, channel, timestamp FROM messages WHERE {' AND '.join(where)}", args)
            msgs = [{"id": r[0], "from": r[1], "content": r[2], "channel": r[3], "timestamp": r[4]} for r in c.fetchall()]
            conn.close()
            self.send_json(200, {"messages": msgs})
        elif path == "/mailbox":
            agent = params.get("agent")
            conn = _connect()
            c = conn.cursor()
            c.execute("SELECT message_id, content, delivered_at FROM mailbox WHERE agent = ?", (agent,))
            msgs = [{"id": r[0], "content": r[1], "delivered_at": r[2]} for r in c.fetchall()]
            conn.close()
            self.send_json(200, {"mailbox": msgs})
        elif path == "/memory":
            agent = params.get("agent")
            search = params.get("search")
            conn = _connect()
            c = conn.cursor()
            if search:
                c.execute("SELECT key, value FROM memory WHERE agent = ? AND (key LIKE ? OR value LIKE ?)", 
                         (agent, f"%{search}%", f"%{search}%"))
            else:
                c.execute("SELECT key, value FROM memory WHERE agent = ?", (agent,))
            mem = {r[0]: r[1] for r in c.fetchall()}
            conn.close()
            self.send_json(200, {"memory": mem})
        elif path == "/tasks":
            conn = _connect()
            c = conn.cursor()
            c.execute("SELECT id, channel, from_agent, to_agent, content, status, claimed_by, result FROM tasks")
            tasks = [dict(zip(["id","channel","from_agent","to_agent","content","status","claimed_by","result"], r)) for r in c.fetchall()]
            conn.close()
            self.send_json(200, {"tasks": tasks})
        elif path == "/tools":
            conn = _connect()
            c = conn.cursor()
            c.execute("SELECT name, owner, description FROM tools ORDER BY name")
            tools = [{"name": r[0], "owner": r[1], "description": r[2]} for r in c.fetchall()]
            conn.close()
            self.send_json(200, {"tools": tools})
        elif path == "/agents":
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                self.send_json(401, {"error": "auth required"})
                return
            conn = _connect()
            c = conn.cursor()
            c.execute("SELECT name, capabilities FROM agents")
            agents = [{"name": r[0], "capabilities": json.loads(r[1])} for r in c.fetchall()]
            conn.close()
            self.send_json(200, {"agents": agents})
        else:
            self.send_json(404, {"error": "not found"})
    
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode() if content_length > 0 else "{}"
        try:
            data = json.loads(body)
        except:
            data = {}
        
        parsed = urlparse(self.path)
        path = parsed.path

        if not self.require_auth(path):
            return
        auth = self.headers.get("Authorization", "")
        
        if path == "/register":
            name = data.get("name")
            if not name:
                self.send_json(400, {"error": "name required"})
                return

            # Re-registering an existing name used to hand the caller that agent's
            # live token, so any unauthenticated POST could impersonate anyone.
            # Only a bootstrap secret may mint a new identity, and a name that
            # already exists is never disclosed.
            if not self.registration_key_ok(data.get("registration_key")):
                self.send_json(403, {"error": "registration key required"})
                return

            token = secrets.token_hex(32)
            conn = _connect()
            c = conn.cursor()
            if c.execute("SELECT 1 FROM agents WHERE name = ?", (name,)).fetchone():
                conn.close()
                self.send_json(409, {"error": "name already registered"})
                return
            c.execute("INSERT INTO agents (name, token, capabilities, created_at) VALUES (?,?,?,?)",
                     (name, token, json.dumps(data.get("capabilities", [])), time.time()))
            conn.commit()
            conn.close()

            self.send_json(200, {"token": token, "message": "registered successfully"})
        
        elif path == "/send":
            if not auth.startswith("Bearer "):
                self.send_json(401, {"error": "auth required"})
                return
            
            sender, token = auth.replace("Bearer ", "").split(":", 1)
            
            conn = _connect()
            c = conn.cursor()
            c.execute("SELECT name FROM agents WHERE name = ? AND token = ?", (sender, token))
            if not c.fetchone():
                conn.close()
                self.send_json(403, {"error": "invalid credentials"})
                return
            
            recipient = data.get("to")
            content = data.get("content")
            if not recipient or not content:
                conn.close()
                self.send_json(400, {"error": "to and content required"})
                return
            
            c.execute("INSERT INTO messages (sender, recipient, content, channel, timestamp) VALUES (?,?,?,?,?)",
                     (sender, recipient, content, data.get("channel", "general"), time.time()))
            conn.commit()
            msg_id = c.lastrowid
            conn.close()
            
            self.send_json(200, {"message_id": msg_id, "status": "sent"})
        
        elif path == "/read":
            if not auth.startswith("Bearer "):
                self.send_json(401, {"error": "auth required"})
                return
            
            agent, token = auth.replace("Bearer ", "").split(":", 1)
            msg_ids = data.get("message_ids", [])
            
            conn = _connect()
            c = conn.cursor()
            c.execute("SELECT name FROM agents WHERE name = ? AND token = ?", (agent, token))
            if not c.fetchone():
                conn.close()
                self.send_json(403, {"error": "invalid credentials"})
                return
            
            for mid in msg_ids:
                c.execute("UPDATE messages SET read_by = ? WHERE id = ?", (agent, mid))
            conn.commit()
            conn.close()
            self.send_json(200, {"status": "marked read"})
        
        elif path == "/task":
            if not auth.startswith("Bearer "):
                self.send_json(401, {"error": "auth required"})
                return
            
            agent, token = auth.replace("Bearer ", "").split(":", 1)
            conn = _connect()
            c = conn.cursor()
            c.execute("SELECT name FROM agents WHERE name = ? AND token = ?", (agent, token))
            if not c.fetchone():
                conn.close()
                self.send_json(403, {"error": "invalid credentials"})
                return
            
            c.execute("INSERT INTO tasks (channel, from_agent, to_agent, content, created_at) VALUES (?,?,?,?,?)",
                     (data.get("channel", "general"), agent, data.get("to"), data.get("content"), time.time()))
            conn.commit()
            task_id = c.lastrowid
            conn.close()
            self.send_json(200, {"task_id": task_id, "status": "created"})
        
        elif path == "/task/claim":
            if not auth.startswith("Bearer "):
                self.send_json(401, {"error": "auth required"})
                return
            
            agent, token = auth.replace("Bearer ", "").split(":", 1)
            task_id = data.get("task_id")
            
            conn = _connect()
            c = conn.cursor()
            c.execute("SELECT name FROM agents WHERE name = ? AND token = ?", (agent, token))
            if not c.fetchone():
                conn.close()
                self.send_json(403, {"error": "invalid credentials"})
                return
            
            c.execute("UPDATE tasks SET status = 'claimed', claimed_by = ?, claimed_at = ? WHERE id = ? AND status = 'pending'",
                     (agent, time.time(), task_id))
            if c.rowcount == 0:
                conn.close()
                self.send_json(409, {"error": "task not available"})
                return
            
            c.execute("SELECT to_agent, content FROM tasks WHERE id = ?", (task_id,))
            task = c.fetchone()
            conn.commit()
            conn.close()
            
            self.send_json(200, {"task_id": task_id, "assigned_to": agent, "task": {"to": task[0], "content": task[1]}})
        
        elif path == "/task/claim-next":
            # The 13 stalled `tools` tasks all sat unclaimed because /task/claim needs an
            # explicit task_id, so the worker had to poll /tasks and choose. A worker that
            # never got to that choice left the queue stuck forever. This picks atomically.
            agent = self.whoami()
            if not agent:
                self.send_json(401, {"error": "invalid credentials"})
                return
            conn = _connect()
            c = conn.cursor()
            row = c.execute("""SELECT id FROM tasks
                               WHERE status = 'pending' AND (to_agent = ? OR to_agent IS NULL)
                               ORDER BY created_at LIMIT 1""", (agent,)).fetchone()
            if not row:
                conn.close()
                self.send_json(200, {"task": None, "status": "empty"})
                return
            task_id = row[0]
            c.execute("UPDATE tasks SET status = 'claimed', claimed_by = ?, claimed_at = ? "
                      "WHERE id = ? AND status = 'pending'", (agent, time.time(), task_id))
            if c.rowcount == 0:
                conn.close()
                self.send_json(409, {"error": "task not available"})
                return
            t = c.execute("SELECT to_agent, content, channel, from_agent FROM tasks WHERE id = ?",
                          (task_id,)).fetchone()
            conn.commit()
            conn.close()
            self.send_json(200, {"task_id": task_id, "assigned_to": agent,
                                 "task": {"to": t[0], "content": t[1], "channel": t[2], "from": t[3]}})
        elif path == "/task/complete":
            if not auth.startswith("Bearer "):
                self.send_json(401, {"error": "auth required"})
                return

            agent, token = auth.replace("Bearer ", "").split(":", 1)
            task_id = data.get("task_id")
            conn = _connect()
            c = conn.cursor()
            c.execute("SELECT name FROM agents WHERE name = ? AND token = ?", (agent, token))
            if not c.fetchone():
                conn.close()
                self.send_json(403, {"error": "invalid credentials"})
                return

            # Only the agent that won the claim may file the result.
            c.execute("UPDATE tasks SET status = 'completed', completed_at = ?, result = ? "
                      "WHERE id = ? AND claimed_by = ?",
                      (time.time(), data.get("result"), task_id, agent))
            if c.rowcount == 0:
                conn.close()
                self.send_json(409, {"error": "not claimed by you or already completed"})
                return
            c.execute("SELECT channel, content, result FROM tasks WHERE id = ?", (task_id,))
            row = c.fetchone()
            conn.commit()

            # Automatic return trip: work finished in a `review` channel comes back
            # to claude for the final pass. This is the routing that was missing.
            # Never route when the completer IS claude -- claude is the final pass,
            # so a review of a review is an infinite ping-pong, not a second pass.
            review_task = None
            if row and row[0] == "review" and agent != "claude":
                brief = data.get("review_request") or f"Final pass on task {task_id}:\n{row[2] or row[1]}"
                c.execute("INSERT INTO tasks (channel, from_agent, to_agent, content, created_at) VALUES (?,?,?,?,?)",
                          ("review", agent, "claude", brief, time.time()))
                conn.commit()
                review_task = c.lastrowid
            conn.close()

            out = {"task_id": task_id, "status": "completed"}
            if review_task:
                out["review_task_id"] = review_task
            self.send_json(200, out)
        elif path == "/tool":
            agent = self.whoami()
            if not agent:
                self.send_json(401, {"error": "invalid credentials"})
                return
            name = data.get("name")
            if not name:
                self.send_json(400, {"error": "name required"})
                return
            conn = _connect()
            conn.execute("REPLACE INTO tools (name, owner, description, command, created_at) VALUES (?,?,?,?,?)",
                         (name, agent, data.get("description", ""), data.get("command", ""), time.time()))
            conn.commit()
            conn.close()
            self.send_json(200, {"tool": name, "owner": agent, "status": "registered"})

        elif path == "/tools/invoke":
            # Routing only. The broker never shells out -- that would make it an RCE
            # endpoint behind a bearer token. If you own the tool you run it yourself;
            # if you don't, it becomes a task for the agent that does.
            agent = self.whoami()
            if not agent:
                self.send_json(401, {"error": "invalid credentials"})
                return
            name = data.get("tool")
            args = data.get("args", "")
            conn = _connect()
            row = conn.execute("SELECT owner, description, command FROM tools WHERE name = ?", (name,)).fetchone()
            if not row:
                conn.close()
                self.send_json(404, {"error": f"no such tool: {name}"})
                return
            owner, description, command = row
            if owner == agent:
                conn.close()
                self.send_json(200, {"tool": name, "local": True, "command": command,
                                     "args": args, "description": description})
                return
            content = f"[tool:{name}] {description}\ncommand: {command} {args}".strip()
            c = conn.cursor()
            c.execute("INSERT INTO tasks (channel, from_agent, to_agent, content, created_at) VALUES (?,?,?,?,?)",
                      (data.get("channel", "tools"), agent, owner, content, time.time()))
            conn.commit()
            task_id = c.lastrowid
            conn.close()
            self.send_json(200, {"tool": name, "delegated": True, "owner": owner, "task_id": task_id})

        elif path == "/channel":
            conn = _connect()
            c = conn.cursor()
            name = data.get("name")
            if name:
                try:
                    # Identifiers cannot be parameterised, so allowlist instead of stripping.
                    safe = re.fullmatch(r"[A-Za-z0-9_]{1,32}", name or "")
                    if not safe:
                        conn.close()
                        self.send_json(400, {"error": "invalid channel name"})
                        return
                    c.execute("CREATE TABLE IF NOT EXISTS channels_%s (id INTEGER PRIMARY KEY)" % safe.group(0))
                    conn.commit()
                    self.send_json(200, {"channel": name, "status": "created"})
                except:
                    conn.close()
                    self.send_json(400, {"error": "invalid channel name"})
            else:
                self.send_json(400, {"error": "name required"})
        
        elif path == "/memory/store":
            if not auth.startswith("Bearer "):
                self.send_json(401, {"error": "auth required"})
                return
            
            agent, token = auth.replace("Bearer ", "").split(":", 1)
            key = data.get("key")
            value = data.get("value")
            
            conn = _connect()
            c = conn.cursor()
            c.execute("SELECT name FROM agents WHERE name = ? AND token = ?", (agent, token))
            if not c.fetchone():
                conn.close()
                self.send_json(403, {"error": "invalid credentials"})
                return
            
            c.execute("REPLACE INTO memory (agent, key, value, created_at) VALUES (?,?,?,?)",
                     (agent, key, value, time.time()))
            conn.commit()
            conn.close()
            self.send_json(200, {"status": "stored"})
        
        elif path == "/mailbox/send":
            if not auth.startswith("Bearer "):
                self.send_json(401, {"error": "auth required"})
                return
            
            sender, token = auth.replace("Bearer ", "").split(":", 1)
            recipient = data.get("agent")
            content = data.get("content")
            
            conn = _connect()
            c = conn.cursor()
            c.execute("SELECT name FROM agents WHERE name = ? AND token = ?", (sender, token))
            if not c.fetchone():
                conn.close()
                self.send_json(403, {"error": "invalid credentials"})
                return
            
            msg_id = f"msg_{int(time.time()*1000000)}"
            c.execute("INSERT INTO mailbox (agent, message_id, content, delivered_at) VALUES (?,?,?,?)",
                     (recipient, msg_id, content, time.time()))
            conn.commit()
            conn.close()
            self.send_json(200, {"message_id": msg_id, "status": "queued"})
        
        elif path == "/human":
            self.send_json(200, {"auto_pause": False, "last_human": time.time()})
        
        else:
            self.send_json(404, {"error": "not found"})

def run_server(port=20129):
    server = HTTPServer(("127.0.0.1", port), A2AHandler)
    print(f"A2A Broker v2 running on http://127.0.0.1:{port}")
    server.serve_forever()

if __name__ == "__main__":
    run_server()
