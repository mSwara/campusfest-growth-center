"""Embedded AI Growth Analyst.

Two engines share one set of tools, so every answer is computed from the live database:
  1. Gemini (set GEMINI_API_KEY) - the model decides which tools to call (function calling), reads the results and
     writes the answer. Tools: KPIs, campaign table, insights, read-only SQL, calculator, tasks, scenario model,
     and propose_task (which only PROPOSES; the user must confirm before anything is written).
  2. Offline analyst (no key) - a deterministic router over the same tools. It is deliberately narrow and says
     so when a question is outside the data.
"""
import ast
import json
import operator
import os
import re
import sqlite3

import requests

import analytics as A
import model as M
from etl import DB

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_FALLBACKS = [m for m in ("gemini-flash-latest", "gemini-flash-lite-latest") if m != GEMINI_MODEL]

DATA_DICTIONARY = """
Tables in the SQLite database (already de-duplicated by stable ID; timestamps are IST text 'YYYY-MM-DD HH:MM:SS'):
- event(event_name, history_start, history_end, event_starts_at, event_ends_at): CampusFest 2025, 12-13 Apr 2025.
- targets(effective_at, identified_external_people_goal, registration_goal, unique_external_visitors_goal, marketing_budget_inr, target_version): the latest version with effective_at <= as-of applies.
- campaigns(campaign_id, campaign_name, channel, owner_id, owner_name, target_audience, objective, planned_start_at, planned_end_at)
- campaign_daily(activity_date, campaign_id, impressions, clicks, reported_reach, landing_page_sessions, registration_starts, marketing_spend_inr): ANONYMOUS counts. Not unique people; reach cannot be summed into people.
- people(person_id, person_name, person_type, first_seen_at, first_touch_source, first_campaign_id): only person_type='external' counts toward goals. Names repeat; use person_id.
- interactions(person_id, campaign_id, occurred_at, event_type): identified engagement (page_visit, brochure_download, registration_start, nurture_email_*, opted_out, event_question_submitted).
- registrations(registration_id, person_id, campaign_id, registered_at): campaign_id = recorded acquisition source.
- reg_history(registration_id, person_id, campaign_id, effective_at, status): status in interested/confirmed/cancelled/waitlisted. The LATEST row per registration_id with effective_at <= as-of is the current status.
- checkins(event_id, person_id, registration_id, campaign_id, occurred_at, result, verification, source): ACTUAL attendance = result='admitted' AND verification='verified' AND external person; count DISTINCT person_id. campaign_id NULL = unattributed walk-in.
- campaign_plan(campaign_id, budget_inr, attendee_target, status, notes): the team's editable plan.
- tasks(id, title, campaign_id, owner_id, due_date, status, priority, notes): execution tracker. status todo/in_progress/blocked/done.
- decisions(campaign_id, decision, rationale, as_of)
NOT in the data: revenue, ticket prices, demographics (age/college/gender), city/location of attendees, sentiment, sponsor money (separate dataset), per-person cost, creative-level performance, hourly ad data.
"""

# ------------------------------------------------------------------ tools


def _readonly(sql):
    s = sql.strip().rstrip(";")
    if not re.match(r"(?is)^\s*(select|with)\b", s) or ";" in s:
        return {"error": "Only a single SELECT statement is allowed."}
    if re.search(r"(?i)\b(insert|update|delete|drop|alter|create|attach|pragma|replace)\b", s):
        return {"error": "Read-only queries only."}
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)
    try:
        cur = c.execute(s)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(200)
        return {"columns": cols, "rows": [list(r) for r in rows], "truncated": len(rows) == 200}
    except Exception as e:  # noqa
        return {"error": str(e)}
    finally:
        c.close()


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.USub: operator.neg, ast.Mod: operator.mod}


def _calc(expr):
    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        raise ValueError("unsupported expression")
    try:
        return {"expression": expr, "result": ev(ast.parse(expr.replace(",", ""), mode="eval"))}
    except Exception as e:  # noqa
        return {"error": f"Cannot evaluate: {e}"}


def _owners():
    c = A.conn()
    try:
        return {r["owner_id"]: r["owner_name"] for r in c.execute("select distinct owner_id, owner_name from campaigns")}
    finally:
        c.close()


def t_get_kpis(as_of=None):
    return A.kpis(as_of or A.latest_date())


