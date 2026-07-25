# FisherQuant Phases 4-6 Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development.

**Goal:** Build Paper Engine + OMS + Position + Risk (Phase 4), Backtest + Analytics (Phase 5), Monitor + Alert + Scheduler + Auth (Phase 6).

**Tech Stack:** Python 3.11+, polars, DuckDB, FastAPI, asyncio, APScheduler, Jinja2

## Global Constraints
- Python >= 3.11, polars for DataFrames, DuckDB for persistence
- A-shares: T+1, 100-share lots, board-varying price limits
- HK Connect: T+0, variable lots, no price limits
- All public functions type annotated
- Paper Engine shared between backtest and live simulation modes

---

## Phase 4: Paper Engine + OMS + Position + Risk

### Task P4-1: Order & OrderStatus Models
**Files:** fisher/oms/__init__.py, fisher/oms/orders.py
- Order dataclass: order_id, ticker, market, asset_type, side, quantity, price, filled_qty, filled_price, commission, status, order_type, created_at
- ORDERS_STATUS_TRANSITIONS dict
- TDD, commit: "feat: Order and OrderStatus models with state transitions"

### Task P4-2: OMS Engine
**Files:** fisher/oms/engine.py
- OMSEngine: submit(order) → state machine, cancel(order_id), get_order(order_id), get_pending()
- Condition order queue (stop-loss, take-profit)
- TDD, commit: "feat: OMS engine with order state machine and condition queue"

### Task P4-3: Fee Calculator
**Files:** fisher/paper/__init__.py, fisher/paper/fees.py
- FeeCalculator.calculate(order, price) → commission, stamp_duty, transfer_fee, total
- Per-market fee tables from configs/fees.yaml
- TDD, commit: "feat: fee calculator for A-share/HK/ETF/CB"

### Task P4-4: Fill Simulator
**Files:** fisher/paper/fill.py
- FillSimulator.check_fill(order, bar) → (filled: bool, fill_price: float)
- Price limit check, volume constraint, liquidity simulation
- Configurable fill price mode: next_open, current_close, vwap
- TDD, commit: "feat: fill simulator with price limits and configurable modes"

### Task P4-5: Paper Engine
**Files:** fisher/paper/engine.py
- PaperEngine implements BrokerAdapter (from fisher/broker/adapter.py)
- Composes FeeCalculator + FillSimulator + ExchangeRules
- submit_order → validate → enqueue → wait fill → execute
- TDD, commit: "feat: PaperEngine implementing BrokerAdapter"

### Task P4-6: Position Service
**Files:** fisher/position/__init__.py, fisher/position/service.py
- PositionService: update_on_fill(order), get_position(ticker), get_all_positions()
- Weighted average cost, T+1 available calculation, frozen quantity
- Multi-currency (HKD→CNY conversion for HK Connect)
- Snapshot to DuckDB on close
- TDD, commit: "feat: position service with cost basis and T+1 tracking"

### Task P4-7: Risk Engine
**Files:** fisher/risk/__init__.py, fisher/risk/pre_trade.py, fisher/risk/engine.py, fisher/risk/realtime.py
- PreTradeEngine: check(order, position_service) → (approved: bool, reason: str)
- Built-in rules: MaxPosition, DailyLossLimit, PriceLimit, SectorLimit, NetExposure, Blacklist
- RealTime monitor: VaR (historical), beta, drawdown
- TDD, commit: "feat: risk engine with pre-trade rules and real-time monitoring"

### Task P4-8: Integration — Order to Position Pipeline
**Files:** tests/integration/test_order_to_position.py
- End-to-end: OMS submit → PaperEngine fill → Position update → verify
- TDD, commit: "feat: order-to-position integration test"

---

## Phase 5: Backtest + Analytics

### Task P5-1: Time Player
**Files:** fisher/backtest/__init__.py, fisher/backtest/time_player.py
- TimePlayer: load bars from DuckDB → iterate sequentially → publish Bar events
- Support daily and minute frequencies
- TDD, commit: "feat: time player for sequential bar replay"

### Task P5-2: Backtest Engine
**Files:** fisher/backtest/engine.py
- BacktestEngine orchestrates: TimePlayer → Strategy → Portfolio → PaperEngine → Position
- Reuses PaperEngine for fill simulation (same code as live mode)
- TDD, commit: "feat: backtest engine with shared PaperEngine"

### Task P5-3: Performance Analytics
**Files:** fisher/analytics/__init__.py, fisher/analytics/performance.py
- Metrics: cumulative_return, annualized_return, sharpe_ratio, sortino_ratio, max_drawdown, win_rate, profit_factor, beta, alpha, information_ratio, turnover
- Input: list of daily NAV values + benchmark NAV
- TDD, commit: "feat: performance analytics with 10+ metrics"

### Task P5-4: Attribution & Reporting
**Files:** fisher/analytics/attribution.py, fisher/analytics/report.py
- brinson_attribution(portfolio, benchmark) → dict
- report_to_json(analytics_result), report_to_html(analytics_result)
- TDD, commit: "feat: Brinson attribution and JSON/HTML reporting"

---

## Phase 6: Monitor + Alert + Scheduler + Auth

### Task P6-1: Auth Module
**Files:** fisher/monitor/__init__.py, fisher/monitor/auth.py
- create_default_admin() → username="admin", random password → write ~/.fisher/credentials
- authenticate(username, password) → JWT token
- get_current_user(token) → username
- TDD, commit: "feat: JWT auth with admin password management"

### Task P6-2: Alert Service
**Files:** fisher/alert/__init__.py, fisher/alert/service.py
- AlertService.subscribe(event_types, callback)
- ConsoleChannel: print alerts to stderr
- Throttle: same event type N seconds apart max
- TDD, commit: "feat: alert service with console channel and throttling"

### Task P6-3: Scheduler
**Files:** fisher/scheduler/__init__.py, fisher/scheduler/engine.py
- SchedulerEngine: APScheduler with jobs
- Market hooks: on_market_open, on_market_close, on_mid_break, on_mid_resume
- Daily tasks: position_snapshot, report_generation
- Periodic: rebalance (weekly), strategy_retrain (monthly)
- TDD, commit: "feat: scheduler with market hooks and periodic tasks"

### Task P6-4: FastAPI Web App
**Files:** fisher/monitor/app.py, fisher/monitor/ws.py
- FastAPI app with routes: /login, /dashboard, /api/overview, /api/positions, /api/orders, /api/risk
- WebSocket endpoints: /ws/overview, /ws/risk, /ws/orders, /ws/alerts
- Static token auth for WebSocket upgrade
- TDD, commit: "feat: FastAPI web app with REST and WebSocket endpoints"

### Task P6-5: HTML Templates
**Files:** fisher/monitor/templates/
- base.html (layout with nav)
- login.html, dashboard.html, orders.html, risk.html, strategy.html, alerts.html, settings.html
- HTMX for partial updates, Chart.js for charts
- TDD (render tests), commit: "feat: dashboard HTML templates with HTMX and Chart.js"

### Task P6-6: Integration — Full System Startup
**Files:** tests/integration/test_startup.py
- Verify: config → logging → event bus → store → (mock) market → strategy → portfolio → risk → oms → positions → monitor starts
- Smoke test: all modules initialize without error
- TDD, commit: "feat: full system startup integration test"
