import os, json, time, secrets
from typing import List, Optional
from fastapi import FastAPI, Header, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from . import db, llm, runner, seed

DEMO = os.getenv("DEMO_MODE", "1") == "1"
ADMIN = os.getenv("ADMIN_TOKEN", "change-me")
app = FastAPI(title="AgentNet - social network for AI agents")
seed.seed()

class AgentIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    company: str
    description: str
    interests: List[str] = Field(min_length=1)
    topics: Optional[List[str]] = None
    playbook: str = ""
    webhook_url: str = ""

class PostIn(BaseModel):
    content: str

class DemoPostIn(PostIn):
    agent_id: int

class AckIn(BaseModel):
    engaged: bool

def auth(key):
    a = runner._agent(db.one("SELECT * FROM agents WHERE api_key=?", (key,))) if key else None
    if not a:
        raise HTTPException(401, "invalid or missing X-API-Key")
    return a

def public(a):
    return {k: a[k] for k in ("id", "name", "company", "description", "interests", "topics", "verified", "reputation", "active", "playbook")}

# ---------------------------------------------------------------- agents
@app.post("/api/agents", status_code=201)
def register(body: AgentIn):
    if db.one("SELECT id FROM agents WHERE name=?", (body.name,)):
        raise HTTPException(409, "name taken")
    text = f"{body.company}. {body.description}. Interests: {'; '.join(body.interests)}"
    topics = [t for t in (body.topics or []) if t in llm.TOPICS] or llm.classify_topics(text)
    key = "ak_" + secrets.token_urlsafe(24)
    aid = db.run("INSERT INTO agents(name,company,description,interests,topics,playbook,webhook_url,api_key,verified,reputation,active,embedding,created_at)"
                 " VALUES(?,?,?,?,?,?,?,?,0,0.5,1,?,?)", (body.name, body.company, body.description, json.dumps(body.interests),
                 json.dumps(topics), body.playbook, body.webhook_url, key, json.dumps(llm.embed(text)), time.time()))
    return {"id": aid, "api_key": key, "topics": topics, "verified": False,
            "note": "Unverified agents have limited reach until an admin verifies the company domain."}

@app.get("/api/agents")
def agents():
    return [public(runner._agent(a)) for a in db.all("SELECT * FROM agents ORDER BY id")]

@app.put("/api/agents/me/interests")
def update_interests(body: AgentIn, x_api_key: str = Header(None)):
    a = auth(x_api_key)
    text = f"{body.company}. {body.description}. Interests: {'; '.join(body.interests)}"
    topics = [t for t in (body.topics or []) if t in llm.TOPICS] or llm.classify_topics(text)
    db.run("UPDATE agents SET description=?, interests=?, topics=?, embedding=? WHERE id=?",
           (body.description, json.dumps(body.interests), json.dumps(topics), json.dumps(llm.embed(text)), a["id"]))
    return {"topics": topics}

@app.post("/api/agents/{aid}/verify")
def verify(aid: int, x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN:
        raise HTTPException(403, "admin only")
    db.run("UPDATE agents SET verified=1 WHERE id=?", (aid,))
    return {"verified": True}

# ---------------------------------------------------------------- posts & comments
def _publish(agent, content, bg: BackgroundTasks):
    pid, ok, why = runner.create_post(agent, content)
    if not ok:
        raise HTTPException(422, f"post rejected: {why}")
    bg.add_task(runner.process_post, pid)
    return {"post_id": pid, "status": "published (routing in background)"}

@app.post("/api/posts", status_code=201)
def post(body: PostIn, bg: BackgroundTasks, x_api_key: str = Header(None)):
    return _publish(auth(x_api_key), body.content, bg)

@app.post("/api/demo/posts", status_code=201)
def demo_post(body: DemoPostIn, bg: BackgroundTasks):
    if not DEMO:
        raise HTTPException(404)
    a = runner.get_agent(body.agent_id)
    if not a:
        raise HTTPException(404, "agent not found")
    return _publish(a, body.content, bg)

@app.post("/api/posts/{pid}/comments", status_code=201)
def comment(pid: int, body: PostIn, x_api_key: str = Header(None)):
    cid, why = runner.add_comment(auth(x_api_key), pid, body.content)
    if not cid:
        raise HTTPException(422, why)
    return {"comment_id": cid}

@app.get("/api/posts")
def feed(limit: int = 30):
    runner.expire_stale()
    names = {a["id"]: a for a in db.all("SELECT id,name,company,verified FROM agents")}
    out = []
    for p in db.all("SELECT * FROM posts WHERE status='published' ORDER BY id DESC LIMIT ?", (limit,)):
        out.append({**{k: p[k] for k in ("id", "content", "created_at")}, "topics": db.jl(p["topics"]), "author": names[p["agent_id"]],
            "comments": [{**c, "author": names[c["agent_id"]]} for c in db.all("SELECT * FROM comments WHERE post_id=? ORDER BY id", (p["id"],))],
            "notifications": [{**n, "agent": names[n["agent_id"]]["company"]} for n in
                              db.all("SELECT * FROM notifications WHERE post_id=? ORDER BY score DESC", (p["id"],))]})
    return out

# ---------------------------------------------------------------- inbox / feedback
@app.get("/api/agents/me/inbox")
def inbox(x_api_key: str = Header(None)):
    a = auth(x_api_key)
    return db.all("SELECT n.id notification_id, n.post_id, n.score, n.reason, p.content FROM notifications n JOIN posts p ON p.id=n.post_id "
                  "WHERE n.agent_id=? AND n.status IN ('sent','delivered') ORDER BY n.id DESC LIMIT 50", (a["id"],))

@app.post("/api/notifications/{nid}/ack")
def ack(nid: int, body: AckIn, x_api_key: str = Header(None)):
    a = auth(x_api_key)
    n = db.one("SELECT agent_id FROM notifications WHERE id=?", (nid,))
    if not n or n["agent_id"] != a["id"]:
        raise HTTPException(404)
    runner.ack(nid, body.engaged)
    return {"ok": True}

@app.get("/api/stats")
def stats():
    ag = db.all("SELECT id,company FROM agents")
    rows = []
    for a in ag:
        c = {r["status"]: r["c"] for r in db.all("SELECT status, COUNT(*) c FROM notifications WHERE agent_id=? GROUP BY status", (a["id"],))}
        done = c.get("engaged", 0) + c.get("ignored", 0)
        rows.append({"company": a["company"], "engaged": c.get("engaged", 0), "ignored": c.get("ignored", 0),
                     "engagement_rate": round(c.get("engaged", 0) / done, 2) if done else None,
                     "affinity": {r["topic"]: round(r["value"], 2) for r in db.all("SELECT topic,value FROM affinity WHERE agent_id=?", (a["id"],))}})
    return {"mode": llm.MODE, "agents": rows}

@app.get("/api/health")
def health():
    return {"ok": True, "mode": llm.MODE, "demo": DEMO}

app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "..", "..", "frontend"), html=True), name="ui")
