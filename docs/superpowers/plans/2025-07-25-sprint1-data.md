# FisherQuant Sprint1 — Data Center + Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Build the Dash web application framework, data center (search/download/manage/refresh/export/adjustment), and home dashboard.

**Architecture:** Dash (Plotly) replaces FastAPI as the web framework. Dash Bootstrap Components for layout. Multi-page app with sidebar navigation. Data center connects to existing DuckDB store and AKShare adapter via background callbacks.

**Tech Stack:** Dash 2.6+, dash-bootstrap-components, Plotly, diskcache, existing fisher/ modules

## Global Constraints
- Python >= 3.11
- Dash >= 2.6 with diskcache for background callbacks (INF-01)
- All UI follows PRD color specs (行情红涨绿跌, 分析绿盈红亏)
- Existing 463 tests must continue passing
- DuckDB via DuckDBManager (INF-02)
- AKShare via rate-limited adapter (INF-03)

---

### Task S1-01: Dash App Framework + Navigation

**Files:**
- Create: `FisherQuant/fisher/dash_app/__init__.py`
- Create: `FisherQuant/fisher/dash_app/app.py`
- Create: `FisherQuant/fisher/dash_app/layout.py`
- Create: `FisherQuant/fisher/dash_app/callbacks/__init__.py`
- Modify: `FisherQuant/pyproject.toml` (add dash, dash-bootstrap-components, diskcache)

```python
# fisher/dash_app/app.py
import dash
import dash_bootstrap_components as dbc
from diskcache import Cache
from fisher.dash_app.layout import create_layout

cache = Cache("./data/dash_cache")
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP],
                background_callback_manager=dash.DiskcacheManager(cache))
app.title = "FisherQuant"
app._favicon = "📊"
app.layout = create_layout()
```

```python
# fisher/dash_app/layout.py — sidebar + content
NAV_ITEMS = [
    {"group": "数据管理", "items": [
        {"id": "data-center", "label": "数据中心", "icon": "📥"},
        {"id": "market-watch", "label": "行情看板", "icon": "📈"},
    ]},
    {"group": "策略研究", "items": [
        {"id": "strategy-center", "label": "策略中心", "icon": "🧠"},
        {"id": "factor-center", "label": "因子计算", "icon": "🔬"},
        {"id": "backtest-center", "label": "回测中心", "icon": "⚡"},
    ]},
    {"group": "结果分析", "items": [
        {"id": "visual-dashboard", "label": "可视化看板", "icon": "📊"},
        {"id": "report-center", "label": "报告中心", "icon": "📄"},
    ]},
    {"group": "系统", "items": [
        {"id": "settings", "label": "系统设置", "icon": "⚙️"},
    ]},
]

def create_layout():
    return dbc.Container([
        dbc.Row([
            dbc.Col(create_sidebar(), width=2, className="sidebar-col"),
            dbc.Col(html.Div(id="page-content"), width=10),
        ]),
        dcc.Location(id="url", refresh=False),
        dcc.Store(id="session-store", storage_type="session"),
        dcc.Store(id="backtest-results", storage_type="session"),
        dcc.Interval(id="refresh-interval", interval=60000),
    ], fluid=True, className="app-container")
```

Run entry: `python -m fisher.dash_app.app` or via CLI.

- [ ] Write test: app starts, home page renders
- [ ] Commit: `"feat(S1-01): Dash app framework with sidebar navigation and diskcache"`

---

### Task S1-02: Home Dashboard Page

**Files:**
- Create: `FisherQuant/fisher/dash_app/pages/home.py`

Cards: data overview (tickers count, A-share/HK counts, total records, last update), recent backtests (5 latest), quick actions (fetch data, create strategy, run backtest), activity timeline.

```python
# fisher/dash_app/pages/home.py
def create_home_layout():
    return dbc.Container([
        html.H3("首页仪表盘", className="mb-4"),
        dbc.Row([
            dbc.Col(create_stat_card("缓存标的", "0", "全部标的", "primary"), width=3),
            dbc.Col(create_stat_card("A股", "0", "沪深股票", "success"), width=3),
            dbc.Col(create_stat_card("港股", "0", "港股通", "info"), width=3),
            dbc.Col(create_stat_card("数据条数", "0", "最近更新: -", "warning"), width=3),
        ], className="mb-4"),
        dbc.Row([
            dbc.Col(dbc.Card([dbc.CardHeader("最近回测"), dbc.CardBody(id="recent-backtests")]), width=8),
            dbc.Col(dbc.Card([dbc.CardHeader("快捷操作"), dbc.CardBody([
                dbc.Button("拉取数据", id="quick-fetch", color="primary", className="mb-2 w-100"),
                dbc.Button("创建策略", id="quick-strategy", color="success", className="mb-2 w-100"),
                dbc.Button("运行回测", id="quick-backtest", color="warning", className="w-100"),
            ])]), width=4),
        ]),
    ])

def create_stat_card(title, value, subtitle, color):
    return dbc.Card([
        dbc.CardBody([
            html.H6(title, className="text-muted"),
            html.H3(value, className=f"text-{color}"),
            html.Small(subtitle, className="text-muted"),
        ])
    ])
```

