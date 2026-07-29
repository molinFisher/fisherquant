# Data Center Emergency Fix — Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development.

**Goal:** Fix 3 P0 callback conflicts and 5 P1 usability issues in the data center.

**Architecture:** Remove duplicate callbacks, search via service layer, support minute/financials data types, non-blocking auto-load via scheduler.

**Tech Stack:** Dash 4+, duckdb, akshare, APScheduler

## Global Constraints
- Delete duplicate callback code, keep service-layer versions
- HK search via `DataCenterService.search_symbols()`
- Data type dispatch in `DataCenterService.fetch_bars()`
- Fetch progress via `dcc.Store` + `dcc.Interval` polling
- Auto-load progress polling reads `auto_load_status` table only, no inline network calls

---

### Task 1: Remove duplicate callbacks from data_callbacks.py (P0)

**Files:**
- Modify: `FisherQuant/fisher/dash_app/callbacks/data_callbacks.py` (delete cache/export/adj callbacks)
- Modify: `FisherQuant/fisher/dash_app/callbacks/routing.py` (verify registrations)

**Changes:**
Remove from `data_callbacks.py`:
- `force_refresh_cached` callback body (cache-refresh-btn → cached-table-container)
- `render_cached_table` callback body (cache-* inputs → cached-table-container)
- `delete_selected_rows` callback body (cache-delete-btn → cached-table-container)
- Export callback body (export-* → download-data)
- Adj factor callback body (adj-* → adj-factor-result)
- Remove all now-unused imports (`polars`, `duckdb`, `io`, etc.)
- Remove helper functions: `_resolve_symbols`, `_fetch_bars_sync`, `_store_bars`

Verify `routing.py` still registers `data_cache_callbacks` and `data_export_callbacks`.

After cleanup, `data_callbacks.py` should only contain:
- `search_symbols` 
- `update_fetch_list`
- `clear_single_search_on_batch`
- `toggle_minute_period`
- `fetch_data` callback
- `close_modal`

- [ ] **Step 1: Remove cache/export/adj callback bodies from data_callbacks.py**
- [ ] **Step 2: Verify routing.py registrations**
- [ ] **Step 3: Test** — `python -c "from fisher.dash_app.callbacks.data_callbacks import *; print('OK')"`
- [ ] **Step 4: Commit** `"fix(P0): remove duplicate cache/export/adj callbacks from data_callbacks.py"`

---

### Task 2: HK stock search + Service layer integration (P1)

**Files:**
- Modify: `FisherQuant/fisher/dash_app/callbacks/data_callbacks.py`
- Modify: `FisherQuant/fisher/dash_app/services/data_center_service.py`

**Changes:**
In `data_callbacks.py` `search_symbols` callback, replace inline `ak.stock_info_a_code_name()` with `DataCenterService.search_symbols()`:

```python
from fisher.dash_app.services import get_data_service

@app.callback(...)
def search_symbols(query):
    if not query or len(query) < 2:
        return []
    svc = get_data_service()
    return svc.search_symbols(query)
```

In `DataCenterService.search_symbols()`, verify the HK search path returns `value` as clean ticker codes (e.g., `"00700.HK"` not `"00700"`).

- [ ] **Step 1: Modify callback to use get_data_service().search_symbols()**
- [ ] **Step 2: Verify HK ticker normalization in DataCenterService**
- [ ] **Step 3: Commit** `"fix(P1): HK stock search via DataCenterService.search_symbols()"`

---

### Task 3: Minute + financials data type dispatch (P1)

**Files:**
- Modify: `FisherQuant/fisher/dash_app/services/data_center_service.py`

**Changes:**
In `DataCenterService.fetch_bars()`, add dispatch by `data_type`:

