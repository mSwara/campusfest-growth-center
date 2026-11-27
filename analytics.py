"""Analytics engine. Everything the dashboard and the AI analyst show is computed here from the SQLite tables,
so any edit to the data, the plan or the tasks flows straight into every number.

Definitions (see README for the reasoning):
  identified  = distinct EXTERNAL people first seen on or before the as-of day
  registered  = distinct external people with a registration on or before the as-of day
  confirmed   = registered people whose LATEST status on/before the as-of day is 'confirmed'
  attended    = distinct external people with an ADMITTED + VERIFIED check-in on or before the as-of day
  as-of day D = end of day D, Asia/Kolkata. Nothing after D is ever used.
"""
import os
import sqlite3
import threading

import pandas as pd

from etl import DB

_lock = threading.Lock()
_cache = {}
_version = [0]

DEFAULT_SHOW_RATE_ASSUMPTION = 0.65     # used only for projections made BEFORE the event (no look-ahead)
TH = dict(show_low=0.60, reg_low=0.70, cpa_high=1.5, cpa_low=0.8, behind=0.80)


def conn():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def bump():
    """Call after any write so cached frames are rebuilt."""
    with _lock:
        _version[0] += 1
        _cache.clear()


def frames():
    with _lock:
        if _cache.get("v") == _version[0] and "f" in _cache:
            return _cache["f"]
    c = sqlite3.connect(DB)
    names = ["event", "targets", "campaigns", "campaign_daily", "people", "interactions", "registrations",
             "reg_history", "checkins", "campaign_plan", "tasks", "decisions"]
    f = {n: pd.read_sql(f"select * from {n}", c) for n in names}
    c.close()
    for n, cols in {"people": ["first_seen_at"], "interactions": ["occurred_at"], "registrations": ["registered_at"],
                    "reg_history": ["effective_at"], "checkins": ["occurred_at"], "targets": ["effective_at"],
                    "campaign_daily": ["activity_date"]}.items():
        for col in cols:
            f[n][col] = pd.to_datetime(f[n][col])
    with _lock:
        _cache["f"] = f
        _cache["v"] = _version[0]
    return f


def event_info():
    e = frames()["event"].iloc[0]
    return dict(name=e.event_name, starts=str(e.event_starts_at)[:10], ends=str(e.event_ends_at)[:10],
                history_start=str(e.history_start)[:10], history_end=str(e.history_end)[:10])


def latest_date():
    return event_info()["history_end"]


def _end(d):
    return pd.Timestamp(d) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)


def _ext(f):
    return set(f["people"].loc[f["people"].person_type == "external", "person_id"])


def targets_as_of(d):
    t = frames()["targets"]
    t = t[t.effective_at <= _end(d)].sort_values("effective_at")
    if t.empty:
        return None
    r = t.iloc[-1]
    return dict(version=r.target_version, effective_at=str(r.effective_at)[:10],
                identified=int(r.identified_external_people_goal), registered=int(r.registration_goal),
                attended=int(r.unique_external_visitors_goal), budget=int(r.marketing_budget_inr))


def _cid(s):
    return s.fillna("UNATTR")


def _state(d):
    """Per-campaign counts as of day d."""
    f = frames()
    E = _end(d)
    ext = _ext(f)
    pe = f["people"]
    pe = pe[(pe.person_type == "external") & (pe.first_seen_at <= E)]
    identified = pe.groupby(_cid(pe.first_campaign_id)).person_id.nunique()

    rg = f["registrations"]
    rg = rg[rg.person_id.isin(ext) & (rg.registered_at <= E)]
    registered = rg.groupby(_cid(rg.campaign_id)).person_id.nunique()

    h = f["reg_history"]
    h = h[h.effective_at <= E].sort_values("effective_at").groupby("registration_id").tail(1)
    h = h[h.person_id.isin(ext)]
    status = h.groupby([_cid(h.campaign_id), "status"]).person_id.nunique().unstack(fill_value=0)

    ck = f["checkins"]
    ck = ck[(ck.occurred_at <= E) & (ck.result == "admitted") & (ck.verification == "verified") & ck.person_id.isin(ext)]
    attended = ck.groupby(_cid(ck.campaign_id)).person_id.nunique()

    cd = f["campaign_daily"]
    cd = cd[cd.activity_date <= pd.Timestamp(d)]
    agg = cd.groupby("campaign_id")[["impressions", "clicks", "reported_reach", "landing_page_sessions",
                                     "registration_starts", "marketing_spend_inr"]].sum()
    return identified, registered, status, attended, agg


