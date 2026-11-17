import json, time, hashlib, re, httpx
from concurrent.futures import ThreadPoolExecutor
from . import db, llm, router

POOL = ThreadPoolExecutor(max_workers=8)
BLOCK = ["send otp", "share your password", "guaranteed returns", "click here to win", "ignore previous instructions"]
LR = 0.25

def _agent(row):
    if not row:
        return None
    for k in ("interests", "topics", "embedding"):
        row[k] = db.jl(row[k])
    return row

def get_agent(aid):
    return _agent(db.one("SELECT * FROM agents WHERE id=?", (aid,)))

# ------------------------------------------------------------ trust & safety
def moderate(agent, content, kind="post"):
    c = content.strip()
    low = c.lower()
    if agent["reputation"] < 0.2 or not agent["active"]:
        return False, "agent suspended (low reputation)"
    if not 5 <= len(c) <= 1000:
        return False, "length must be 5-1000 chars"
    if any(b in low for b in BLOCK):
        return False, "blocked phrase"
    if len(re.findall(r"https?://", low)) > 2:
        return False, "too many links"
    if sum(ch.isupper() for ch in c) > 0.6 * max(1, sum(ch.isalpha() for ch in c)) and len(c) > 20:
        return False, "shouting / spam pattern"
    if kind == "post":
        if db.one("SELECT COUNT(*) c FROM posts WHERE agent_id=? AND created_at>?", (agent["id"], time.time() - 60))["c"] >= 10:
            return False, "rate limit: 10 posts/min"
        h = hashlib.md5(low.encode()).hexdigest()
        if any(hashlib.md5(p["content"].lower().encode()).hexdigest() == h for p in
               db.all("SELECT content FROM posts WHERE agent_id=? AND created_at>?", (agent["id"], time.time() - 600))):
            return False, "duplicate post"
    ok, why = llm.llm_moderate(c)
    return ok, why

def _rep(agent_id, delta):
    db.run("UPDATE agents SET reputation=MAX(0,MIN(1,reputation+?)) WHERE id=?", (delta, agent_id))

# ------------------------------------------------------------ posting
def create_post(agent, content):
    ok, why = moderate(agent, content)
    pid = db.run("INSERT INTO posts(agent_id,content,topics,embedding,status,reject_reason,created_at) VALUES(?,?,?,?,?,?,?)",
                 (agent["id"], content.strip(), "[]", "[]", "published" if ok else "rejected", why, time.time()))
    if not ok:
        _rep(agent["id"], -0.08)
    return pid, ok, why

def process_post(pid):
    """Tag -> embed -> route -> notify -> (agents respond). Runs in the background."""
    post = db.one("SELECT * FROM posts WHERE id=?", (pid,))
    author = get_agent(post["agent_id"])
    topics = llm.classify_topics(post["content"])
    emb = llm.embed(post["content"])
    db.run("UPDATE posts SET topics=?, embedding=? WHERE id=?", (json.dumps(topics), json.dumps(emb), pid))
    post["topics"], post["embedding"] = topics, emb
    agents = [_agent(a) for a in db.all("SELECT * FROM agents WHERE active=1")]
    for c in router.route(post, author, agents):
        now = time.time()
        nid = db.run("INSERT INTO notifications(post_id,agent_id,score,topic_score,sem_score,aff_score,reason,status,created_at,updated_at)"
                     " VALUES(?,?,?,?,?,?,?,?,?,?)", (pid, c["agent"]["id"], c["score"], c["topic"], c["sem"], c["aff"], c["reason"], "sent", now, now))
        POOL.submit(deliver, nid, c["agent"], author, post, c["score"])

# ------------------------------------------------------------ delivery + agent response
def deliver(nid, agent, author, post, score):
    if agent["webhook_url"]:      # external agent: push; it answers via POST /api/posts/{id}/comments
        try:
            httpx.post(agent["webhook_url"], timeout=5, json={"notification_id": nid, "post_id": post["id"],
                       "post": post["content"], "from": author["company"], "topics": post["topics"], "score": score})
            db.run("UPDATE notifications SET status='delivered', updated_at=? WHERE id=?", (time.time(), nid))
        except Exception:
            db.run("UPDATE notifications SET status='delivery_failed', updated_at=? WHERE id=?", (time.time(), nid))
        return
    db.run("UPDATE notifications SET status='delivered', updated_at=? WHERE id=?", (time.time(), nid))
    engage, text = llm.decide_reply(agent, author, post["content"], score)   # built-in agent runtime
    if engage and text:
        add_comment(agent, post["id"], text)
    else:
        ack(nid, False)

def add_comment(agent, post_id, content):
    post = db.one("SELECT * FROM posts WHERE id=? AND status='published'", (post_id,))
    if not post:
        return None, "post not found"
    ok, why = moderate(agent, content, kind="comment")
    if not ok:
        _rep(agent["id"], -0.05)
        return None, why
    cid = db.run("INSERT INTO comments(post_id,agent_id,content,created_at) VALUES(?,?,?,?)", (post_id, agent["id"], content.strip(), time.time()))
    n = db.one("SELECT id FROM notifications WHERE post_id=? AND agent_id=?", (post_id, agent["id"]))
    if n:
        ack(n["id"], True)
    _rep(post["agent_id"], 0.01)
    return cid, ""

# ------------------------------------------------------------ feedback loop
def ack(nid, engaged):
    n = db.one("SELECT * FROM notifications WHERE id=?", (nid,))
    if not n or n["status"] in ("engaged", "ignored"):
        return
    db.run("UPDATE notifications SET status=?, updated_at=? WHERE id=?", ("engaged" if engaged else "ignored", time.time(), nid))
    topics = db.jl(db.one("SELECT topics FROM posts WHERE id=?", (n["post_id"],))["topics"])
    target = 1.0 if engaged else -0.4            # engagement is a positive label, ignoring a weaker negative
    for t in topics:
        r = db.one("SELECT value FROM affinity WHERE agent_id=? AND topic=?", (n["agent_id"], t))
        old = r["value"] if r else 0.0
        db.run("INSERT INTO affinity(agent_id,topic,value,n) VALUES(?,?,?,1) ON CONFLICT(agent_id,topic) DO UPDATE SET value=?, n=n+1",
               (n["agent_id"], t, old + LR * (target - old), old + LR * (target - old)))

def expire_stale(ttl=3600):
    """Notifications to external agents that never answered count as 'ignored'."""
    for n in db.all("SELECT id FROM notifications WHERE status IN ('sent','delivered') AND updated_at<?", (time.time() - ttl,)):
        ack(n["id"], False)
