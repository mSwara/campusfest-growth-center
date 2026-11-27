# CampusFest Growth Center (Challenge A: Attendee Growth)

A working command center for an attendee-growth campaign: funnel analytics, campaign diagnosis, a task/plan manager,
a scenario planner, and an embedded AI analyst that works on the live database.

- **Strategy deck:** `strategy/Swara_Mohite_Growth_APM_Strategy.pdf` (3 slides; rebuild with `python strategy/build.py`)
- **Data:** the supplied `data/Attendee Dataset.xlsx` (CampusFest 2025, synthetic). The original workbook is kept untouched in `data/`;
  the database is rebuilt from it on first run or with the **Reset** button.

## Run it

```bash
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export GEMINI_API_KEY=your_key                     # optional, free key from Google AI Studio. Windows: set GEMINI_API_KEY=...
python app.py                                      # http://localhost:5000
python tests/test_core.py                          # 7 checks, all must print "ok"
```

Deploy: `render.yaml` / `Procfile` / `Dockerfile` are included (Render, Railway, Fly, any Docker host). Set `GEMINI_API_KEY` as a secret.
Free hosts have an ephemeral disk: edits persist while the service runs but reset on redeploy. For permanent storage mount a disk and set `GROWTH_DB=/path/growth.db`.

## What is in the product (mapped to the brief)

| Brief | Where |
|---|---|
| 1 Measure performance | **Overview**: KPIs vs the target version in force on the as-of date, cumulative growth chart, identified funnel and anonymous traffic, budget used, projected outcome. **As-of date picker** (with Latest and T-14 buttons) rebuilds every number as of the end of that day. |
| 2 Diagnose | **Campaigns**: per-campaign funnel, registration %, show-up %, CPR, CPA, plan attainment, and a verdict (scale / fix / reduce / hold) with the flags that caused it. |
| 3 Support decisions | **Insights** panel (ranked, with evidence and a recommended action), **Planner** (move budget between campaigns and see projected attendees and CPA), **Decision log**. |
| 4 Manage execution | **Tasks** (owner, due date, priority, status, campaign), editable **plan budget / attendee target** per campaign, **Data entry** (add a day of marketing activity, quick-add a person). All writes go to SQLite and every metric recomputes. |
| 5 Embedded AI analyst | Docked chat. Tool-calling over live data, evidence shown for each answer, follow-ups, refuses what the data cannot support, drafts tasks that are saved only after you click Confirm. |

### One complete workflow (insight → action)
1. Overview shows the goal was missed by 150 (2,050 vs 2,200). Campaigns marks **Paid Social** and **Creator Partners** as `reduce` (CPA ₹274 / ₹337, show-up 50%).
2. Ask the analyst: *“Which campaign has the worst cost per attendee?”* → *“and its show rate?”* (follow-up) → *“what if we move 20k from Paid Social to Student Referrals?”* (scenario model).
3. Say *“create task to cut Paid Social budget for Paid Social”*. A proposal card appears; **Confirm & add**. The task appears in Tasks with an owner, and the overdue / open counters in Campaigns update.
4. Log the decision (Insights → Log decision) or edit the campaign's budget in Campaigns; the budget-used % and the planned-budget headroom update immediately.
5. Switch the as-of date to **T-14 (29 Mar)** to see the same product doing the early-warning job: ~1,600 projected attendees vs the 2,200 goal.

## Definitions and data cleaning (from the workbook's own Read me)

