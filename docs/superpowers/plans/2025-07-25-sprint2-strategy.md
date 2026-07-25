# FisherQuant Sprint2 — Strategy + Factor Center

> **For agentic workers:** Use superpowers:subagent-driven-development.

**Goal:** Build strategy center (list/create/edit/templates/import-export/execution engine) and factor center (list/calculate/preview).

**Architecture:** All pages are Dash pages under `fisher/dash_app/pages/`. Strategy persistence via JSON files in `strategies/`. DSL engine (INF-05) validates custom strategies. Factors stored via FactorStorage (INF-06). Execution engine maps config → Strategy subclass via registry.

**Tech Stack:** Dash, dbc, existing fisher/strategy/, fisher/factor/, fisher/dash_app/

## Global Constraints
- Python >= 3.11, Dash + dbc, diskcache background callbacks
- Strategy JSON files: `strategies/{name}.json`
- DSL validation via INF-05 DSLEngine.validate_dsl()
- Factor storage via INF-06 FactorStorage
- NO eval/exec in custom strategy execution
- 479 existing tests must continue passing

---

### Task S2-01: Strategy Center Page + List + Creation Wizard

**Files:**
- Create: `FisherQuant/fisher/dash_app/pages/strategy_center.py`
- Create: `FisherQuant/fisher/dash_app/callbacks/strategy_callbacks.py`

Steps wizard (4 steps):
1. Basic info (name, type dropdown: sma_cross/macd/bollinger/rsi/buy_and_hold/custom, description)
2. Parameters (dynamic form per type — SMA: fast/slow, MACD: fast/slow/signal, Bollinger: period/std, RSI: period/overbought/oversold, Custom: JSON editor)
3. Symbol pool (optional, multi-select from cached)
4. Confirm (summary + save)

Strategy list table: name, type, symbols count, params summary, enabled toggle, created_at, edit/delete actions.

Commit: `"feat(S2-01): strategy list + 4-step creation wizard with dynamic params"`

---

### Task S2-02: Strategy Templates + Import/Export + Execution Engine

**Files:**
- Modify: `FisherQuant/fisher/dash_app/pages/strategy_center.py`
- Create: `FisherQuant/fisher/strategy/execution.py`

5 templates: SMA Cross, MACD, Bollinger, RSI, Buy & Hold — each with default params.

Strategy execution engine: reads `strategies/{name}.json` → `STRATEGY_REGISTRY[type]` → instantiate strategy class → return callable.

Import/Export: JSON file upload/download via dcc.Upload + dcc.Download.

Commit: `"feat(S2-02): 5 strategy templates, JSON import/export, execution engine"`

---

### Task S2-03: Factor Center Page + Compute + Preview

**Files:**
- Create: `FisherQuant/fisher/dash_app/pages/factor_center.py`
- Create: `FisherQuant/fisher/dash_app/callbacks/factor_callbacks.py`

Factor list: MA(SMA/EMA), MACD, RSI, Bollinger Bands, ATR, Volume SMA — with descriptions and default params.

Compute: select symbols (from cached) + select factors + configure params → background callback → store via FactorStorage → show success/fail per symbol.

Preview: select symbol → show data table with OHLCV + computed factor columns (via FactorStorage.load_with_factors).

Commit: `"feat(S2-03): factor list, compute, and preview with indep- storage"`

---

### Self-Review
- [x] 3 tasks, each covers multiple PRD items
- [x] Uses existing INF-05 (DSL) and INF-06 (FactorStorage)
- [x] All new pages use Dash + dbc consistent with Sprint1 layout