def _safe(a, b):
    return round(a / b, 4) if b else None


def campaigns_table(d):
    f = frames()
    identified, registered, status, attended, agg = _state(d)
    plan = f["campaign_plan"].set_index("campaign_id")
    camps = f["campaigns"].set_index("campaign_id")
    tk = f["tasks"].copy()
    tk["due"] = pd.to_datetime(tk.due_date)
    ev = event_info()
    pre_event = pd.Timestamp(d) < pd.Timestamp(ev["starts"])
    rows = []
    for cid in list(camps.index) + ["UNATTR"]:
        c = camps.loc[cid] if cid in camps.index else None
        p = plan.loc[cid] if cid in plan.index else None
        spend = int(agg.marketing_spend_inr.get(cid, 0)) if cid in agg.index else 0
        r = dict(
            campaign_id=cid, name=c.campaign_name if c is not None else "Walk-ins / unattributed",
            channel=c.channel if c is not None else "walk_in", owner_id=c.owner_id if c is not None else None,
            owner=c.owner_name if c is not None else None,
            identified=int(identified.get(cid, 0)), registered=int(registered.get(cid, 0)),
            confirmed=int(status.loc[cid, "confirmed"]) if cid in status.index and "confirmed" in status else 0,
            cancelled=int(status.loc[cid, "cancelled"]) if cid in status.index and "cancelled" in status else 0,
            waitlisted=int(status.loc[cid, "waitlisted"]) if cid in status.index and "waitlisted" in status else 0,
            attended=int(attended.get(cid, 0)), spend=spend,
            impressions=int(agg.impressions.get(cid, 0)) if cid in agg.index else 0,
            clicks=int(agg.clicks.get(cid, 0)) if cid in agg.index else 0,
            sessions=int(agg.landing_page_sessions.get(cid, 0)) if cid in agg.index else 0,
            form_starts=int(agg.registration_starts.get(cid, 0)) if cid in agg.index else 0,
            plan_budget=int(p.budget_inr) if p is not None else None,
            plan_target=int(p.attendee_target) if p is not None else None,
            plan_status=p.status if p is not None else None,
            plan_notes=p.notes if p is not None else "",
        )
        r["reg_rate"] = _safe(r["registered"], r["identified"])
        r["show_rate"] = _safe(r["attended"], r["registered"]) if not pre_event else None
        r["cpi"] = _safe(r["spend"], r["identified"])
        r["cpr"] = _safe(r["spend"], r["registered"])
        r["cpa"] = _safe(r["spend"], r["attended"]) if not pre_event else None
        r["target_pct"] = _safe(r["attended"], r["plan_target"]) if not pre_event and r["plan_target"] else None
        r["budget_used_pct"] = _safe(r["spend"], r["plan_budget"]) if r["plan_budget"] else None
        sub = tk[tk.campaign_id == cid] if cid != "UNATTR" else tk.iloc[0:0]
        open_ = sub[sub.status != "done"]
        r["tasks_open"] = int(len(open_))
        r["tasks_overdue"] = int((open_.due < pd.Timestamp(d)).sum())
        r["tasks_blocked"] = int((sub.status == "blocked").sum())
        rows.append(r)
    rows = [r for r in rows if r["campaign_id"] != "UNATTR" or r["attended"] or r["identified"]]
    _diagnose(rows, pre_event)
    return rows