def t_get_campaigns(as_of=None):
    rows = A.campaigns_table(as_of or A.latest_date())
    keep = ["campaign_id", "name", "channel", "owner", "identified", "registered", "confirmed", "cancelled", "waitlisted",
            "attended", "spend", "reg_rate", "show_rate", "cpi", "cpr", "cpa", "plan_budget", "plan_target", "target_pct",
            "budget_used_pct", "verdict", "why", "flags", "tasks_open", "tasks_overdue", "tasks_blocked"]
    return [{k: r.get(k) for k in keep} for r in rows]


def t_get_insights(as_of=None):
    return A.insights(as_of or A.latest_date())


def t_list_tasks(status=None, campaign_id=None, overdue_only=False, as_of=None):
    f = A.frames()["tasks"]
    if status:
        f = f[f.status == status]
    if campaign_id:
        f = f[f.campaign_id == campaign_id]
    if overdue_only:
        d = as_of or A.latest_date()
        f = f[(f.status != "done") & (f.due_date < d)]
    return f[["id", "title", "campaign_id", "owner_id", "due_date", "status", "priority"]].to_dict("records")


def t_propose_task(title, campaign_id=None, owner_id=None, due_date=None, priority="medium", notes=""):
    return {"proposal": dict(title=title, campaign_id=campaign_id, owner_id=owner_id, due_date=due_date,
                             priority=priority, notes=notes, source="assistant"),
            "status": "NOT SAVED - waiting for the user to confirm in the UI."}


def t_project_scenario(budgets=None, show_uplift=0.0, reg_uplift=0.0):
    base = dict(M.PRESETS["2025 repeat"]["budgets"])
    base.update({k: float(v) for k, v in (budgets or {}).items()})
    r = M.run(base, float(show_uplift or 0), float(reg_uplift or 0))
    r["assumptions"] = "Model calibrated on 2025 actuals; elasticity (beta) and channel caps are assumptions."
    return r


TOOLS = {
    "get_kpis": (t_get_kpis, "Headline funnel KPIs vs the target in force on the as-of date (identified, registered, confirmed, attended, spend, rates, budget).",
                 {"as_of": "string YYYY-MM-DD (optional, default = latest data date)"}),
    "get_campaigns": (t_get_campaigns, "Per-campaign funnel, cost metrics, plan, verdict and execution health as of a date.",
                      {"as_of": "string YYYY-MM-DD (optional)"}),
    "get_insights": (t_get_insights, "Ranked evidence-backed recommended actions as of a date.", {"as_of": "string YYYY-MM-DD (optional)"}),
    "query_data": (lambda sql: _readonly(sql), "Run ONE read-only SQL SELECT on the app database for any custom question. Use the data dictionary.",
                   {"sql": "string, a single SELECT"}),
    "calculate": (lambda expression: _calc(expression), "Evaluate an arithmetic expression exactly (use for any calculation).",
                  {"expression": "string, e.g. '93000/340'"}),
    "list_tasks": (t_list_tasks, "List tasks, optionally filtered.", {"status": "todo|in_progress|blocked|done (optional)",
                                                                   "campaign_id": "e.g. C02 (optional)", "overdue_only": "boolean (optional)",
                                                                   "as_of": "string (optional)"}),
    "propose_task": (t_propose_task, "PROPOSE a task. It is NOT saved until the user confirms in the UI. Always tell the user to confirm.",
                     {"title": "string", "campaign_id": "string (optional)", "owner_id": "T01..T06 (optional)",
                      "due_date": "YYYY-MM-DD (optional)", "priority": "low|medium|high", "notes": "string (optional)"}),
    "project_scenario": (t_project_scenario, "Project next-edition attendees under a new budget split (INR per campaign id) and optional show-up / registration uplifts (e.g. 0.05 = +5pp).",
                         {"budgets": "object campaign_id -> INR (optional; unspecified use 2025 spend)", "show_uplift": "number", "reg_uplift": "number"}),
}


def _declarations():
    decl = []
    for name, (fn, desc, params) in TOOLS.items():
        props = {}
        for k, v in params.items():
            typ = "string"
            if "number" in v:
                typ = "number"
            if "boolean" in v:
                typ = "boolean"
            if "object" in v:
                props[k] = {"type": "object", "description": v}
                continue
            props[k] = {"type": typ, "description": v}
        decl.append({"name": name, "description": desc,
                     "parameters": {"type": "object", "properties": props, "required": [k for k, v in params.items() if "optional" not in v and k != "notes"]}})
    return decl


