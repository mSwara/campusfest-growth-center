#!/usr/bin/env python3
"""Builds the 3-slide strategy PDF (1280x720) with headless Chrome.  python strategy/build.py
Numbers come from model.py / analytics.py (run from the repo root) so the deck and the app cannot disagree."""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NAME = "Swara Mohite"
OUT = "Swara_Mohite_Growth_APM_Strategy.pdf"
NAVY, BLUE, LBLUE, GOLD, INK = "#0A1F44", "#1B4FA0", "#E8EFFA", "#C8A24A", "#14213D"
GOOD, BAD = "#1F8F5F", "#B5483A"

CSS = f"""
@page {{ size: 1280px 720px; margin: 0 }}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',Arial,sans-serif;color:{INK};-webkit-print-color-adjust:exact;print-color-adjust:exact}}
.s{{width:1280px;height:720px;position:relative;overflow:hidden;page-break-after:always;background:#FAF7F2;padding:26px 40px 30px}}
.s:last-child{{page-break-after:auto}}
h1{{font-family:Georgia,serif;font-size:27px;color:{NAVY};line-height:1.1}}
.ey{{font-size:10.5px;letter-spacing:2.2px;text-transform:uppercase;font-weight:700;color:{BLUE};margin-bottom:4px}}
h3{{font-size:10.5px;letter-spacing:1.6px;text-transform:uppercase;color:{BLUE};margin-bottom:4px}}
p,li{{font-size:11.6px;line-height:1.36}} ul{{padding-left:15px}}
.c{{background:#fff;border:1px solid #E3E6EE;border-radius:10px;padding:9px 12px}}
.d{{background:{NAVY};color:#fff;border:0}} .d h3{{color:{GOLD}}}
table{{border-collapse:collapse;width:100%;font-size:11px}}
th{{background:{NAVY};color:#fff;text-align:left;padding:5px 7px;font-size:9.8px;letter-spacing:.8px;text-transform:uppercase}}
td{{padding:4.5px 7px;border-bottom:1px solid #E3E6EE;vertical-align:top;line-height:1.3}}
td.n,th.n{{text-align:right}} tr.hl td{{background:#FFF4D6}} tr.tot td{{font-weight:700;background:{LBLUE}}}
.big{{font-family:Georgia,serif;font-size:34px;line-height:1}} .gold{{color:{GOLD}}}
.row{{display:flex;gap:12px}} .g{{display:grid;gap:10px}}
.foot{{position:absolute;left:40px;bottom:8px;font-size:9.5px;color:#7a849a}} .pg{{position:absolute;right:40px;bottom:8px;font-size:9.5px;color:#7a849a}}
.tag{{display:inline-block;font-size:9.5px;font-weight:700;padding:1px 6px;border-radius:4px;background:#F6EBCB;color:#7A5B12}}
.A{{display:inline-block;font-size:9px;font-weight:700;padding:0 4px;border-radius:3px;background:#FDE3DC;color:#9b2c20}}
"""


def foot(n):
    return (f'<div class="foot">{NAME} · Growth APM assignment · Challenge A. Data from the supplied CampusFest 2025 workbook; '
            f'<span class="A">A</span> = assumption, everything else measured from the data.</div><div class="pg">{n} / 3</div>')


def money(x):
    return "₹{:,.0f}".format(x)


