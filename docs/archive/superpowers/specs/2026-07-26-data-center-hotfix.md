# FisherQuant 数据中心紧急修复 spec

> 日期：2026-07-26  
> 范围：P0 冲突 + P1 核心体验  
> 状态：设计完成

## 1. P0 重复回调冲突（3 项）

### 1.1 `cached-table-container` 冲突

`data_callbacks.py` 和 `data_cache_callbacks.py` 同时输出到 `cached-table-container`。

删除 `data_callbacks.py` 中以下重复回调：
- `force_refresh_cached`（Input: cache-refresh-btn）
- `render_cached_table`（Input: cache-tab + cache-market-filter + cache-filter-input + cache-refresh-btn + cache-delete-btn + cached-table）
- `delete_selected_rows`（Input: cache-delete-btn）

保留 `data_cache_callbacks.py` 中的版本（已接入 Service 层）。

### 1.2 `download-data` 冲突

`data_callbacks.py` 的 export 回调忽略筛选条件，与 `data_export_callbacks.py` 冲突。

删除 `data_callbacks.py` 中 export 回调（约 `:237-269`）。

### 1.3 `adj-factor-result` 冲突

`data_callbacks.py` 和 `data_export_callbacks.py` 同时输出到 `adj-factor-result`。

删除 `data_callbacks.py` 中 adj 回调（约 `:271-312`）。

### 1.4 Schema 初始化一致性（C6）

`services/__init__.py` 的 `get_db()` 中补调 `init_schema()`，确保 `bars_daily` 等表在建库时创建。

## 2. P1 核心体验修复（5 项）

### 2.1 港股搜索

将 `callbacks/data_callbacks.py` 的 `search_symbols` 回调改为调用 `DataCenterService.search_symbols()`，后者已包含 A 股 + 港股双市场搜索。

### 2.2 数据类型分发

在 `DataCenterService.fetch_bars()` 中按 `data_type` 分发：

| data_type | API | 目标表 |
|-----------|-----|--------|
| `daily` | `ak.stock_zh_a_hist()` | `bars_daily`（已有） |
| `minute` | `ak.stock_zh_a_hist_min_em()` | `bars_minute` |
| `financials` | `ak.stock_financial_abstract()` | 新建 `financials` 表 |

### 2.3 拉取进度反馈

采用 `dcc.Store` + `dcc.Interval` 轮询方案（兼容 Dash 4.x，无需 LongCallback）：

- fetch 回调改为 `background=True`
- 每次下载一个标的更新一次 `data-fetch-progress` Store
- 前端 `dcc.Interval` 每秒轮询读取并更新 `dbc.Progress`

### 2.4 自动加载不阻塞主线程

- `update_auto_load_progress` 回调只读 `auto_load_status` 表做 UI 展示，不再调用 `initial_load()`
- 改用 APScheduler 后台线程执行 `initial_load()` 和 `incremental_update()`
- 下载进度写入 `auto_load_status` 表，前端轮询读取

### 2.5 接入调度器 + 启动检查

- `app.py` 启动时调用 `AutoLoadService.check_and_start()`（检测空数据库 -> 自动开始首次加载）
- APScheduler 注册日终任务 `incremental_update()`（16:30 执行）

## 3. 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `callbacks/data_callbacks.py` | 删除约 200 行 | 移除与 cache/export/adj 重复的回调 |
| `callbacks/routing.py` | 确认注册 | 确保只注册保留的版本 |
| `services/data_center_service.py` | 修改 `fetch_bars()` | 补 minute/financials 分发 |
| `services/auto_load_service.py` | 保留 | 不需修改，调度器在 app.py 接入 |
| `services/__init__.py` | 修改 `get_db()` | 补 `init_schema()` |
| `app.py` | 修改 | 启动时调 `check_and_start()` |
| `pages/data_center.py` | 修改 | fetch 进度轮询 UI；auto-load 轮询回调改为只读状态 |

## 4. 测试

- 回归测试：已存的 22 条 regression 测试继续通过
- 新增测试：港股搜索、minute/financials 分发、auto_load schema init、调度器触发

## 自我审查

- [x] 无 TBD/TODO
- [x] 3 个 P0 冲突均对应修复
- [x] 5 个 P1 体验问题均对应修复
- [x] 范围聚焦 P0+P1