def run_tool(name, args):
    if name not in TOOLS:
        return {"error": f"unknown tool {name}"}
    try:
        return TOOLS[name][0](**(args or {}))
    except TypeError as e:
        return {"error": f"bad arguments: {e}"}
    except Exception as e:  # noqa
        return {"error": str(e)}


# ------------------------------------------------------------------ Gemini engine

SYSTEM = """You are the Growth Analyst embedded in the CampusFest Growth Center. You help the team run an attendee-growth campaign.
Rules:
1. Ground every number in a tool result. Never use outside knowledge for campaign facts. Prefer get_kpis/get_campaigns/get_insights; use query_data for anything custom; use calculate for arithmetic.
2. The UI's selected as-of date is {as_of}. Use it unless the user names another date; always state the as-of date you used. Nothing after the as-of date may be used.
3. Definitions: attendee = distinct EXTERNAL person with an admitted+verified check-in; registered = distinct external people with a registration; confirmed = latest status confirmed. Anonymous impressions/reach/clicks are not people.
4. Separate EVIDENCE (from data) from ASSUMPTIONS (e.g. model elasticity). If the data cannot answer (see the dictionary's 'NOT in the data' list), say exactly that, say what is missing, and offer the closest answerable question. Do not guess.
5. To act, call propose_task, then tell the user a proposal is waiting and they must confirm it. Never claim a task was created.
6. Be concise: lead with the answer, then 2-4 bullets of evidence, then a recommendation if asked. Use Indian Rupee formatting (Rs).
Data dictionary:
""" + DATA_DICTIONARY


def _post_gemini(body, used):
    """Try the preferred model, retry once when busy (429/500/503), then fall back to other models."""
    import time
    last = None
    for model in [used[0]] + [m for m in [GEMINI_MODEL] + GEMINI_FALLBACKS if m != used[0]]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(2):
            r = requests.post(url, params={"key": GEMINI_KEY}, json=body, timeout=60)
            if r.status_code == 200:
                used[0] = model
                return r
            last = r
            if r.status_code in (429, 500, 503) and attempt == 0:
                time.sleep(1.5)
                continue
            break
        if last is not None and last.status_code in (400, 401, 403):
            break
    raise RuntimeError(f"Gemini error {last.status_code}: {last.text[:300]}")


def gemini_chat(message, history, as_of):
    contents = []
    for h in history[-10:]:
        contents.append({"role": "user" if h["role"] == "user" else "model", "parts": [{"text": h["text"]}]})
    contents.append({"role": "user", "parts": [{"text": message}]})
    trace, proposals = [], []
    used = [GEMINI_MODEL]
    for _ in range(8):
        body = {"system_instruction": {"parts": [{"text": SYSTEM.format(as_of=as_of)}]}, "contents": contents,
                "tools": [{"function_declarations": _declarations()}], "generationConfig": {"temperature": 0.2}}
        r = _post_gemini(body, used)
        parts = r.json()["candidates"][0]["content"].get("parts", [])
        calls = [p["functionCall"] for p in parts if "functionCall" in p]
        if not calls:
            text = "".join(p.get("text", "") for p in parts).strip()
            return dict(reply=text or "I could not produce an answer.", trace=trace, proposals=proposals, engine=f"gemini:{used[0]}")
        contents.append({"role": "model", "parts": parts})
        resp_parts = []
        for c in calls:
            args = dict(c.get("args", {}))
            if c["name"] in ("get_kpis", "get_campaigns", "get_insights") and not args.get("as_of"):
                args["as_of"] = as_of
            res = run_tool(c["name"], args)
            if c["name"] == "propose_task" and "proposal" in res:
                proposals.append(res["proposal"])
            trace.append(dict(tool=c["name"], args=args, result_preview=json.dumps(res, default=str)[:400]))
            resp_parts.append({"functionResponse": {"name": c["name"], "response": {"result": json.loads(json.dumps(res, default=str))}}})
        contents.append({"role": "user", "parts": resp_parts})
    return dict(reply="I hit the tool-call limit before finishing. Try a narrower question.", trace=trace, proposals=proposals, engine="gemini")


# ------------------------------------------------------------------ offline analyst

ALIASES = {"C01": ["ambassador"], "C02": ["paid social", "paid", "social ads", "ads"], "C03": ["creator", "influencer"],
           "C04": ["college partner", "college", "partnership"], "C05": ["referral"], "C06": ["organic", "search", "seo"],
           "C07": ["community", "communities"]}
