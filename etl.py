"""Load the supplied CampusFest attendee workbook into SQLite.

Cleaning rules (all from the workbook's own 'Read me'):
  * exact repeated records (same stable ID, import retries) are counted once
  * timestamps are IST; 'as of D' later means the end of day D
  * only person_type = external counts toward attendee goals
  * actual attendance = result 'admitted' AND verification 'verified'
Run directly to (re)build growth.db from the original workbook.
"""
import os
import sqlite3
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
XLSX = os.path.join(HERE, "data", "Attendee Dataset.xlsx")
DB = os.environ.get("GROWTH_DB", os.path.join(HERE, "growth.db"))

SHEETS = {
    "Event": "event", "Targets": "targets", "Campaigns": "campaigns", "Daily Marketing": "campaign_daily",
    "People": "people", "Interest and Engagement": "interactions", "Registrations": "registrations",
    "Registration History": "reg_history", "Check-ins": "checkins",
}
DEDUPE_KEY = {"campaign_daily": "activity_id", "reg_history": "history_id", "checkins": "event_id",
              "interactions": "interaction_id", "registrations": "registration_id", "people": "person_id"}

MGMT_SCHEMA = """
CREATE TABLE IF NOT EXISTS campaign_plan (
  campaign_id TEXT PRIMARY KEY, budget_inr INTEGER NOT NULL, attendee_target INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'active', notes TEXT DEFAULT '', updated_at TEXT);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, campaign_id TEXT, owner_id TEXT,
  due_date TEXT, status TEXT NOT NULL DEFAULT 'todo', priority TEXT NOT NULL DEFAULT 'medium',
  notes TEXT DEFAULT '', source TEXT DEFAULT 'manual', created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT, decision TEXT NOT NULL, rationale TEXT,
  as_of TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS scenarios (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, config TEXT NOT NULL, result TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS chat_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, content TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

# Seed plan (assumption, documented in README): approved budget split of the Rs 3.0 L cap, and per-campaign
# attendee targets that add up to the revised 2,200 goal.
PLAN_SEED = {
    "C01": (45000, 400), "C02": (90000, 450), "C03": (55000, 300), "C04": (35000, 350),
    "C05": (20000, 250), "C06": (15000, 200), "C07": (20000, 150),
}
TASK_SEED = [
    ("Pause new Paid Social creatives until show-up improves", "C02", "T04", "2025-04-25", "in_progress", "high"),
    ("Switch creator deals from flat fee to per-attended payout", "C03", "T05", "2025-04-28", "todo", "high"),
    ("Brief 12 more college clubs; offer group passes", "C04", "T03", "2025-05-02", "in_progress", "high"),
    ("Launch referral leaderboard with squad passes", "C05", "T06", "2025-04-22", "done", "medium"),
    ("Set up WhatsApp reminder flow (T-3, T-1, day-of)", None, "T04", "2025-05-09", "todo", "high"),
    ("Waitlist backfill: confirm waitlisted people when cancellations arrive", None, "T06", "2025-05-12", "todo", "medium"),
    ("Refresh Organic Search landing page with schedule + FAQ", "C06", "T04", "2025-05-05", "todo", "medium"),
    ("Recruit 5 community group admins for day-1 meetups", "C07", "T05", "2025-05-07", "blocked", "medium"),
    ("Ambassador weekly check-in: new registrations per ambassador", "C01", "T03", "2025-04-18", "done", "low"),
    ("Prepare scanner + manual desk plan for peak hours (10-12, 18:00)", None, "T06", "2025-05-16", "todo", "medium"),
]


def build(db_path=DB, force=True):
    if force and os.path.exists(db_path):
        os.remove(db_path)
    con = sqlite3.connect(db_path)
    xl = pd.ExcelFile(XLSX)
    for sheet, table in SHEETS.items():
        df = xl.parse(sheet)
        for col in df.columns:
            if str(df[col].dtype).startswith("datetime"):
                df[col] = df[col].dt.strftime("%Y-%m-%d %H:%M:%S")
        if table in DEDUPE_KEY:
            df = df.drop_duplicates()                      # exact import copies
            df = df.drop_duplicates(subset=[DEDUPE_KEY[table]])
        df.to_sql(table, con, index=False, if_exists="replace")
    con.executescript(MGMT_SCHEMA)
    now = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    for cid, (b, t) in PLAN_SEED.items():
        con.execute("INSERT OR REPLACE INTO campaign_plan VALUES (?,?,?,?,?,?)", (cid, b, t, "active", "", now))
    for title, cid, oid, due, st, pr in TASK_SEED:
        con.execute("INSERT INTO tasks (title,campaign_id,owner_id,due_date,status,priority,source,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)", (title, cid, oid, due, st, pr, "seed", now, now))
    con.execute("INSERT OR REPLACE INTO meta VALUES ('built_at', ?)", (now,))
    con.commit()
    con.close()
    return db_path


if __name__ == "__main__":
    print("built", build(force=True))
    sys.exit(0)