```python
def fetch_bars(self, symbols: list[str], start: str, end: str,
               data_type: str = "daily", period: str = "") -> dict:
    results = {}
    for sym in symbols:
        try:
            code = sym.replace(".SH","").replace(".SZ","").replace(".HK","")
            if data_type == "daily":
                df = ak.stock_zh_a_hist(symbol=code, period="daily",
                    start_date=start, end_date=end, adjust="qfq")
                if df is not None and not df.empty:
                    ticker = resolve_ticker(code)
                    rows = []
                    for _, r in df.iterrows():
                        rows.append([ticker, str(r["日期"])[:10],
                            float(r["开盘"]), float(r["最高"]), float(r["最低"]),
                            float(r["收盘"]), int(r["成交量"]), float(r["成交额"])])
                    self._db.execute("DELETE FROM bars_daily WHERE ticker=?", [ticker])
                    self._db.execute_many("INSERT INTO bars_daily (ticker,trade_date,open,high,low,close,volume,amount) VALUES (?,?,?,?,?,?,?,?)", rows)
                    results[sym] = {"status": "ok", "count": len(rows)}
                    
            elif data_type == "minute":
                df = ak.stock_zh_a_hist_min_em(symbol=code, period=period or "1",
                    start_date=start.replace("-",""), end_date=end.replace("-",""))
                if df is not None and not df.empty:
                    ticker = resolve_ticker(code)
                    rows = []
                    for _, r in df.iterrows():
                        rows.append([ticker, str(r["时间"]), float(r["开盘"]),
                            float(r["最高"]), float(r["最低"]), float(r["收盘"]),
                            int(r["成交量"]), float(r["成交额"])])
                    self._db.execute("DELETE FROM bars_minute WHERE ticker=?", [ticker])
                    self._db.execute_many("INSERT INTO bars_minute VALUES (?,?,?,?,?,?,?,?)", rows)
                    results[sym] = {"status": "ok", "count": len(rows)}
                    
            elif data_type == "financials":
                df = ak.stock_financial_abstract(symbol=code)
                if df is not None and not df.empty:
                    self._db.execute("CREATE TABLE IF NOT EXISTS financials (ticker VARCHAR, report_date VARCHAR, data JSON)")
                    import json
                    self._db.execute("DELETE FROM financials WHERE ticker=?", [code])
                    for _, r in df.iterrows():
                        self._db.execute("INSERT INTO financials VALUES (?,?,?)",
                            [code, str(r.iloc[0])[:10], json.dumps(r.to_dict(), ensure_ascii=False)])
                    results[sym] = {"status": "ok", "financials": True}
                    
        except Exception as e:
            results[sym] = {"status": "failed", "error": str(e)[:80]}
    return results
```

- [ ] **Step 1: Add minute/financials dispatch to fetch_bars()**
- [ ] **Step 2: Test** — `python -c "from fisher.dash_app.services.data_center_service import DataCenterService; print('OK')"`
- [ ] **Step 3: Commit** `"fix(P1): minute and financials data type dispatch in fetch_bars()"`

---

### Task 4: Fetch progress feedback (P1)

**Files:**
- Modify: `FisherQuant/fisher/dash_app/callbacks/data_callbacks.py`
- Modify: `FisherQuant/fisher/dash_app/pages/data_center.py`

**Changes:**
Add a `dcc.Store(id="fetch-progress-status")` to the data query tab layout.

Modify `fetch_data` callback to write to both `fetch-progress-status` and the final output:

```python
@app.callback(
    Output("fetch-status", "children"),
    Output("fetch-progress-status", "data"),
    Input("fetch-data-button", "n_clicks"),
    background=True,
    running=[(Output("fetch-data-button", "disabled"), True, False)],
)
def fetch_data(n_clicks):
    if not n_clicks:
        return "请先选择标的", {}
    # ... resolve symbols and fetch ...
    total = len(symbols)
    for i, sym in enumerate(symbols):
        result = svc.fetch_bars([sym], start, end, data_type, period)
        yield dash.no_update, {"current": i+1, "total": total, "symbol": sym}
    return f"完成！共 {total} 个标的", {"current": total, "total": total}
```