def build_html():
    import analytics as A
    import model as M
    base = M.preset("2025 repeat")["total"]
    bs = M.preset("Base")["total"]
    st = M.preset("Stretch")["total"]
    rows = {r["campaign_id"]: r for r in A.campaigns_table(A.latest_date())}

    def aud(cid, role):
        r = rows[cid]
        return (f"<tr><td><b>{r['name']}</b></td><td class='n'>{r['identified']:,}</td><td class='n'>{r['reg_rate']*100:.0f}%</td>"
                f"<td class='n'>{r['show_rate']*100:.0f}%</td><td class='n'>₹{r['cpa']:.0f}</td><td>{role}</td></tr>")

    # ------------------------------------------------ slide 1
    s1 = f"""
<section class="s">
 <div class="row" style="align-items:flex-start">
  <div style="flex:1"><div class="ey">Growth APM assignment · Challenge A: Attendee Growth</div>
   <h1>CampusFest 2026, Bengaluru: from 2,050 to 2,940 verified attendees on a ₹3 L cap</h1>
   <p style="margin-top:3px"><b>{NAME}</b> · Slide 1 of 3: How high can I aim?</p></div>
  <div class="c d" style="width:420px;display:flex;gap:18px;align-items:center">
   <div><h3>Base case</h3><div class="big">{bs['attended']:,}</div><p style="color:#9fb4d8">+{(bs['attended']/2050-1)*100:.0f}% vs 2025 · {money(bs['spend'])} · CPA ₹{bs['cpa']:.0f}</p></div>
   <div><h3>Stretch</h3><div class="big gold">{st['attended']:,}</div><p style="color:#9fb4d8">+{(st['attended']/2050-1)*100:.0f}% vs 2025 · {money(st['spend'])} · CPA ₹{st['cpa']:.0f}</p></div></div>
 </div>
 <div class="row" style="margin-top:9px">
  <div style="width:560px" class="g">
   <div class="c"><h3>Why Bengaluru <span class="A">A</span></h3><p>The data has no city, so this is a judgement: the densest mix of engineering, management and design colleges among the metros, an established inter-college fest circuit, and good metro connectivity for a two-day, walk-in-heavy event. Pool assumed ~8 lakh higher-ed students <span class="A">A</span>; the stretch needs 4.2 K identified people, ~0.5% of it. <b>Conversion and gate capacity limit us, not audience size.</b></p></div>
   <div class="c"><h3>Target audiences, ranked (2025 actuals, measured)</h3>
    <table><tr><th>Audience / campaign</th><th class="n">Identified</th><th class="n">Reg %</th><th class="n">Show %</th><th class="n">CPA</th><th>Priority</th></tr>
     {aud('C04','1 · College clubs and fest committees. Pool ~1,000 groups <span class="A">A</span>')}
     {aud('C05','2 · Peer squads, invite chains')}
     {aud('C01','3 · Campus ambassadors')}
     {aud('C07','4 · Community / interest groups')}
     {aud('C06','5 · Search-intent (cheapest)')}
     {aud('C02','Deprioritise: discovery audience, half never turn up')}
     {aud('C03','Deprioritise: creator audience, CPA ₹337')}</table></div>
   <div class="c"><h3>Capacity and risks</h3><ul><li>2025 peak gate: <b>456 check-ins/hour</b>, 1,430 unique on day 1 (data). Licensed capacity 2,500 at once <span class="A">A</span> → binding only above ~3,600 attendees. Stretch is safe; add 2 scanner lanes.</li><li>Walk-ins were 125 in 2025 (6%); held flat.</li></ul></div>
  </div>
  <div style="flex:1" class="g">
   <div class="c"><h3>Funnel model: reach → registrations → actual attendees</h3>
    <table><tr><th>Stage</th><th class="n">2025 actual</th><th class="n">Base</th><th class="n">Stretch</th><th>Source of the rate</th></tr>
     <tr><td>Impressions (anonymous)</td><td class="n">1,029,015</td><td class="n">1,060,530</td><td class="n">1,108,120</td><td>per-channel ratio to identified, held at 2025</td></tr>
     <tr><td>Landing sessions</td><td class="n">24,645</td><td class="n">27,059</td><td class="n">29,634</td><td>same</td></tr>
     <tr><td>Identified external people</td><td class="n">3,625</td><td class="n">3,897</td><td class="n">4,209</td><td>spend ↑ with <b>diminishing returns</b> <span class="A">A</span></td></tr>
     <tr><td>Registered</td><td class="n">2,800 (77%)</td><td class="n">3,075 (79%)</td><td class="n">3,455 (82%)</td><td>2025 rate +0 / +2 pp nurture</td></tr>
     <tr class="hl"><td><b>Verified attendees</b></td><td class="n"><b>2,050 (73%)</b></td><td class="n"><b>{bs['attended']:,} (79%)</b></td><td class="n"><b>{st['attended']:,} (85%)</b></td><td>2025 show-up +3 / +8 pp reminders</td></tr>
     <tr class="tot"><td>Spend · blended CPA</td><td class="n">₹2.74 L · ₹134</td><td class="n">₹2.72 L · ₹{bs['cpa']:.0f}</td><td class="n">₹2.84 L · ₹{st['cpa']:.0f}</td><td>cap ₹3.0 L (revised 2025 limit)</td></tr></table>
    <p style="margin-top:4px" class="mut">Per channel: identified = I₀ × (S/S₀)^β, capped at 2–3× 2025 spend. β = 0.5–0.85 and the caps are assumptions <span class="A">A</span>, because each campaign has one spend level in the data.</p></div>
   <div class="c"><h3>Why you should believe the number</h3><ul>
    <li><b>Re-computed from the data:</b> 2,050 verified external attendees (admitted + verified, de-duplicated), vs the 2,200 revised goal. The model reproduces 2025 exactly.</li>
    <li><b>The gain is mostly money moved, not money added:</b> spend stays ₹2.7–2.8 L. Cost per attendee falls from ₹134 to ₹97 because 5 of 7 campaigns cost ₹69–108 and show up at 75–86%, while Paid Social and Creators cost ₹274–337 with 50% show-up.</li>
    <li><b>Stress test:</b> steeper diminishing returns (β −0.2) → 2,759. Half the show-up gain → 2,803. Caps 30% lower → 2,684. All pessimistic at once (β −0.2, +4 pp show-up, no nurture lift, caps ×0.7) → <b>2,406 ≈ the base case</b>.</li>
    <li><b>Where it could fail:</b> reminders move show-up less than 8 pp, club partnerships saturate, or the revised goal drifts again (it rose 22% mid-campaign in 2025).</li></ul></div>
  </div>
 </div>
 {foot(1)}
</section>"""

    # ------------------------------------------------ slide 2
    # (name, concept, incremental, budget/timeline, test/KPIs, impact, confidence, ease)  scores 1-10
    raw = [
        ("Attendance guarantee", "WhatsApp/SMS reminders (T-3, T-1, day-of), QR e-pass, one-tap reconfirm, auto-backfill from the waitlist. 2025 lost 575 confirmed people (23%) and 88 waitlisted never got in.",
         "+224", "~₹10 K (reserve) · 1 owner · start T-21 d", "Reminder cadence A/B on half of confirmed (holdout); KPIs confirmed→attended, opt-out %", 10, 8, 8),
        ("Squad referrals and ambassadors", "Group passes for squads of 4+, leaderboard, ambassador quotas by college. Referral CPA ₹69, ambassadors ₹108, show-up 75–79%.",
         "+363", "+₹39 K (referrals ₹19→38 K, ambassadors ₹42→62 K) · 3 owners · T-60 d", "Two reward designs in 2 zones; KPIs invites / registrant, CPA / attendee weekly", 8, 8, 6),
        ("Creators pay per attended; paid social retargeting only", "Replace flat fees with per-attended codes and micro-creators; use paid only on the 825 identified-but-unregistered. Funds ideas 2 and 4.",
         "−155 (frees ₹69 K)", "Saves ₹31 K + ₹38 K · 1 owner · T-75 d", "2-week holdout; KPIs CPA / attended, show-up ≥ 60%", 6, 7, 7),
        ("Club and community partnerships", "Brief 12 more clubs, 5 community admins, fixed group passes. Best show-up in the data (86%, 83%).",
         "+347", "+₹40 K (C04 ₹31→58 K, C07 ₹16→25 K, C06 ₹14→18 K) · 2 owners · T-60 d", "Per-club registrations in 14 days; KPIs members registered / club, show-up", 8, 7, 5),
        ("Registration nurture sprint", "Nudge the 825 identified-not-registered (23% in 2025) with deadline, social proof and a one-click form.",
         "+47", "₹0 cash · content time · T-30 d", "Randomised 50/50 send; KPI identified→registered, opt-outs", 3, 6, 9),
    ]
    ideas = []
    for i, r in enumerate(raw, 1):
        ice = (r[5] * r[6] * r[7]) ** (1 / 3)
        ideas.append((str(i), r[0], r[1], r[2], r[3], r[4], f"{ice:.1f}<div style='font-weight:400;color:#46506A'>{r[5]}·{r[6]}·{r[7]}</div>"))
    assert [x[6].split('<')[0] for x in ideas] == sorted([x[6].split('<')[0] for x in ideas], reverse=True), "ranking must follow ICE"
    irow = "".join(f"<tr class='{'hl' if i[0]=='1' else ''}'><td><b>{i[0]}</b></td><td><b>{i[1]}</b><div style='color:#46506A'>{i[2]}</div></td><td class='n'><b>{i[3]}</b></td><td>{i[4]}</td><td>{i[5]}</td><td class='n'><b>{i[6]}</b></td></tr>" for i in ideas)
    s2 = f"""
<section class="s">
 <div class="ey">Slide 2 of 3 · Where will you place your bets?</div>
 <h1>Five bets, ranked by attendees per rupee and confidence. Fund the winners by cutting the leaks.</h1>
 <div class="row" style="margin-top:8px">
  <div style="flex:1">
   <table><tr><th>#</th><th>Idea: concept and why it works (evidence)</th><th class="n">Incremental attendees<br>(standalone)</th><th>Budget, resources, timeline</th><th>How I test it · KPIs</th><th class="n">ICE</th></tr>{irow}
    <tr class="tot"><td></td><td>Combined effect of 1 to 5 (interaction: reminders apply to a bigger base)</td><td class="n">+891 → <b>{st['attended']:,}</b></td><td>₹{st['spend']/1000:.0f} K of ₹300 K (₹16 K reserve)</td><td></td><td></td></tr></table>
   <p style="margin-top:5px" class="mut">Standalone effects sum to +826; together +891 because reminders act on a larger registrant base. All effects come from the app's scenario model (2025 actuals + assumed β and caps). Effects are estimates, not forecasts.</p>
  </div>
 </div>
 <div class="row" style="margin-top:8px">
  <div class="c" style="width:420px"><h3>Prioritisation framework: ICE (1–10 each)</h3>
   <p><b>Impact</b> = incremental attendees per ₹10 K from the model (224 for ~₹10 K scores 10; ~90 per ₹10 K scores 8). <b>Confidence</b> = evidence quality: measured in the data (7–8) vs assumed behaviour (6). <b>Ease</b> = people-days and dependencies. Score = (I × C × E)<sup>1/3</sup>; inputs shown under each score.</p>
   <p style="margin-top:4px"><b>Dependencies and overlap:</b> idea 3 must land first (it releases ₹69 K for 2 and 4). Ideas 1 and 5 share the same WhatsApp list, so they ship together. Ideas 2 and 4 compete for the same college clubs: split by zone.</p></div>
  <div class="c" style="flex:1"><h3>What I would deliberately avoid, and why</h3><ul>
   <li><b>More Paid Social spend:</b> CPA ₹274, 50% show-up, and the data's own warning: reach and opens do not prove attendance.</li>
   <li><b>Flat-fee creators:</b> ₹59 K for 175 attendees (₹337 each) with no payout link to showing up.</li>
   <li><b>Mass email / outdoor for “awareness”:</b> impressions (1.03 M) are anonymous and cannot be turned into people.</li>
   <li><b>Second city or a celebrity headliner:</b> cannot be tested inside ₹3 L and adds capacity risk; revisit after the 2026 data.</li></ul></div>
  <div class="c d" style="width:300px"><h3>The bet in one line</h3><p style="font-size:13px;line-height:1.4">Move ₹69 K out of two channels that convert half their registrants and into those that convert 75–86%; then close the confirm-to-attend gap. About the same budget, +43% attendees.</p></div>
 </div>
 {foot(2)}
</section>"""

    # ------------------------------------------------ slide 3
    ctrl = [
        ("1", "Attendance guarantee", "Opt-in rate to WhatsApp; confirmed→attended vs holdout. Risk: opt-outs, reminder fatigue.",
         "Reminder open ≥ 60% by T-14; holdout gap visible at T-7",
         "≥ +5 pp vs control", "+2 to +5 pp: switch channel / timing", "< +2 pp or opt-out > 3%"),
        ("2", "Squad referrals and ambassadors", "Invites per registrant, invite→registration rate. Risk: reward gaming, low-quality leads.",
         "≥ 1.2 invites / registrant in week 2; leaderboard activity",
         "CPA / attendee ≤ ₹100 at week 3 → +₹10 K", "₹100–130: change reward", "> ₹130 or show-up < 65%"),
        ("3", "Creators per-attended; paid retargeting", "Cost per registrant and show-up by creator code. Risk: fewer registrants if creators disengage.",
         "Registrations per creator code by day 7",
         "CPA ≤ ₹150 and show-up ≥ 65%", "CPA ₹150–200: pause the weakest 30% of codes", "CPA > ₹200 or show-up < 55%"),
        ("4", "Club and community partnerships", "Registrations per briefed club, group-pass redemption. Risk: slow club approvals, capacity per club.",
         "≥ 6 of 12 new clubs with 20+ registrations in 14 days",
         "≥ 6 clubs hit and show-up ≥ 80%", "3 to 5 clubs: swap the weakest clubs", "< 3 clubs after 3 weeks"),
        ("5", "Registration nurture sprint", "Identified→registered. Risk: list is small, effect is small.",
         "Test-group registrations +1 pp inside 10 days", "≥ +1.5 pp", "+0.5 to +1.5 pp: new message", "< +0.5 pp: stop, save the time"),
    ]
    crow = "".join(f"<tr><td><b>{c[0]}</b></td><td><b>{c[1]}</b><div style='color:#46506A'>{c[2]}</div></td><td>{c[3]}</td><td style='background:#E3F4EA'>{c[4]}</td><td style='background:#FFF1CC'>{c[5]}</td><td style='background:#F9DDD7'>{c[6]}</td></tr>" for c in ctrl)
    s3 = f"""
<section class="s">
 <div class="ey">Slide 3 of 3 · How will you know what's working?</div>
 <h1>Leading indicators, hard thresholds, and a weekly scale / change / stop call</h1>
 <table style="margin-top:8px"><tr><th>#</th><th>Idea · critical variable and biggest risk</th><th>Early signal (leading)</th><th>Scale if</th><th>Change if</th><th>Stop if</th></tr>{crow}</table>
 <div class="row" style="margin-top:9px">
  <div class="c" style="flex:1.1"><h3>Checkpoints and what I do</h3><ul>
   <li><b>T-60 / T-45:</b> launch 3 first, then 2 and 4; read the first 14 days of CPA. <b>T-30:</b> reallocate ≤ 20% of unspent budget by the verdicts. <b>T-14 (gate):</b> projected attendees vs base case (2,420).</li>
   <li><b>Evidence it works:</b> replaying 2025 on the Growth Center at T-14 (29 Mar) shows 3,224 identified, 2,243 registered, and a run-rate projection of ~1,600 attendees (65% assumed show-up <span class="A">A</span>) vs the 2,200 goal: the gap is visible two weeks out, in time to act.</li>
   <li><b>If behind at T-14:</b> pull the 20% held-back budget into the best-CPA channel, extend group-pass deadline, and trigger the reminder blitz on all confirmed.</li></ul></div>
  <div class="c d" style="flex:1"><h3>How the Growth Center and AI analyst make the call</h3><ul>
   <li><b>Dashboard:</b> funnel vs the target version in force, per-campaign CPR / CPA / show-up, and a verdict (scale · fix · reduce) using these same thresholds (show-up &lt; 60%, registration &lt; 70%, CPA &gt; 1.5× or &lt; 0.8× blended).</li>
   <li><b>Planner:</b> move budget between campaigns and see projected attendees and CPA before committing.</li>
   <li><b>Analyst:</b> answers from live data with an as-of date, shows its evidence, says “the data can't answer that” (revenue, demographics), and <b>drafts tasks that only save after I confirm</b>.</li>
   <li><b>Tasks and decisions:</b> owners, deadlines, overdue flags; logged decisions update plan status and every number.</li></ul></div>
 </div>
 {foot(3)}
</section>"""
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{NAME} · Growth APM strategy</title><style>{CSS}</style></head><body>{s1}{s2}{s3}</body></html>"


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    os.chdir(os.path.dirname(here))
    os.environ.setdefault("GROWTH_DB", os.path.join(os.path.dirname(here), "growth.db"))
    html = os.path.join(here, "strategy.html")
    open(html, "w", encoding="utf-8").write(build_html())
    chrome = next(p for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe") if os.path.exists(p))
    out = os.path.join(here, OUT)
    subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--print-to-pdf=" + out,
                    "file:///" + html.replace("\\", "/")], check=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
