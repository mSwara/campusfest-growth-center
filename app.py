"""CampusFest Growth Center: Flask API + single-page UI.  Run:  python app.py   (http://localhost:5000)"""
import json
import os
import re
from datetime import datetime

from flask import Flask, jsonify, request, send_from_directory

import analytics as A
import chat
import etl
import model as M

app = Flask(__name__, static_folder="static", static_url_path="")
STATUSES = ("todo", "in_progress", "blocked", "done")
PRIORITIES = ("low", "medium", "high")
PLAN_STATUS = ("active", "paused", "stopped")


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_db():
    if not os.path.exists(etl.DB):
        etl.build()


def _d():
    d = request.args.get("as_of") or A.latest_date()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
        raise ValueError("as_of must be YYYY-MM-DD")
    info = A.event_info()
    return min(max(d, info["history_start"]), info["history_end"])


def err(msg, code=400):
    return jsonify(error=msg), code


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/api/meta")
def meta():
    c = A.conn()
    owners = [dict(r) for r in c.execute("select distinct owner_id, owner_name from campaigns order by owner_id")]
    camps = [dict(r) for r in c.execute("select campaign_id, campaign_name, channel from campaigns order by campaign_id")]
    c.close()
    return jsonify(event=A.event_info(), owners=owners, campaigns=camps, statuses=STATUSES, priorities=PRIORITIES,
                   chat_engine="gemini:" + chat.GEMINI_MODEL if chat.GEMINI_KEY else "offline-analyst",
                   presets=list(M.PRESETS))


@app.get("/api/state")
def state():
    d = _d()
    return jsonify(kpis=A.kpis(d), campaigns=A.campaigns_table(d), timeline=A.timeline(d), projection=A.projection(d),
                   insights=A.insights(d), funnel=A.rate_card(d))


# ------------------------------------------------------------- tasks
@app.get("/api/tasks")
def tasks_list():
    c = A.conn()
    rows = [dict(r) for r in c.execute("select * from tasks order by case status when 'done' then 1 else 0 end, due_date")]
    c.close()
    d = _d()
    for r in rows:
        r["overdue"] = bool(r["status"] != "done" and r["due_date"] and r["due_date"] < d)
    return jsonify(tasks=rows, as_of=d)


def _task_payload(p, partial=False):
    out = {}
    if "title" in p or not partial:
        t = (p.get("title") or "").strip()
        if not t:
            raise ValueError("title is required")
        out["title"] = t[:200]
    for k in ("campaign_id", "owner_id", "notes", "source"):
        if k in p:
            out[k] = p[k] or None if k in ("campaign_id", "owner_id") else (p[k] or "")
    if "due_date" in p:
        if p["due_date"] and not re.match(r"^\d{4}-\d{2}-\d{2}$", p["due_date"]):
            raise ValueError("due_date must be YYYY-MM-DD")
        out["due_date"] = p["due_date"] or None
    if "status" in p:
        if p["status"] not in STATUSES:
            raise ValueError("bad status")
        out["status"] = p["status"]
    if "priority" in p:
        if p["priority"] not in PRIORITIES:
            raise ValueError("bad priority")
        out["priority"] = p["priority"]
    return out


@app.post("/api/tasks")
def tasks_create():
    try:
        p = _task_payload(request.json or {})
    except ValueError as e:
        return err(str(e))
    p.setdefault("status", "todo")
    p.setdefault("priority", "medium")
    p["created_at"] = p["updated_at"] = now()
    c = A.conn()
    cur = c.execute(f"insert into tasks ({','.join(p)}) values ({','.join('?' * len(p))})", list(p.values()))
    c.commit()
    tid = cur.lastrowid
    c.close()
    A.bump()
    return jsonify(id=tid, ok=True)


@app.put("/api/tasks/<int:tid>")
def tasks_update(tid):
    try:
        p = _task_payload(request.json or {}, partial=True)
    except ValueError as e:
        return err(str(e))
    if not p:
        return err("nothing to update")
    p["updated_at"] = now()
    c = A.conn()
    c.execute(f"update tasks set {','.join(k + '=?' for k in p)} where id=?", list(p.values()) + [tid])
    c.commit()
    c.close()
    A.bump()
    return jsonify(ok=True)