def _diagnose(rows, pre_event):
    paid = [r for r in rows if r["campaign_id"] != "UNATTR"]
    sp, att = sum(r["spend"] for r in paid), sum(r["attended"] for r in paid)
    reg = sum(r["registered"] for r in paid)
    blended_cpa = sp / att if att else None
    blended_cpr = sp / reg if reg else None
    for r in rows:
        flags = []
        if r["campaign_id"] == "UNATTR":
            r["flags"], r["verdict"], r["why"] = [], "info", "Walk-ins and people without a recorded campaign."
            continue
        if r["show_rate"] is not None and r["show_rate"] < TH["show_low"]:
            flags.append("low_show_rate")
        if r["reg_rate"] is not None and r["reg_rate"] < TH["reg_low"]:
            flags.append("registration_leak")
        if blended_cpa and r["cpa"] and r["cpa"] > TH["cpa_high"] * blended_cpa:
            flags.append("high_cpa")
        if blended_cpa and r["cpa"] and r["cpa"] < TH["cpa_low"] * blended_cpa:
            flags.append("efficient_cpa")
        if blended_cpr and r["cpr"] and pre_event and r["cpr"] > TH["cpa_high"] * blended_cpr:
            flags.append("high_cpr")
        if r["target_pct"] is not None and r["target_pct"] < TH["behind"]:
            flags.append("behind_plan")
        if r["plan_status"] == "stopped":
            verdict, why = "stopped", "Marked stopped in the plan."
        elif "high_cpa" in flags and "low_show_rate" in flags:
            verdict, why = "reduce", "Cost per attendee is far above blended AND fewer than 60% of registrants show up."
        elif "low_show_rate" in flags or "registration_leak" in flags:
            verdict, why = "fix", "A funnel step is leaking; fix it before adding spend."
        elif "efficient_cpa" in flags:
            verdict, why = "scale", "Cost per attendee well below blended with healthy conversion."
        elif "high_cpr" in flags:
            verdict, why = "fix", "Cost per registration is well above blended."
        else:
            verdict, why = "hold", "Within normal range."
        r["flags"], r["verdict"], r["why"] = flags, verdict, why
    return blended_cpa


def kpis(d):
    rows = campaigns_table(d)
    tg = targets_as_of(d)
    f = frames()
    E = _end(d)
    ext = _ext(f)
    pe = f["people"]
    ident = int(((pe.person_type == "external") & (pe.first_seen_at <= E)).sum())
    rg = f["registrations"]
    reg = int(rg[rg.person_id.isin(ext) & (rg.registered_at <= E)].person_id.nunique())
    ck = f["checkins"]
    att = int(ck[(ck.occurred_at <= E) & (ck.result == "admitted") & (ck.verification == "verified")
                 & ck.person_id.isin(ext)].person_id.nunique())
    h = f["reg_history"]
    h = h[h.effective_at <= E].sort_values("effective_at").groupby("registration_id").tail(1)
    h = h[h.person_id.isin(ext)]
    conf = int((h.status == "confirmed").sum())
    canc = int((h.status == "cancelled").sum())
    wait = int((h.status == "waitlisted").sum())
    cd = f["campaign_daily"]
    cd = cd[cd.activity_date <= pd.Timestamp(d)]
    spend = int(cd.marketing_spend_inr.sum())
    ev = event_info()
    pre = pd.Timestamp(d) < pd.Timestamp(ev["starts"])
    plan_budget = int(f["campaign_plan"].budget_inr.sum())
    return dict(
        as_of=d, event=ev, pre_event=bool(pre), target=tg,
        identified=ident, registered=reg, confirmed=conf, cancelled=canc, waitlisted=wait, attended=att, spend=spend,
        impressions=int(cd.impressions.sum()), clicks=int(cd.clicks.sum()), sessions=int(cd.landing_page_sessions.sum()),
        form_starts=int(cd.registration_starts.sum()),
        reg_rate=_safe(reg, ident), confirm_rate=_safe(conf, reg), show_rate=None if pre else _safe(att, reg),
        cpa=None if pre or not att else round(spend / att, 1), cpr=round(spend / reg, 1) if reg else None,
        plan_budget=plan_budget, budget_headroom=(tg["budget"] - plan_budget) if tg else None,
        pct_identified=_safe(ident, tg["identified"]) if tg else None,
        pct_registered=_safe(reg, tg["registered"]) if tg else None,
        pct_attended=None if pre or not tg else _safe(att, tg["attended"]),
        budget_used_pct=_safe(spend, tg["budget"]) if tg else None,
    )


