"""Manual test: simulate auto-load flow against the running app's DB."""
# First, connect to the DB
from fisher.dash_app.services import get_db, get_auto_load_service

db = get_db()

# Step 1: Check current state
phase = db.query_df("SELECT value FROM auto_load_status WHERE key='phase'")
print("Current phase:", phase["value"].to_list()[0] if len(phase) > 0 else "no table")
count = db.query_df("SELECT COUNT(*) as c FROM bars_daily")
print("bars_daily rows:", count["c"].to_list()[0])

# Step 2: Simulate click
svc = get_auto_load_service()
svc.set_status("phase", "initial_load")
svc.set_status("current", "0")
svc.set_status("total", "0")
print("\nPhase set to initial_load")

# Step 3: Run initial_load
import time
t0 = time.time()
result = svc.initial_load()
elapsed = time.time() - t0
print(f"initial_load result: {result}")
print(f"Elapsed: {elapsed:.1f}s")

# Step 4: Check bars_daily
count2 = db.query_df("SELECT COUNT(*) as c FROM bars_daily")
print(f"bars_daily after: {count2['c'].to_list()[0]} rows")