UNANSWERABLE = ["revenue", "ticket price", "profit", "age", "gender", "demographic", "which college", "city", "weather", "sentiment",
                "nps", "feedback", "sponsor", "instagram follower", "creative", "ad copy", "hourly", "per hour spend", "salary", "competitor"]


def _find_campaigns(text, rows):
    t = text.lower()
    found = []
    for r in rows:
        if r["campaign_id"].lower() in t or r["name"].lower() in t or any(a in t for a in ALIASES.get(r["campaign_id"], [])):
            found.append(r)
    return found


def _fmt_inr(x):
    return "Rs {:,.0f}".format(x) if x is not None else "n/a"


def _pct(x):
    return "n/a" if x is None else f"{x*100:.1f}%"


def offline_chat(message, history, as_of):
    m = message.lower().strip()
    rows = A.campaigns_table(as_of)
    k = A.kpis(as_of)
    trace, proposals = [], []
    pre = k["pre_event"]

    def done(text, tools=()):
        for t in tools:
            trace.append(dict(tool=t, args={"as_of": as_of}, result_preview="(computed from live data)"))
        return dict(reply=text, trace=trace, proposals=proposals, engine="offline-analyst")

    # follow-up resolution: "and its show rate?" -> reuse the last campaign mentioned
    named = _find_campaigns(m, rows)
    if not named and history and re.search(r"\b(it|its|that|them|those|this one)\b", m):
        for h in reversed(history):
            named = _find_campaigns(h["text"], rows)
            if named:
                break

    for w in UNANSWERABLE:
        if re.search(r"(?<![a-z])" + re.escape(w) + r"s?(?![a-z])", m):
            return done(f"I can't answer that from this data. The dataset has no field for **{w}**. It covers campaigns, daily marketing "
                        "counts and spend, identified people, registrations and status history, and check-ins. "
                        "I can answer questions about funnel conversion, cost per registrant/attendee, show-up, targets and tasks.")

    # calculation
    mc = re.search(r"(?:calculate|compute|what is|what's)\s+([\d\.,\s\+\-\*/\(\)%]+)\s*\??$", m)
    if mc and re.search(r"[\+\-\*/]", mc.group(1)):
        r = _calc(mc.group(1).replace("%", "/100"))
        if "result" in r:
            return done(f"{mc.group(1).strip()} = **{r['result']:,.4g}**", ["calculate"])

    # task creation
    mt = re.search(r"(?:create|add|make|log)\s+(?:a\s+)?(?:new\s+)?task(?:\s+(?:to|for|called|:))?\s*(.+)", m)
    if mt:
        title = message[message.lower().index(mt.group(1)):].strip().rstrip(".")
        camp = named[0] if named else None
        p = t_propose_task(title[:140].capitalize(), camp["campaign_id"] if camp else None, camp["owner_id"] if camp else None,
                           None, "medium", f"Proposed by analyst (as of {as_of})")
        proposals.append(p["proposal"])
        return done(f"I've drafted a task: **{p['proposal']['title']}**"
                    + (f" (campaign {camp['name']}, owner {camp['owner']})" if camp else "")
                    + ". Nothing is saved yet. Please **confirm it** below to add it to the tracker.", ["propose_task"])

    if re.search(r"overdue|late tasks|behind schedule tasks", m):
        t = t_list_tasks(overdue_only=True, as_of=as_of)
        if not t:
            return done(f"No overdue tasks as of {as_of}.", ["list_tasks"])
        return done(f"{len(t)} overdue task(s) as of {as_of}:\n" + "\n".join(f"- #{x['id']} {x['title']} (due {x['due_date']}, {x['status']}, owner {x['owner_id']})" for x in t), ["list_tasks"])
    if re.search(r"\btasks?\b|to-?do|action items", m):
        t = t_list_tasks(campaign_id=named[0]["campaign_id"] if named else None)
        op = [x for x in t if x["status"] != "done"]
        return done(f"{len(op)} open task(s)" + (f" for {named[0]['name']}" if named else "") + ":\n"
                    + "\n".join(f"- #{x['id']} [{x['status']}] {x['title']} (due {x['due_date']}, {x['owner_id']})" for x in op), ["list_tasks"])

    # what-if
    if re.search(r"what if|scenario|move|shift|reallocate|increase .*budget|cut .*budget", m):
        mm = re.search(r"(?:move|shift|reallocate|cut)\s*(?:rs\.?|₹|inr)?\s*([\d,\.]+)\s*(k|l|lakh)?", m)
        if mm and len(named) >= 1:
            amt = float(mm.group(1).replace(",", ""))
            amt *= 1000 if mm.group(2) == "k" else 100000 if mm.group(2) in ("l", "lakh") else 1
            base = dict(M.PRESETS["2025 repeat"]["budgets"])
            src = named[0]["campaign_id"]
            dst = named[1]["campaign_id"] if len(named) > 1 else None
            if dst:
                base[src] -= amt
                base[dst] += amt
                b0 = M.run(M.PRESETS["2025 repeat"]["budgets"])["total"]["attended"]
                r = M.run(base)
                d = r["total"]["attended"] - b0
                return done(f"Model projection (2025 actuals as the base, elasticity is an assumption): moving {_fmt_inr(amt)} from "
                            f"{named[0]['name']} to {named[1]['name']} changes attendees from {b0:,} to **{r['total']['attended']:,}** ({d:+,}). "
                            "Treat this as directional: the data has one spend level per campaign so diminishing returns are assumed, not measured.", ["project_scenario"])
        return done("Tell me the amount and the two campaigns, e.g. 'what if we move 20k from Paid Social to Student Referrals?'")

    # specific campaign
    if named:
        r = named[0]
        focus = None
        for pat, key, lab, kind in [(r"show[- ]?up|show rate|no[- ]?show", "show_rate", "show-up rate", "pct"),
                                    (r"cost per attend|cpa", "cpa", "cost per attendee", "inr"),
                                    (r"cost per reg|cpr", "cpr", "cost per registrant", "inr"),
                                    (r"cost per (identified|lead)|cpi", "cpi", "cost per identified person", "inr"),
                                    (r"registration rate|reg rate|convert", "reg_rate", "registration rate (registered / identified)", "pct"),
                                    (r"spend|spent|budget", "spend", "spend", "inr"),
                                    (r"registr", "registered", "registrants", "num"),
                                    (r"attend|turn(ed)? up|came", "attended", "verified attendees", "num"),
                                    (r"identif|leads?", "identified", "identified people", "num"),
                                    (r"verdict|scale|stop", "verdict", "verdict", "txt")]:
            if re.search(pat, m):
                focus = (key, lab, kind)
                break
        if focus and not (pre and focus[0] in ("show_rate", "cpa", "attended")):
            key, lab, kind = focus
            val = r.get(key)
            shown = _pct(val) if kind == "pct" else _fmt_inr(val) if kind == "inr" else f"{val:,}" if kind == "num" else str(val)
            extra = f" Reason: {r['why']}" if key == "verdict" else ""
            return done(f"{r['name']}: {lab} = **{shown}** as of {as_of}.{extra}", ["get_campaigns"])
        if focus and pre:
            return done(f"{r['name']}: {focus[1]} isn't known as of {as_of} because attendance only exists after the event ({k['event']['starts']}).", ["get_campaigns"])
        if pre:
            return done(f"**{r['name']}** as of {as_of}: {r['identified']:,} identified, {r['registered']:,} registered "
                        f"({_pct(r['reg_rate'])} of identified), spend {_fmt_inr(r['spend'])}, cost per registrant {_fmt_inr(r['cpr'])}. "
                        "Attendance isn't known yet because the event hasn't happened by this date.", ["get_campaigns"])
        txt = (f"**{r['name']}** as of {as_of}: {r['attended']:,} verified attendees from {r['registered']:,} registrants "
               f"(show-up {_pct(r['show_rate'])}), spend {_fmt_inr(r['spend'])}, **cost per attendee {_fmt_inr(r['cpa'])}** "
               f"vs blended {_fmt_inr(k['cpa'])}. Verdict: **{r['verdict']}**. {r['why']}")
        if r["plan_target"]:
            txt += f" Target attainment: {_pct(r['target_pct'])} of its {r['plan_target']:,} plan."
        return done(txt, ["get_campaigns"])

    # ranking
    mr = re.search(r"(best|worst|highest|lowest|top|bottom|most|least)", m)
    metric = None
    for key, col in [("cost per attendee", "cpa"), ("cpa", "cpa"), ("show", "show_rate"), ("attend", "attended"), ("registr", "registered"),
                     ("cost per reg", "cpr"), ("spend", "spend"), ("identif", "identified"), ("efficien", "cpa")]:
        if key in m:
            metric = col
            break
    if mr and metric:
        cand = [r for r in rows if r["campaign_id"] != "UNATTR" and r.get(metric) is not None]
        if not cand:
            return done("That metric isn't available as of this date (attendance is only known after the event).")
        low_good = metric in ("cpa", "cpr")
        want_low = (mr.group(1) in ("best", "lowest", "bottom", "least")) == low_good if metric in ("cpa", "cpr") else mr.group(1) in ("worst", "lowest", "bottom", "least")
        cand.sort(key=lambda r: r[metric], reverse=not want_low)
        lab = {"cpa": "cost per attendee", "cpr": "cost per registrant", "show_rate": "show-up rate", "attended": "attendees",
               "registered": "registrants", "spend": "spend", "identified": "identified people"}[metric]
        f = lambda r: _pct(r[metric]) if metric == "show_rate" else (_fmt_inr(r[metric]) if metric in ("cpa", "cpr", "spend") else f"{r[metric]:,}")
        return done(f"Ranking by {lab} ({'ascending' if want_low else 'descending'}), as of {as_of}:\n"
                    + "\n".join(f"{i+1}. {r['name']}: {f(r)}" for i, r in enumerate(cand)), ["get_campaigns"])

    # diagnosis / recommendations
    if re.search(r"bottleneck|diagnos|why|leak|problem|underperform|issue", m):
        bad = [r for r in rows if r["flags"] and r["campaign_id"] != "UNATTR" and any(f in r["flags"] for f in ("low_show_rate", "registration_leak", "high_cpa", "high_cpr"))]
        steps = [("identified→registered", k["reg_rate"]), ("confirmed→attended", None if pre else (k["attended"] / k["confirmed"] if k["confirmed"] else None))]
        txt = f"As of {as_of}: identified→registered {_pct(k['reg_rate'])}" + ("" if pre else f", registered→attended {_pct(k['show_rate'])}") + ".\n"
        txt += "Campaigns with problems:\n" + ("\n".join(f"- {r['name']}: {', '.join(r['flags'])}. {r['why']}" for r in bad) if bad else "- none flagged") if bad or True else ""
        return done(txt, ["get_kpis", "get_campaigns"])
    if re.search(r"recommend|should we|prioriti|scale|stop|what next|next step|focus|improve|suggest", m):
        ins = A.insights(as_of)[:5]
        return done(f"Top actions as of {as_of} (each backed by data):\n" + "\n".join(f"- **{i['title']}**. {i['evidence']} {i['recommendation']}" for i in ins)
                    + "\nSay 'create task to ...' and I'll draft it for your confirmation.", ["get_insights"])

    # kpi
    if re.search(r"how many|total|summary|status|how are we|kpi|funnel|target|goal|attendee|registr|identified|spend|budget|show", m):
        t = k["target"]
        txt = (f"As of {as_of} ({t['version']} in force): **{k['identified']:,}** identified external people "
               f"({_pct(k['pct_identified'])} of {t['identified']:,}), **{k['registered']:,}** registered ({_pct(k['pct_registered'])} of {t['registered']:,}), "
               f"{k['confirmed']:,} currently confirmed")
        if pre:
            txt += f". Attendance isn't known yet (event starts {k['event']['starts']})"
        else:
            txt += f", **{k['attended']:,}** verified attendees ({_pct(k['pct_attended'])} of {t['attended']:,}), show-up {_pct(k['show_rate'])}"
        txt += f". Spend {_fmt_inr(k['spend'])} of {_fmt_inr(t['budget'])} limit"
        if k["cpa"]:
            txt += f", cost per attendee {_fmt_inr(k['cpa'])}"
        return done(txt + ".", ["get_kpis"])

    return done("I couldn't map that to something I can compute from this data. Try asking about funnel numbers vs target, a campaign's cost per "
                "attendee or show-up, the best/worst campaign by a metric, bottlenecks, recommendations, tasks, or a budget what-if. "
                "(Connect a Gemini key for open-ended questions.)")


def answer(message, history, as_of):
    as_of = as_of or A.latest_date()
    if GEMINI_KEY:
        try:
            return gemini_chat(message, history, as_of)
        except Exception as e:  # noqa
            out = offline_chat(message, history, as_of)
            out["reply"] = f"(Gemini unavailable: {e}. Using the offline analyst.)\n\n" + out["reply"]
            return out
    return offline_chat(message, history, as_of)
