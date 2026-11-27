"""Run:  python -m pytest -q   (or  python tests/test_core.py)
Independent re-computation of the headline numbers straight from the workbook, compared with the app's analytics,
plus checks on the no-look-ahead rule, the chatbot tools and persistence."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["GROWTH_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
import pandas as pd
import etl, analytics as A, chat, model as M
etl.DB = os.environ["GROWTH_DB"]; A.DB = etl.DB; chat.DB = etl.DB
etl.build(etl.DB)
X = pd.ExcelFile(etl.XLSX)

def raw(s): return X.parse(s)

def test_final_numbers_match_independent_calc():
    P, R, C = raw("People"), raw("Registrations"), raw("Check-ins").drop_duplicates("event_id")
    ext = set(P[P.person_type == "external"].person_id)
    att = C[(C.result == "admitted") & (C.verification == "verified") & C.person_id.isin(ext)].person_id.nunique()
    k = A.kpis("2025-04-20")
    assert k["attended"] == att == 2050
    assert k["registered"] == R[R.person_id.isin(ext)].person_id.nunique() == 2800
    assert k["identified"] == len(ext) == 3625
    assert k["target"]["attended"] == 2200

def test_duplicates_counted_once():
    c = A.conn(); n = c.execute("select count(*), count(distinct event_id) from checkins").fetchone(); c.close()
    assert n[0] == n[1]

def test_no_lookahead():
    k = A.kpis("2025-04-11")
    assert k["attended"] == 0 and k["pre_event"]
    assert A.targets_as_of("2025-03-14")["attended"] == 1800      # launch plan before the revision
    assert A.targets_as_of("2025-03-15")["attended"] == 2200
    assert A.kpis("2025-03-29")["registered"] < A.kpis("2025-04-20")["registered"]

def test_campaign_sums_match_totals():
    rows = A.campaigns_table("2025-04-20"); k = A.kpis("2025-04-20")
    assert sum(r["attended"] for r in rows) == k["attended"]
    assert sum(r["spend"] for r in rows) == k["spend"] == 274000

def test_model_reproduces_2025():
    assert M.preset("2025 repeat")["total"]["attended"] == 2050

def test_chat_grounding_and_refusal():
    assert "2,050" in chat.answer("how many verified attendees", [], "2025-04-20")["reply"]
    assert "can't answer" in chat.answer("what was the revenue?", [], "2025-04-20")["reply"]
    assert chat.run_tool("query_data", {"sql": "delete from tasks"}).get("error")
    assert chat.run_tool("calculate", {"expression": "93000/340"})["result"] == 93000 / 340
    out = chat.answer("create task to call clubs for college partnerships", [], "2025-04-20")
    assert out["proposals"] and A.frames()["tasks"].shape[0] == 10          # proposed, NOT saved

def test_plan_edit_changes_analytics():
    c = A.conn(); c.execute("update campaign_plan set budget_inr=30000 where campaign_id='C02'"); c.commit(); c.close(); A.bump()
    r = [x for x in A.campaigns_table("2025-04-20") if x["campaign_id"] == "C02"][0]
    assert r["plan_budget"] == 30000 and r["budget_used_pct"] > 3

if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