@app.delete("/api/tasks/<int:tid>")
def tasks_delete(tid):
    c = A.conn()
    c.execute("delete from tasks where id=?", (tid,))
    c.commit()
    c.close()
    A.bump()
    return jsonify(ok=True)


# ------------------------------------------------------------- plan / decisions / data entry
@app.put("/api/plan/<cid>")
def plan_update(cid):
    p = request.json or {}
    sets = {}
    for k in ("budget_inr", "attendee_target"):
        if k in p:
            try:
                v = int(p[k])
            except (TypeError, ValueError):
                return err(f"{k} must be a whole number")
            if v < 0:
                return err(f"{k} must be >= 0")
            sets[k] = v
    if "status" in p:
        if p["status"] not in PLAN_STATUS:
            return err("bad status")
        sets["status"] = p["status"]
    if "notes" in p:
        sets["notes"] = str(p["notes"])[:500]
    if not sets:
        return err("nothing to update")
    sets["updated_at"] = now()
    c = A.conn()
    if not c.execute("select 1 from campaign_plan where campaign_id=?", (cid,)).fetchone():
        c.close()
        return err("unknown campaign", 404)
    c.execute(f"update campaign_plan set {','.join(k + '=?' for k in sets)} where campaign_id=?", list(sets.values()) + [cid])
    c.commit()
    c.close()
    A.bump()
    return jsonify(ok=True)


@app.get("/api/decisions")
def decisions_list():
    c = A.conn()
    rows = [dict(r) for r in c.execute("select * from decisions order by id desc limit 50")]
    c.close()
    return jsonify(decisions=rows)


@app.post("/api/decisions")
def decisions_add():
    p = request.json or {}
    if p.get("decision") not in ("scale", "change", "stop", "hold"):
        return err("decision must be scale, change, stop or hold")
    c = A.conn()
    c.execute("insert into decisions (campaign_id, decision, rationale, as_of, created_at) values (?,?,?,?,?)",
              (p.get("campaign_id"), p["decision"], (p.get("rationale") or "")[:500], p.get("as_of"), now()))
    if p.get("campaign_id") and p["decision"] in ("stop", "hold", "scale"):
        c.execute("update campaign_plan set status=?, updated_at=? where campaign_id=?",
                  ({"stop": "stopped", "hold": "paused", "scale": "active"}[p["decision"]], now(), p["campaign_id"]))
    c.commit()
    c.close()
    A.bump()
    return jsonify(ok=True)


@app.post("/api/daily")
def daily_upsert():
    """Add or replace one day of marketing activity for a campaign (analytics update immediately)."""
    p = request.json or {}
    try:
        cid, day = p["campaign_id"], p["activity_date"]
        vals = [int(p.get(k, 0)) for k in ("impressions", "clicks", "reported_reach", "landing_page_sessions",
                                            "registration_starts", "marketing_spend_inr")]
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", day) or min(vals[:5]) < 0:
            raise ValueError
    except (KeyError, ValueError, TypeError):
        return err("campaign_id, activity_date (YYYY-MM-DD) and non-negative whole numbers are required")
    c = A.conn()
    row = c.execute("select campaign_name, owner_name, owner_id from campaigns where campaign_id=?", (cid,)).fetchone()
    if not row:
        c.close()
        return err("unknown campaign", 404)
    aid = f"AD-{cid}-{day.replace('-', '')[4:]}"
    c.execute("delete from campaign_daily where activity_id=?", (aid,))
    c.execute("insert into campaign_daily (campaign_name, owner_name, activity_date, impressions, clicks, reported_reach, "
              "landing_page_sessions, registration_starts, marketing_spend_inr, platform, activity_id, campaign_id, owner_id) "
              "values (?,?,?,?,?,?,?,?,?,?,?,?,?)",
              [row["campaign_name"], row["owner_name"], day + " 00:00:00"] + vals + ["manual entry", aid, cid, row["owner_id"]])
    c.commit()
    c.close()
    A.bump()
    return jsonify(ok=True, activity_id=aid)