Add a progress bar in data_center.py that reads from `fetch-progress-status`:

```python
dcc.Interval(id="fetch-progress-poll", interval=1000),
dbc.Progress(id="fetch-progress-bar", value=0, label="0%"),
```

Add a callback to update the progress bar from the Store:

```python
@app.callback(
    Output("fetch-progress-bar", "value"),
    Output("fetch-progress-bar", "label"),
    Input("fetch-progress-poll", "n_intervals"),
)
def update_fetch_progress(n):
    data = dash.callback_context.states.get("fetch-progress-status.data", {})
    if not data:
        return 0, "0%"
    current = data.get("current", 0)
    total = data.get("total", 1)
    pct = int(current * 100 / max(total, 1))
    return pct, f"{current}/{total} ({pct}%)"
```

- [ ] **Step 1: Add dcc.Store + dcc.Interval + dbc.Progress to data_center.py layout**
- [ ] **Step 2: Modify fetch callback to yield progress**
- [ ] **Step 3: Add progress update callback**
- [ ] **Step 4: Commit** `"feat(P1): fetch progress via dcc.Store + Interval polling"`

---

### Task 5: Non-blocking auto-load + scheduler + startup check (P1)

**Files:**
- Modify: `FisherQuant/fisher/dash_app/pages/data_center.py`
- Modify: `FisherQuant/fisher/dash_app/app.py`

**Changes:**
In `data_center.py`, modify `update_auto_load_progress` to only READ status, never call `initial_load()`:

```python
def update_auto_load_progress(n):
    try:
        svc = get_auto_load_service()
        # Remove: if phase == "initial_load": svc.initial_load()
        progress = svc.get_progress()
    ...
```

In `app.py`, after app creation, schedule auto-load tasks:

```python
from fisher.dash_app.services import get_auto_load_service
from fisher.scheduler.engine import SchedulerEngine

# On first start, check if data is empty
scheduler = SchedulerEngine()
scheduler.start()

@ app.server.before_first_request
def init_on_startup():
    svc = get_auto_load_service(scheduler)
    result = svc.check_and_start()
    if result.get("phase") == "initial_load":
        # Schedule batch processing every 30 seconds
        scheduler.add_job("auto_load_batch", svc.initial_load,
                          trigger="interval", seconds=30)
    # Schedule daily incremental at 16:30
    scheduler.add_job("auto_load_daily", svc.incremental_update,
                      trigger="cron", hour=16, minute=30)
```

- [ ] **Step 1: Remove `initial_load()` call from auto-load progress callback**
- [ ] **Step 2: Add scheduler + startup check to app.py**
- [ ] **Step 3: Commit** `"fix(P1): non-blocking auto-load via scheduler, startup check in app.py"`

---

### Task 6: Schema init consistency (C6)

**Files:**
- Modify: `FisherQuant/fisher/dash_app/services/__init__.py`

**Changes:**
In `get_db()`, after connect, call `init_schema()`:

```python
from ...store.schema import init_schema

def get_db() -> DuckDBManager:
    global _db_instance
    if _db_instance is None:
        _db_instance = DuckDBManager()
        _db_instance.connect("data/fisherquant.db")
        init_schema(_db_instance)  # Ensure all tables exist
    elif not hasattr(_db_instance, '_write_conn') or _db_instance._write_conn is None:
        _db_instance.connect("data/fisherquant.db")
        init_schema(_db_instance)
    return _db_instance
```

- [ ] **Step 1: Add init_schema() call to get_db()**
- [ ] **Step 2: Test** — verify tables created
- [ ] **Step 3: Commit** `"fix(C6): schema init consistency in get_db()"`

---

### Self-Review
- [x] All 6 spec requirements map to tasks
- [x] No TBD/TODO
- [x] Task 1 (P0) is independent — do first
- [x] Tasks 2-3 (search + data type) modify same file — sequential
- [x] Tasks 4-5 independent
- [x] Task 6 is one-line change