- Exact repeated records (same stable ID, import retries) are counted once: 20 check-ins, 4 registration-history rows, 2 daily rows. Dedup in `etl.py`.
- Time is IST; **as-of day D = end of day D**. No query uses anything later (tested in `tests/test_core.py::test_no_lookahead`). The targets version in force is the latest `effective_at` on or before D (launch plan 1,800 attendees → revised plan 2,200 from 15 Mar).
- Only `person_type = external` counts toward goals (the data also has internal, staff, test).
- **Identified** = distinct external people with `first_seen_at` ≤ D. **Registered** = distinct external people with a registration ≤ D. **Confirmed** = registered people whose latest status ≤ D is `confirmed`. **Attended** = distinct external people with an `admitted` AND `verified` check-in ≤ D (pending, denied, unverified and duplicates excluded). Names are not keys; `person_id` is.
- Campaign attribution = the source recorded on each record (first campaign for identified, registration source for registered, check-in campaign for attended); empty on check-ins = unattributed walk-ins (125). Alternative attribution (e.g. last-touch) is not used because the data has no touch sequence per person.
- Impressions, clicks, reach, landing sessions and form starts are **anonymous**; they are shown as traffic, never summed into people.
- Spend = net posted INR (debits minus credits), deduplicated. CPR = spend / registered; CPA = spend / verified attendees.
- Before the event, attendance and show-up are shown as “not yet known”, and the projection uses an **assumed** 65% show-up (not this event's outcome, to avoid look-ahead).

### 2025 actuals (all re-computed independently in the tests)

| | Identified | Registered | Attended | Spend | Reg % | Show % | CPA |
|---|---|---|---|---|---|---|---|
| Campus Ambassadors | 600 | 520 | 390 | ₹42,000 | 87% | 75% | ₹108 |
| Paid Social | 960 | 680 | 340 | ₹93,000 | 71% | 50% | ₹274 |
| Creator Partners | 490 | 350 | 175 | ₹59,000 | 71% | 50% | ₹337 |
| College Partnerships | 500 | 450 | 385 | ₹31,000 | 90% | 86% | ₹81 |
| Student Referrals | 410 | 350 | 275 | ₹19,000 | 85% | 79% | ₹69 |
| Organic Search | 290 | 250 | 195 | ₹14,000 | 86% | 78% | ₹72 |
| Community Groups | 250 | 200 | 165 | ₹16,000 | 80% | 82% | ₹97 |
| Walk-ins (no campaign) | 125 | – | 125 | – | | | |
| **Total** | **3,625** | **2,800** | **2,050** | **₹2,74,000** | 77% | 73% | ₹134 |

Goals (revised plan): 3,600 identified, 3,200 registered, 2,200 attended, ₹3,00,000 budget.
Other facts used: 2,500 externals confirmed → 1,925 attended (575 lost); 183 cancelled; 88 waitlisted (none attended); 825 identified but never registered; peak gate load 456 check-ins/hour; 1,430 unique visitors on day 1.

## Strategy model (slide 1 and the Planner)

Per campaign *c*, with 2025 spend S₀, identified I₀, registration rate r, show-up rate s (all measured):

```
identified(c) = I0 * (min(S/S0, cap_c)) ^ beta_c          diminishing returns, capped by channel capacity
registered(c) = identified * min(r + reg_uplift, 0.97)
attended(c)   = registered * min(s + show_uplift, 0.95)
total         = sum over campaigns + 125 walk-ins (held flat)
```

`beta` (0.5–0.85) and `cap` (1.8–3.0× 2025 spend) are **assumptions**: each campaign has one spend level in the data, so elasticity cannot be estimated. The model reproduces 2025 exactly (2,050) when given 2025 spend and no uplifts.

| Scenario | Budgets (C01..C07, ₹ K) | Show-up | Reg | Attended | Spend | CPA |
|---|---|---|---|---|---|---|
| 2025 repeat | 42 / 93 / 59 / 31 / 19 / 14 / 16 | +0 | +0 | 2,050 | ₹2.74 L | ₹134 |
| Base | 52 / 70 / 40 / 45 / 28 / 17 / 20 | +3 pp | +0 | 2,419 | ₹2.72 L | ₹112 |
| Stretch | 62 / 55 / 28 / 58 / 38 / 18 / 25 | +8 pp | +2 pp | 2,941 | ₹2.84 L | ₹97 |

Stress tests on the stretch: β −0.2 → 2,759; half the show-up gain → 2,803; caps ×0.7 → 2,684; all pessimistic at once (β −0.2, +4 pp, no registration lift, caps ×0.7) → 2,406, about the base case.

Idea contributions (standalone vs 2025): attendance guarantee +224; squad referrals and ambassadors +363 (+₹39 K); club and community partnerships +347 (+₹40 K); cut creators and paid social −155 (frees ₹69 K); registration nurture +47. Sum +826; combined +891 because reminders act on a larger base.

## Prioritisation framework

ICE with a geometric mean: score = (Impact × Confidence × Ease)^(1/3), each 1–10. Impact is attendees per ₹10 K from the model; Confidence is higher where the number is measured in the data than where behaviour is assumed; Ease reflects people-days and dependencies. Inputs are printed under each score on slide 2.

## How the AI analyst works (and how it is kept honest)

- **With `GEMINI_API_KEY`:** Gemini function-calling. Tools: `get_kpis`, `get_campaigns`, `get_insights`, `query_data` (one read-only SELECT on the app database), `calculate` (exact arithmetic), `list_tasks`, `project_scenario`, `propose_task`. The system prompt carries the data dictionary and rules: ground every number in a tool result, state the as-of date, separate evidence from assumptions, say so when the data cannot answer (revenue, demographics, city, sentiment…), and never claim a task was created.
- **Without a key:** an offline analyst routes the question to the same tools and computes the answer from the live database. It is deliberately narrower (funnel vs target, a campaign's metrics, rankings, bottlenecks, recommendations, tasks, a two-campaign budget what-if, arithmetic) and replies honestly when a question falls outside the data or its scope.
- **Execution is confirm-first:** `propose_task` only returns a proposal; the UI shows a card, and nothing is written until the user clicks Confirm.
- **Evidence is visible:** each reply has an expandable list of the tools called.
- **Model:** default `gemini-3.8-flash`, override with `GEMINI_MODEL`.

## Tools and what I reused / modified / verified

- **Stack:** Python 3, Flask, SQLite, pandas/openpyxl, `requests`; vanilla JS with inline SVG charts (no front-end framework, no CDN). Optional Gemini via the REST API (free tier).
- **Development tools:** Python, Flask, SQLite, VS Code. Every headline number is checked by an independent recomputation in `tests/test_core.py`.
- **Reused:** the supplied workbook (unmodified in `data/`). No external datasets, templates or UI kits.
- **Verified:** funnel totals vs an independent pandas recomputation; dedup; the no-look-ahead rule (targets version change on 15 Mar, zero attendance before the event); campaign sums equal totals; the model reproduces 2025; plan edits change analytics; the analyst grounds answers, refuses unanswerable questions, rejects non-SELECT SQL, and proposes without saving. The Gemini loop was tested against a stubbed Gemini response, **not against the live API** (no key was available while building).

## Sourced facts vs assumptions

**Sourced (from the workbook):** every 2025 funnel, spend, status and check-in number; targets and their revision; campaign owners. **Assumptions (marked A in the deck):** Bengaluru as the city (the data has no city); ~8 lakh higher-ed student pool and ~1,000 clubs; licensed venue capacity 2,500; diminishing-return β and channel caps; the show-up and registration uplifts from reminders and nurture; 65% show-up used for pre-event projections; the seeded per-campaign plan budgets (₹2.8 L of ₹3 L) and attendee targets (sum 2,200); seeded tasks.

## Known limitations

- Synthetic single-edition data: the model is calibrated on one event, so it cannot estimate elasticity or seasonality. Treat projections as directional.
- The pre-event projection is a simple last-7-day run rate, which understates the late surge seen in 2025.
- No login or multi-user permissions; one shared SQLite file. Writes are not audited beyond `updated_at`, the decision log, and the chat log.
- The offline analyst is rule-based and narrower than the Gemini path; the Gemini path has not been exercised against the live API.
- Attribution is single-source per person; multi-touch effects are not measurable from this data.
- The T-14 snapshot uses the same seeded tasks and plan as the final one; the data does not record historical plan or task states.