def timeline(d):
    """Cumulative daily series up to d (people, registrations, check-ins, spend)."""
    f = frames()
    ext = _ext(f)
    days = pd.date_range(f["event"].iloc[0].history_start, pd.Timestamp(d))
    pe = f["people"][f["people"].person_type == "external"]
    s = pd.DataFrame(index=days)
    s["identified"] = pe.groupby(pe.first_seen_at.dt.normalize()).person_id.nunique().reindex(days, fill_value=0).cumsum()
    rg = f["registrations"]
    rg = rg[rg.person_id.isin(ext)]
    s["registered"] = rg.groupby(rg.registered_at.dt.normalize()).person_id.nunique().reindex(days, fill_value=0).cumsum()
    ck = f["checkins"]
    ck = ck[(ck.result == "admitted") & (ck.verification == "verified") & ck.person_id.isin(ext)].sort_values("occurred_at")
    first = ck.drop_duplicates("person_id")
    s["attended"] = first.groupby(first.occurred_at.dt.normalize()).person_id.nunique().reindex(days, fill_value=0).cumsum()
    cd = f["campaign_daily"]
    s["spend"] = cd.groupby("activity_date").marketing_spend_inr.sum().reindex(days, fill_value=0).cumsum()
    s = s.reset_index().rename(columns={"index": "date"})
    s["date"] = s["date"].dt.strftime("%Y-%m-%d")
    return s.to_dict("records")


def projection(d):
    """Run-rate projection. Before the event: last-7-day registration pace carried to the event day and a flat
    assumed show-up rate (we must not use this edition's later outcomes). After the event: actuals."""
    k = kpis(d)
    ev = event_info()
    if not k["pre_event"]:
        return dict(mode="actual", registered=k["registered"], attended=k["attended"],
                    note="Event finished: these are actuals, not projections.")
    series = timeline(d)
    last7 = series[-8:]
    pace = (last7[-1]["registered"] - last7[0]["registered"]) / max(len(last7) - 1, 1)
    days_left = (pd.Timestamp(ev["starts"]) - pd.Timestamp(d)).days
    proj_reg = int(round(k["registered"] + pace * days_left))
    show = float(os.environ.get("ASSUMED_SHOW_RATE", DEFAULT_SHOW_RATE_ASSUMPTION))
    walk = 0
    proj_att = int(round(proj_reg * show * (k["confirmed"] / k["registered"] if k["registered"] else 1) + walk))
    tg = k["target"]
    return dict(mode="projection", days_to_event=days_left, pace_per_day=round(pace, 1), registered=proj_reg,
                assumed_show_rate=show, attended=proj_att,
                gap_to_attendee_goal=(tg["attended"] - proj_att) if tg else None,
                note="Assumptions: the last-7-day registration pace continues; show-up equals the assumed rate "
                     "(not taken from this event's outcomes) applied to confirmed registrations.")