- [ ] Add callbacks: update stat cards from DuckDB, load recent backtests
- [ ] Commit: `"feat(S1-02): home dashboard with stat cards, recent backtests, quick actions"`

---

### Task S1-03: Data Center — Symbol Search + Fetch

**Files:**
- Create: `FisherQuant/fisher/dash_app/pages/data_center.py`
- Create: `FisherQuant/fisher/dash_app/callbacks/data_callbacks.py`

```python
# Pages: search input → results dropdown → add to fetch list → fetch with date range + data type
# Callbacks: search_akshare(query) → list[dict], fetch_daily(symbols, start, end) → progress → success/fail
```

Key components:
- `dcc.Input` for search (min 2 chars)
- `dcc.Dropdown` for search results
- `dcc.DatePickerRange` for date range (default: Jan-Dec 2024)
- `dcc.RadioItems` for data type (日线/分钟线/财务数据)
- `dcc.Textarea` for batch paste (comma/newline separated)
- `dbc.Button` for fetch with loading state
- Progress bar for batch fetch

- [ ] Commit: `"feat(S1-03): data center search, single/batch fetch with progress"`

---

### Task S1-04: Data Center — Cached Symbols Management

**Files:**
- Modify: `FisherQuant/fisher/dash_app/pages/data_center.py`

- Table: `dash_table.DataTable` — code, name, market, records, date range, last_updated, actions
- Filters: Tab (全部/A股/港股)
- Actions: refresh row (incremental), delete row (with ConfirmDialog)
- Empty state: "暂无缓存数据" with shortcut

- [ ] Commit: `"feat(S1-04): cached symbols table with filter/refresh/delete"`

---

### Task S1-05: Data Center — Financials + Minute Download

**Files:**
- Modify: `FisherQuant/fisher/dash_app/pages/data_center.py`

- Financial data: Modal with table (AKShare financial summary)
- Minute data: period selector (1/5/15/30/60min) + date range (recent only)
- Store minute data via DuckDB

- [ ] Commit: `"feat(S1-05): financial data query and minute data download"`

---

### Task S1-06: Data Center — Auto Refresh + Export + Adj Factor

**Files:**
- Modify: `FisherQuant/fisher/dash_app/pages/data_center.py`
- Modify: `FisherQuant/fisher/dash_app/callbacks/data_callbacks.py`

- Auto refresh: toggle + cron input + next-run display (via APScheduler INF-07)
- Export: format selector (CSV/Excel/Parquet) → streaming download (INF-08)
- Adj factor: fetch button → table display → "已复权" badge
- Cascade cleanup: delete symbol → factors + adj data deleted

- [ ] Commit: `"feat(S1-06): auto-refresh, data export, adj factor with cascade cleanup"`

---

### Task S1-07: UX — Grouped Navigation + Responsive

**Files:**
- Modify: `FisherQuant/fisher/dash_app/layout.py`
- Create: `FisherQuant/fisher/dash_app/assets/style.css`

- Sidebar: collapsible groups, current page highlight (blue), unread badge on backtest center
- Responsive: ≥1400px sidebar always, 1024-1399 collapsible (default collapsed), <1024 hamburger + drawer
- Toast notification system: Critical/Error/Warning/Success/Info with stacking + timeout

```css
/* fisher/dash_app/assets/style.css */
.sidebar-col { background: #1a1d23; min-height: 100vh; padding: 12px; }
.nav-group-title { color: #6c757d; font-size: 0.75rem; text-transform: uppercase; padding: 8px 12px; }
.nav-item { color: #adb5bd; padding: 8px 12px; border-radius: 6px; cursor: pointer; margin: 2px 0; }
.nav-item:hover { background: #2a2d35; }
.nav-item.active { background: #0d6efd; color: white; }
```

- [ ] Commit: `"feat(S1-07): grouped sidebar navigation, responsive layout, toast notifications"`

---

### Task S1-08: QA-06 Performance Baselines

**Files:**
- Create: `FisherQuant/tests/performance/test_backtest_benchmarks.py`
- Create: `FisherQuant/tests/performance/conftest.py`

Benchmark tests per PRD 18.2:
- Single strategy/single symbol, 1 year: ≤ 5s
- Single strategy/10 symbols, 1 year: ≤ 30s
- Walk-forward, 1 symbol, 3 years, 12 windows: ≤ 45s
- Parameter sensitivity (fast 5-50/10 steps): ≤ 60s

```python
# tests/performance/test_backtest_benchmarks.py
import pytest
import time
from tests.factories import DataFactory

class TestBacktestPerformance:
    def test_single_strategy_1y(self):
        factory = DataFactory(seed=42)
        data = factory.generate_ohlcv("TEST.SZ", days=252, trend="random")
        # ... run backtest, assert elapsed <= 5s
```

- [ ] Commit: `"feat(QA-06): performance benchmark baselines for backtest scenarios"`

---

### Self-Review
- [x] All 8 tasks have complete code/descriptions
- [x] Dash replaces FastAPI as web framework (per PRD)
- [x] Background callbacks via diskcache (INF-01)
- [x] All existing 463 tests must continue passing
- [x] No TBD/TODO
