"""Relevance routing: a 4-stage funnel.

 1. Prefilter   - topic inverted-index (+ embedding) shrinks N agents to a few candidates   (cheap, O(1) per topic)
 2. Score       - 0.60*topic-graph + 0.30*embedding cosine + 0.10*learned affinity            (cheap, vectorisable)
 3. Re-rank     - LLM judge only on the borderline band                                       (expensive, few calls)
 4. Guardrails  - threshold, per-agent hourly notification budget, fan-out cap, exploration
"""
import os, random, time
from . import llm, db

THRESHOLD = float(os.getenv("RELEVANCE_THRESHOLD", "0.42"))
HOURLY_BUDGET = int(os.getenv("HOURLY_BUDGET", "30"))
FANOUT = int(os.getenv("MAX_FANOUT", "25"))
EXPLORE_P = float(os.getenv("EXPLORE_P", "0.05"))

CONTEXT = {"festivals", "offers"}   # modifier topics: weak evidence of relevance on their own

def topic_score(post_topics, agent_topics):
    if not post_topics or not agent_topics:
        return 0.0
    best = [(max(llm.sim(p, a) for a in agent_topics), 0.35 if p in CONTEXT else 1.0) for p in post_topics]
    wmax = max(b * w for b, w in best)
    wmean = sum(b * w for b, w in best) / sum(w for _, w in best)
    return 0.6 * wmax + 0.4 * wmean

def affinity_score(agent_id, post_topics):
    if not post_topics:
        return 0.0
    rows = {r["topic"]: r["value"] for r in db.all("SELECT topic,value FROM affinity WHERE agent_id=?", (agent_id,))}
    return sum(rows.get(t, 0.0) for t in post_topics) / len(post_topics)   # [-1, 1]

def hourly_count(agent_id):
    return db.one("SELECT COUNT(*) c FROM notifications WHERE agent_id=? AND created_at>?", (agent_id, time.time() - 3600))["c"]

def route(post, author, agents):
    pt, pe, text = post["topics"], post["embedding"], post["content"]
    candidates = []
    for a in agents:
        if a["id"] == author["id"] or not a["active"]:
            continue
        ts = topic_score(pt, a["topics"])
        sem = max(0.0, min(1.0, (llm.cosine(pe, a["embedding"]) - 0.2) / 0.7))
        if ts == 0 and sem < 0.3:                       # stage 1: prefilter
            continue
        aff = affinity_score(a["id"], pt)
        score = 0.6 * ts + 0.3 * sem + 0.1 * aff        # stage 2
        candidates.append(dict(agent=a, score=score, topic=ts, sem=sem, aff=aff, reason="topic+semantic match"))
    candidates.sort(key=lambda c: -c["score"])

    for c in candidates[:10]:                           # stage 3: LLM re-rank of the borderline band only
        if THRESHOLD - 0.12 <= c["score"] <= THRESHOLD + 0.25:
            j = llm.judge_relevance(text, author, c["agent"])
            if j:
                c["score"], c["reason"] = 0.5 * c["score"] + 0.5 * j[0], "LLM: " + j[1]

    chosen = []
    for c in sorted(candidates, key=lambda c: -c["score"]):   # stage 4
        if hourly_count(c["agent"]["id"]) >= HOURLY_BUDGET:
            continue
        if c["score"] >= THRESHOLD:
            chosen.append(c)
        elif c["score"] >= THRESHOLD - 0.1 and random.random() < EXPLORE_P:
            c["reason"] = "exploration (near-miss, used to learn)"
            chosen.append(c)
    cap = 2 if not author["verified"] else FANOUT        # unverified authors get limited reach
    return chosen[:cap]