def insights(d):
    """Evidence-backed recommended actions, each convertible into a task."""
    rows = [r for r in campaigns_table(d) if r["campaign_id"] != "UNATTR"]
    k = kpis(d)
    out = []
    tg = k["target"]
    top_scale = [r["campaign_id"] for r in sorted([r for r in rows if r["verdict"] == "scale" and r["cpa"]], key=lambda r: r["cpa"])[:2]]
    if not k["pre_event"] and tg:
        gap = tg["attended"] - k["attended"]
        if gap > 0:
            out.append(dict(id="gap", severity="high", campaign_id=None,
                            title=f"Attendee goal missed by {gap:,} ({k['attended']:,} vs {tg['attended']:,})",
                            evidence=f"Verified external attendees {k['attended']:,}; goal {tg['attended']:,} ({tg['version']}).",
                            recommendation="Close the gap through the highest-ROI campaigns and the confirm-to-attend step (see below).",
                            task=None))
    for r in rows:
        if r["verdict"] == "reduce":
            out.append(dict(id=f"reduce-{r['campaign_id']}", severity="high", campaign_id=r["campaign_id"],
                            title=f"Cut spend on {r['name']}",
                            evidence=f"CPA Rs {r['cpa']:.0f} vs blended Rs {k['spend']/max(k['attended'],1):.0f}; show-up {r['show_rate']*100:.0f}%; spend Rs {r['spend']:,}.",
                            recommendation="Reduce its budget and move the money to a campaign marked 'scale'; fix show-up before reinvesting.",
                            task=dict(title=f"Reduce {r['name']} budget and reallocate to efficient channels", campaign_id=r["campaign_id"],
                                      owner_id=r["owner_id"], priority="high")))
        elif r["verdict"] == "fix" and "low_show_rate" in r["flags"]:
            out.append(dict(id=f"fix-{r['campaign_id']}", severity="medium", campaign_id=r["campaign_id"],
                            title=f"Fix attendance leak in {r['name']}",
                            evidence=f"Only {r['show_rate']*100:.0f}% of {r['registered']:,} registrants attended.",
                            recommendation="Add reminders and a confirm step before the event for this audience.",
                            task=dict(title=f"Add reminder + confirm step for {r['name']} registrants", campaign_id=r["campaign_id"],
                                      owner_id=r["owner_id"], priority="medium")))
        elif r["verdict"] == "fix":
            out.append(dict(id=f"fixr-{r['campaign_id']}", severity="medium", campaign_id=r["campaign_id"],
                            title=f"Fix funnel leak in {r['name']}",
                            evidence=f"Registration rate {(r['reg_rate'] or 0)*100:.0f}% of identified people.",
                            recommendation="Review the registration form and follow-up for this campaign.",
                            task=dict(title=f"Review registration flow for {r['name']}", campaign_id=r["campaign_id"],
                                      owner_id=r["owner_id"], priority="medium")))
        elif r["verdict"] == "scale" and r["campaign_id"] in top_scale:
            out.append(dict(id=f"scale-{r['campaign_id']}", severity="opportunity", campaign_id=r["campaign_id"],
                            title=f"Scale {r['name']}",
                            evidence=f"CPA Rs {r['cpa']:.0f}" + (f", show-up {r['show_rate']*100:.0f}%" if r['show_rate'] else "")
                                     + f", {r['attended']:,} attendees on Rs {r['spend']:,}.",
                            recommendation="Increase budget/capacity gradually (diminishing returns expected) and watch CPA weekly.",
                            task=dict(title=f"Increase {r['name']} budget; set weekly CPA check", campaign_id=r["campaign_id"],
                                      owner_id=r["owner_id"], priority="medium")))
    over = [r for r in rows if r["tasks_overdue"]]
    for r in over:
        out.append(dict(id=f"overdue-{r['campaign_id']}", severity="medium", campaign_id=r["campaign_id"],
                        title=f"{r['tasks_overdue']} overdue task(s) on {r['name']}",
                        evidence=f"Open tasks {r['tasks_open']}, overdue {r['tasks_overdue']} as of {d}.",
                        recommendation="Unblock or re-plan these before adding new work.", task=None))
    if tg and k["budget_headroom"] is not None and k["budget_headroom"] < 0:
        out.append(dict(id="budget", severity="high", campaign_id=None,
                        title=f"Planned budgets exceed the approved limit by Rs {-k['budget_headroom']:,}",
                        evidence=f"Sum of plan budgets Rs {k['plan_budget']:,} vs limit Rs {tg['budget']:,}.",
                        recommendation="Trim the lowest-ROI campaign budgets.", task=None))
    sev = {"high": 0, "medium": 1, "opportunity": 2}
    out.sort(key=lambda x: sev.get(x["severity"], 3))
    return out


def rate_card(d):
    """Funnel conversion at each stage for the whole event, anonymous and identified."""
    k = kpis(d)
    return dict(anonymous=[("Impressions", k["impressions"]), ("Clicks", k["clicks"]),
                           ("Landing sessions", k["sessions"]), ("Form starts", k["form_starts"])],
                identified=[("Identified people", k["identified"]), ("Registered", k["registered"]),
                            ("Confirmed", k["confirmed"]), ("Attended (verified)", k["attended"])])
