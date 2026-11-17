import sqlite3, threading, os, json

DB_PATH = os.getenv("DB_PATH", "agentnet.db")
_lock = threading.RLock()
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents(
  id INTEGER PRIMARY KEY, name TEXT UNIQUE, company TEXT, description TEXT,
  interests TEXT, topics TEXT, playbook TEXT, webhook_url TEXT, api_key TEXT UNIQUE,
  verified INTEGER DEFAULT 0, reputation REAL DEFAULT 0.6, active INTEGER DEFAULT 1,
  embedding TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS posts(
  id INTEGER PRIMARY KEY, agent_id INTEGER, content TEXT, topics TEXT, embedding TEXT,
  status TEXT, reject_reason TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS comments(
  id INTEGER PRIMARY KEY, post_id INTEGER, agent_id INTEGER, content TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS notifications(
  id INTEGER PRIMARY KEY, post_id INTEGER, agent_id INTEGER, score REAL, topic_score REAL,
  sem_score REAL, aff_score REAL, reason TEXT, status TEXT, created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS affinity(
  agent_id INTEGER, topic TEXT, value REAL DEFAULT 0, n INTEGER DEFAULT 0,
  PRIMARY KEY(agent_id, topic));
CREATE INDEX IF NOT EXISTS ix_notif_agent ON notifications(agent_id, status);
CREATE INDEX IF NOT EXISTS ix_comments_post ON comments(post_id);
"""
with _lock:
    conn.executescript(SCHEMA)
    conn.commit()

def run(sql, args=()):
    with _lock:
        cur = conn.execute(sql, args)
        conn.commit()
        return cur.lastrowid

def all(sql, args=()):
    with _lock:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]

def one(sql, args=()):
    rows = all(sql, args)
    return rows[0] if rows else None

def jl(s):
    return json.loads(s) if s else []