@app.post("/api/attendees")
def attendee_add():
    """Quick-add an external person with optional registration/status/check-in so funnel counts can be changed live."""
    p = request.json or {}
    name, cid = (p.get("person_name") or "").strip(), p.get("campaign_id")
    if not name:
        return err("person_name required")
    c = A.conn()
    cam = c.execute("select campaign_name, owner_name, owner_id from campaigns where campaign_id=?", (cid,)).fetchone()
    if not cam:
        c.close()
        return err("unknown campaign", 404)
    n = c.execute("select count(*) from people").fetchone()[0] + 1
    pid = f"M{n:05d}"
    seen = (p.get("first_seen_at") or A.latest_date()) + " 09:00:00"
    c.execute("insert into people (person_name, person_type, first_seen_at, first_touch_source, first_campaign_name, owner_name, person_id, "
              "first_campaign_id, owner_id) values (?,?,?,?,?,?,?,?,?)", (name, "external", seen, "campaign", cam["campaign_name"], cam["owner_name"], pid, cid, cam["owner_id"]))
    rid = None
    if p.get("registered"):
        rid = f"RM{n:05d}"
        c.execute("insert into registrations (person_name, campaign_name, owner_name, registered_at, registration_id, person_id, campaign_id, owner_id) values (?,?,?,?,?,?,?,?)",
                  (name, cam["campaign_name"], cam["owner_name"], seen, rid, pid, cid, cam["owner_id"]))
        status = p.get("status") if p.get("status") in ("interested", "confirmed", "cancelled", "waitlisted") else "confirmed"
        c.execute("insert into reg_history (person_name, campaign_name, owner_name, effective_at, status, history_id, registration_id, person_id, campaign_id, owner_id) values (?,?,?,?,?,?,?,?,?,?)",
                  (name, cam["campaign_name"], cam["owner_name"], seen, status, f"HM{n:05d}", rid, pid, cid, cam["owner_id"]))
    if p.get("attended"):
        c.execute("insert into checkins (person_name, campaign_name, owner_name, occurred_at, result, verification, source, event_id, person_id, registration_id, campaign_id, owner_id) values (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (name, cam["campaign_name"], cam["owner_name"], "2025-04-12 12:00:00", "admitted", "verified", "manual", f"CM{n:05d}", pid, rid, cid, cam["owner_id"]))
    c.commit()
    c.close()
    A.bump()
    return jsonify(ok=True, person_id=pid)


# ------------------------------------------------------------- scenario model
@app.get("/api/model/baseline")
def model_baseline():
    base, walk = M.baseline()
    return jsonify(baseline=base, walkins=walk, beta=M.BETA, cap=M.CAP, presets={k: v for k, v in M.PRESETS.items()})


@app.post("/api/model/run")
def model_run():
    p = request.json or {}
    try:
        res = M.run({k: float(v) for k, v in (p.get("budgets") or {}).items()}, float(p.get("show_uplift", 0)), float(p.get("reg_uplift", 0)))
    except (TypeError, ValueError):
        return err("bad numbers")
    return jsonify(res)


@app.post("/api/scenarios")
def scenario_save():
    p = request.json or {}
    c = A.conn()
    c.execute("insert into scenarios (name, config, result, created_at) values (?,?,?,?)",
              ((p.get("name") or "Scenario")[:80], json.dumps(p.get("config")), json.dumps(p.get("result")), now()))
    c.commit()
    c.close()
    return jsonify(ok=True)


@app.get("/api/scenarios")
def scenario_list():
    c = A.conn()
    rows = [dict(r) for r in c.execute("select id, name, config, result, created_at from scenarios order by id desc limit 20")]
    c.close()
    for r in rows:
        r["config"], r["result"] = json.loads(r["config"] or "null"), json.loads(r["result"] or "null")
    return jsonify(scenarios=rows)


# ------------------------------------------------------------- chat
@app.post("/api/chat")
def chat_post():
    p = request.json or {}
    msg = (p.get("message") or "").strip()
    if not msg:
        return err("empty message")
    as_of = p.get("as_of") or A.latest_date()
    out = chat.answer(msg, p.get("history") or [], as_of)
    c = A.conn()
    c.execute("insert into chat_log (role, content, created_at) values ('user', ?, ?)", (msg, now()))
    c.execute("insert into chat_log (role, content, created_at) values ('assistant', ?, ?)", (out["reply"], now()))
    c.commit()
    c.close()
    return jsonify(out)


@app.post("/api/reset")
def reset():
    etl.build()
    A.bump()
    return jsonify(ok=True)


if __name__ == "__main__":
    ensure_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
else:
    ensure_db()
