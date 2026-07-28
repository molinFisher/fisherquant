# 行情看板 · 交互优化与功能增强 PRD

| 项 | 内容 |
|---|---|
| 文档版本 | **v1.1（含评审记录）** |
| 作者 | 高级产品经理（AI 代理） |
| 日期 | 2026-07-28 |
| 状态 | 待评审 |
| 关联模块 | `fisher/dash_app/pages/quote_board.py`（页面）<br>`fisher/dash_app/callbacks/quote_callbacks.py`（回调） |
| 上游依赖 | `bars_minute` / `bars_daily` / `snapshots` 表（不变） |

---

## 1. 背景与问题陈述

行情看板是用户日常监控自选标的市场行情的核心页面。经页面走查与代码审计，发现以下影响体验的问题：

| 编号 | 用户感知问题 | 代码事实 | 严重度 |
|---|---|---|---|
| B1 | **无法删除标的。** 添加了的标的无法移除，用户被锁定在初始选择中。整个页面没有"删除"入口。 | DataTable 无删除/移除操作列；页面无"清空自选"按钮。用户唯一删除方法：手动编辑 `watchlist.json` 文件。 | **P0** |
| B2 | **只有分钟 K 线，看不到日 K 线。** 用户需要日线趋势判断，但行情的图表只提供分钟 K 线。 | 只有一个 `dcc.Graph`（`qb-minute-chart`），无日线图表组件。复权口径选择器有但只能影响表格降级数据，对图表没有作用。 | **P0** |
| B3 | **无法切换图表标地：K 线始终画第一个标的。** 用户想看第二个标的的 K 线，没有切换入口。 | `render_minute_chart` 固定取 `wl[0]`（自选列表第一个）。 | **P0** |
| B4 | **"名称"列显示的是代码，不是中文名称。** 用户看到的"名称"列是 `000001` 而非"平安银行"，丧失可读性。 | `_quote_row` 使用 `sym.split(".")[0]`，未从 `symbol_dict` 查中文名。 | **P1** |
| B5 | **行选中（checkbox）无任何作用。** 每行左侧出现复选框，用户选中后页面没有反应，困惑。 | DataTable 设置了 `row_selectable="multi"` 但没有任何回调监听 selected_rows。 | **P1** |
| B6 | **复权口径在手动刷新后丢失。** 用户切到"前复权"后点"手动刷新"，表格重置为不复权。 | `update_watchlist` 回调未透传 `adj_mode` State，默认 `"none"`。 | **P1** |
| B7 | **非交易时段空转。** 周末/夜间60秒定时器持续触发数据库查询，浪费资源。 | `qb-trading-status` store 被写入但从未被消费。 | **P2** |
| B8 | **健康度仪表盘每60秒闪烁重建。** 覆盖率不变但仪表盘整体重建，含按钮在内产生视觉跳动。 | `render_health` 以 `n_intervals` 为 Input，触发全量重建。 | **P2** |

**核心矛盾**：行情看板有行情数据的读取和展示能力，但缺乏"用户可控"的交互——不能增删自选（其实可以增不能删）、不能选 K 线标的、行选中无意义、口径不一致。

---

## 2. 目标与非目标

### 2.1 目标
1. **让用户能删除标的**（B1）：单行 × 删除 + 选中批量删除 + 清空自选
2. **让用户能看到日 K 线**（B2/B3）：新增日线图，点击表格行切换 K 线标的
3. **修复无效/误导性交互**（B4-B8）：名称中文、行选中改删除、口径一致、交易时段联动

### 2.2 非目标（本次不做）
- **不引入实时推送**（WebSocket/SSE）：快照仍依赖 RealtimeDaemon 后台写入，不做架构级实时化改造。
- **不修改数据服务层**：`get_minute_bars` / `get_daily_bars` / `get_snapshot` 接口不变。
- **不做多图表联动**（如量价副图/技术指标叠加），保留简约 K 线形态。
- **不改"批量去缓存补齐"跳转逻辑**（`batch_goto_cache` 保留）。

---

## 3. 用户角色与场景

| 角色 | 核心诉求 |
|---|---|
| **量化研究员** | 监控 A/港股实时报价，通过 K 线判断入场/出场时机，需要能灵活管理自选列表 |
| **日内交易者** | 依赖分钟线捕捉短期波动，快速切换标的查看不同分钟周期 |
| **趋势投资者** | 关注日线形态（均线/支撑位），需要中长期的图表视角 |

---

## 4. 重设计后的信息架构

```
行情看板（/market-watch）
├─ 工具栏 Row
│   ├─ 搜索添加（Dropdown + 添加按钮）【保留】
│   └─ 手动刷新 + 自动刷新(60s) + **清空自选** 【新增】
├─ 参数 Row
│   ├─ 复权口径【保留】 
│   └─ 分钟周期【不变】
├─ 健康度仪表盘【优化：仅在池变化时重建】
├─ 行情表格 + K线区
│   ├─ DataTable
│   │   └─ 每行：代码 | **名称(中文)** | 最新价 | 涨跌幅 | 成交量 | 覆盖度 | 实时 | 去缓存 | **移除(×)** 
│   │   └─ 行选中 → **批量删除** 【替换原无意义的选中】
│   └─ **K 线切换 Tabs** 【新增】
│       ├─ Tab「分钟线」 ← 原分钟K线图（不变）
│       └─ Tab「日线」    ← **新增日K线图**
│   └─ 当前选中标的名称（高亮标识）
```

---

## 5. 功能需求（FR）

### FR-1 单行删除 + 批量删除 + 清空自选（对应 B1）

**需求**：提供三种删除标的的方式，覆盖全场景。

**FR-1.1 单行移除**：
- DataTable 新增 `remove` 列（type="text"），每行显示 "×"。
- 使用 Dash DataTable 的 `active_cell` 监听点击：当 `active_cell.column_id == "remove"` 时，通过 `active_cell.row` 索引 `data` 数组取得 ticker。
- 从 `watchlist` 中移除该标的 → 保存到文件 → 刷新表格。
- × 按钮在首行/末行逻辑一致，不可误删（需确认——一次点击即删，不做二次确认；误删可重新搜索添加）。

**FR-1.2 选中批量删除**：
- 将目前无意义的 `row_selectable="multi"` 赋予实际功能：选中多行后，页面显示"删除选中 (N)"按钮。
- 点击按钮 → 从 watchlist 中批量移除选中的标的 → 保存 → 刷新表格。
- 选中状态随表格刷新自动清空。

**FR-1.3 清空自选**：
- 工具栏新增「清空自选」按钮（`danger` 色，确认弹窗）。
- 点击 → `dbc.Modal` 确认 → 确认后 `watchlist=[]` 保存 → 页面全空状态。

**验收**：
- [ ] DataTable 每行末尾显示 ×，点击后该标的从看板消失。
- [ ] 勾选多行后出现"删除选中"按钮，点击后选中标的全部移除。
- [ ] 工具栏有"清空自选"按钮，点击后二次确认，确认后自选清空、页面为空态提示。
- [ ] 删除操作与配置文件 `watchlist.json` 实时同步。

### FR-2 日 K 线图 + 标的切换（对应 B2/B3）

**需求**：新增日 K 线图展示，允许用户点击表格行切换 K 线展示的标的。

**FR-2.1 K 线切换 Tabs**：
- 将原本的单 `dcc.Graph` 包裹在 `dbc.Tabs` 中，分"分钟线"和"日线"两个 Tab。
- Tab 切换不影响表格和其他区域——只切换 K 线的周期类型。

**FR-2.2 日 K 线图**：
- 新增 `qb-daily-chart`（`dcc.Graph`），默认隐藏（在日线 Tab 中展示）。
- **服务层无 `get_daily_bars` 方法**（评审 D1：`DataCenterService` 仅暴露 `get_minute_bars`，无法直接获取日线数据）。实现方式：
  - 新增 `_fetch_daily_bars(ticker, limit=120, adj_mode="none")` 辅助函数，使用已有 `_get_db()` 直接查询 `bars_daily` 表。
  - SQL: `SELECT trade_date, open, high, low, close, volume FROM bars_daily WHERE ticker=? ORDER BY trade_date DESC LIMIT 120` → 反转升序 → Candlestick 图。
  - 复权口径处理：复用 `_adj_factor` 对收盘价/开盘价做前/后复权换算（逻辑同 `_quote_row` 中日线降级）。
- 图表参数：高度同分钟线（~320px），`xaxis_rangeslider_visible=False`。
- 数据：`bar_date, open, high, low, close, volume` → Candlestick 图。

**FR-2.3 点击选行切换 K 线标的**：
- 新增 `dcc.Store(id="qb-chart-symbol")` 存储当前 K 线展示的标的代码。
- 使用 `active_cell` 监听 DataTable 单元格点击。当任意非操作列单元格被点击时，取 `active_cell.row` 索引 `data` 数组获得 ticker → 设置 `qb-chart-symbol`。注意：点击 × 移除列不触发图表切换（冲突解决见评审 D4）。
- 分钟/日 K 线图均以 `qb-chart-symbol` 为 State，图表更新为展示该标的的 K 线。
- 默认 `qb-chart-symbol = watchlist[0]`（首个标的）。
- 当前图表标的在表格中高亮（`style_data_conditional` 中 `{code} = '<ticker>'` 设置背景色 `#fff3cd` + 加粗。复用已有 `highlight` 参数，驱动源改为 `qb-chart-symbol` 而非仅 URL `?focus=`）。

**验收**：
- [ ] K 线区域上方有"分钟线 / 日线"两个 Tab，切换后 K 线图对应刷新。
- [ ] 日线 Tab 展示日 K 线图（Candlestick），包含开盘/最高/最低/收盘/成交量。
- [ ] 点击表格某行，K 线图（无论分钟/日线）切换展示该标的的行情。
- [ ] 当前 K 线标的在表格中高亮标识。
- [ ] 日 K 线图表根据 `qb-adj-mode` 复权口径读取对应数据。

### FR-3 名称列展示中文名称（对应 B4）

**需求**：表格"名称"列显示真实的中文股票名称。

- 通过 `symbol_dict_ready()` 后查询 `symbol_dict` 获取 `ticker → name` 映射。
- `_quote_row` 函数新增参数 `name_map: dict[str, str]`，以 `ticker.split(".")[0]` 为 key 查找中文名。
- 未找到时降级为显示代码片段（当前行为）。

**验收**：
- [ ] "名称"列显示"贵州茅台"而非"600519"。
- [ ] 未在 symbol_dict 中的标的降级显示代码。

### FR-4 行选中改为批量删除（对应 B5）

**需求**：利用已存在但无作用的 `row_selectable="multi"`，将其功能定义为批量删除的前置操作（详见 FR-1.2）。

- DataTable 保持 `row_selectable="multi"`（不变）。
- 新增组件 `qb-delete-selected-btn`（`dbc.Button`，"删除选中 (0)"），初始隐藏/禁用。
- 新增回调：监听 `qb-data-table.selected_rows` → 有选中行时显示按钮并更新计数"删除选中 (N)" → 点击按钮触发 FR-1.2 批量删除。
- 选中行数 = 0 时按钮隐藏。

**验收**：
- [ ] 选中 0 行时"删除选中"按钮隐藏。
- [ ] 选中 ≥1 行时按钮显示"删除选中 (N)"，点击后批量删除。
- [ ] 删除后选中状态清空，按钮恢复隐藏。

### FR-5 复权口径在刷新中保持一致（对应 B6）

**需求**：手动刷新/自动刷新后，复权口径不丢失。

- **关键发现（评审 D5）**：`_fetch_quote_data` 函数 **已支持** `adj_mode` 参数（第 265 行），`rerender_on_adj_mode` 回调也已正确透传口径（第 509 行）。但 `update_watchlist` 回调调用 `_fetch_quote_data(watchlist)` 未传 `adj_mode`，默认 `"none"`。修复点：
  - `update_watchlist` 新增 `State("qb-adj-mode", "value")` 参数。
  - 调用 `_fetch_quote_data(watchlist, adj_mode)` 透传口径。
- `rerender_on_adj_mode` 回调保留不变（口径切换时独立刷新表格）。

**验收**：
- [ ] 切到"前复权"→ 点"手动刷新"→ 表格仍为前复权数据。
- [ ] 口径由 Store 持久化，不依赖表格刷新重置。

### FR-6 交易时段联动（对应 B7）

**需求**：非交易时段停用自动刷新，减少无意义数据库查询。

- **关键发现（评审 D5）**：`check_trading_hours` 以 `Input("url", "pathname")` 为触发源，仅在导航时执行一次。交易时段跨越（如 9:15→11:30→13:00→15:00）不会自动触发。因此需要两种联动机制：
  - **导航联动**（保持现有 `url.pathname` Input，首次进入页面即判断当前时段）。
  - **心跳联动**（新增 `qb-refresh-interval.n_intervals` Input 联动的定时检查），每 60 秒评估一次当前时间，交易时段切换时（如 11:30 收盘）自动停止刷新。
- 实施：`check_trading_hours` 改为双 Input（`url.pathname` + `qb-refresh-interval.n_intervals`），输出（已有 `qb-trading-status.data` + 新增 `qb-refresh-interval.disabled`）。
- `toggle_auto_refresh` 原回调保留不变（用户手动开关优先级最高；若用户关闭自动刷新，不受交易时段影响）。

**验收**：
- [ ] 交易时段（周一到五 9:15-11:30, 13:00-15:00）：自动刷新正常工作。
- [ ] 非交易时段（盘后、周末）：自动刷新停止，手动刷新仍可用。
- [ ] 下次进入交易时段时自动恢复刷新。

### FR-7 健康度仪表盘优化（对应 B8）

**需求**：健康度仪表盘只在池变化时重建，避免 60 秒心跳闪烁。

- `render_health` 回调移除 `qb-refresh-interval.n_intervals` Input。
- Input 仅保留 `qb-watchlist-store.data`（池变化才重建）。
- 内部按钮（"批量去缓存补齐"）现为静态，不因心跳重建。

**验收**：
- [ ] 修改自选（添加/删除）后健康度仪表盘刷新。
- [ ] 60 秒心跳时仪表盘不重建，无视觉闪烁。

---

## 6. 交互流程（用户旅程）

**管理自选**：
```
进入看板 → 看到自选列表
  ├─ 想删除格力电器 → 点击格力行末尾 × → 从列表消失，watchlist.json 同步移除
  ├─ 想批量删多个 → 勾选美的、格力行的复选框 → 出现"删除选中 (2)" → 点击 → 批量移除
  └─ 想清空 → 点击"清空自选" → 弹窗确认 → 确认 → 自选清空
```

**查看日 K 线**：
```
看板 → 点击"平安银行"行的任意位置（非操作列）→ 平安银行行高亮
  → K 线图切换为平安银行的分钟线
  → 点击上方的「日线」Tab → K 线图切换为平安银行日线
  → 调整复权口径为"前复权" → 日线图重新读取前复权数据
```

---

## 7. 数据模型（新增/调整 Store）

| Store | 类型 | 用途 |
|---|---|---|
| `qb-chart-symbol`（**新增**） | `dcc.Store` | 当前 K 线展示的标的代码；默认 `watchlist[0]`；点击表格行更新 |
| `qb-trading-status`（**赋予用途**） | `dcc.Store` | 已有，现追加消费方：控制自动刷新开关 |

---

## 8. 产品决策

1. **单行删除不二次确认**
   - 决策：不弹确认框，一次点击即删。用户可通过重新搜索添加恢复。误删成本低。
2. **K 线切换标的的触发方式**
   - 决策：点击表格行（`active_cell`，忽略 column_id 仅取 row）切换，而非独立 Dropdown。最直观，且复用已有行交互。注意：点击 × 移除列时不触发图表切换（通过 `active_cell.column_id != "remove"` 守卫）。
3. **日线数据量**
   - 决策：拉取最近 120 个交易日（约半年），足够趋势判断。首屏按 `LIMIT 120 DESC`。
4. **清空自选二次确认**
   - 决策：需 `dbc.Modal` 确认弹窗。清空是破坏性操作，需提示用户确认。
5. **单行移除实现方式**
   - 决策（评审 D2）：用 DataTable `active_cell` 监听 × 列点击 + `data[row_index]["code"]` 取 ticker，而非 pattern-matching IDs。Dash DataTable 不支持行内交互组件（不支持 `dbc.Button` 嵌入 each row）。
6. **删除回调 Output 冲突策略**
   - 决策（评审 D3）：删除/清空操作统一收敛到**单个** watchlist 写回调，通过 `dash.ctx.triggered` 区分触发源（`active_cell` / 批量删除按钮 / 清空确认按钮）。避免 6 个 `allow_duplicate` 回调争夺同一 Output。

---

## 9. 代码改动清单

| 对象 | 位置 | 处理 |
|---|---|---|
| `qb-minute-chart` | `quote_board.py` L86 | 包裹在 `dbc.Tabs` 中，新增 Tab「日线」 |
| `qb-daily-chart`（**新增**）| `quote_board.py` | 新增 `dcc.Graph(id="qb-daily-chart")`，日线 Tab 容器内 |
| `qb-chart-symbol`（**新增**）| `quote_board.py` | 新增 `dcc.Store(id="qb-chart-symbol", data=None)` |
| `qb-delete-selected-btn`（**新增**）| `quote_board.py` | 新增批量删除按钮，DataTable 附近；初始隐藏 |
| `qb-clear-all-btn`（**新增**）| `quote_board.py` | 工具栏新增"清空自选"按钮 |
| `qb-clear-modal`（**新增**）| `quote_board.py` | 清空自选确认弹窗（`dbc.Modal`） |
| DataTable 新增 `remove` 列 | `quote_board.py` `_build_quote_table` | 列 `{"name": "", "id": "remove"}`，每行渲染 "×"（type="text"）；通过 `active_cell` 监听点击，`data[row]["code"]` 取 ticker（评审 D2：不使用 pattern-matching） |
| DataTable 名称列修复 | `_quote_row` | 新增 `name_map` 参数，查 `symbol_dict` 取中文名 |
| DataTable 高亮驱动源 | `_build_quote_table` | 新增可选 `chart_symbol` 参数；若传则追加 `{code} = '<chart_symbol>'` 高亮条件，不影响 `?focus=` 高亮 |
| `_fetch_daily_bars`（**新增函数**）| `quote_callbacks.py` | 评审 D1：服务层无 `get_daily_bars`，直接用 `_get_db()` 查 `bars_daily`；支持复权口径换算 |
| `_build_daily_chart`（**新增函数**）| `quote_callbacks.py` | 构建日 K 线 Candlestick figure，逻辑同 `_build_minute_chart` |
| `update_watchlist` | `quote_callbacks.py` | 新增 `State("qb-adj-mode", "value")`；透传口径到 `_fetch_quote_data`（评审 D5） |
| `render_minute_chart` | `quote_callbacks.py` | 改为读取 `qb-chart-symbol` 指定标的（FR-2.3）；移除 `n_intervals` Input（评审 D6：图表不因心跳重建） |
| `render_daily_chart`（**新增**）| `quote_callbacks.py` | 日 K 线渲染回调；Input: `qb-chart-symbol.data`, `qb-adj-mode.value` |
| `on_table_cell_click`（**新增**）| `quote_callbacks.py` | `active_cell` → 区分 × 列（删除）与非操作列（切图表）→ 写 `qb-chart-symbol` 或触发删除 |
| `on_delete_selected`（**新增**）| `quote_callbacks.py` | 通过 `selected_rows` 取选中行 ticker 列表 → `_remove_from_watchlist(tickers)` |
| `on_clear_watchlist_confirm`（**新增**）| `quote_callbacks.py` | 确认弹窗后清空 watchlist |
| `check_trading_hours` | `quote_callbacks.py` | 新增 `qb-refresh-interval.n_intervals` Input（评审 D5：需心跳联动，仅导航不够）；直接输出 `qb-refresh-interval.disabled` 和 `qb-trading-status.data` |
| `render_health` | `quote_callbacks.py` | 移除 `n_intervals` Input

---

## 10. 验收测试建议

| 测试 | 覆盖 | 类型 | 评审状态 |
|---|---|---|---|
| `test_remove_symbol_via_active_cell` | FR-1.1 单行 × 删除 | 单元 | 新增（评审 T2：替换原 pattern-matching 方案测试） |
| `test_delete_selected_removes_multiple` | FR-1.2 批量删除 | 单元 | 新增 |
| `test_clear_watchlist_shows_modal_then_confirms` | FR-1.3 清空确认弹窗 | 单元 | 新增 |
| `test_daily_chart_renders_candlestick` | FR-2.1/2.2 日线图 | 单元 | 新增 |
| `test_click_row_switches_chart_symbol` | FR-2.3 | 单元 | 新增 |
| `test_chart_symbol_highlight_in_table` | FR-2.3 高亮 | 单元 | 新增 |
| `test_name_column_shows_chinese_name` | FR-3（**需注意 T1**） | 单元 | **需重写**：现有 `test_fetch_quote_data` 断言 `data[0]["name"] == "600519"` → FR-3 后变为 "贵州茅台"，须更新 mock 和断言 |
| `test_selected_rows_shows_delete_button` | FR-4 | 单元 | 新增 |
| `test_adj_mode_persists_after_manual_refresh` | FR-5 | 集成 | 新增 |
| `test_trading_hours_interval_triggers` | FR-6 心跳联动 | 单元 | 新增（评审 D5：需 mock datetime 验证时段切换） |
| `test_auto_refresh_disabled_non_trading_period` | FR-6 非交易时段禁用 | 单元 | 新增 |
| `test_health_not_rebuilt_on_interval` | FR-7 | 单元 | 新增 |
| `test_build_quote_table_data_shape` | 回归 | 单元 | **需更新**（评审 T1）：现有测试 data 包含 `"name":"600519"`，FR-3 后需改为中文名 |
| `test_chart_symbol_clear_on_empty_watchlist` | 边界 | 单元 | 新增（评审 DES-3：空自选时图表状态） |

---

## 11. 里程碑建议

| 阶段 | 内容 | 涉及 FR | 估时 |
|---|---|---|---|
| P1 | 删除功能（单行×、批量删、清空自选） | FR-1 + FR-4 | 1d |
| P2 | 日 K 线图 + 标的切换 | FR-2 | 1d |
| P3 | 交互修复（中文名称、口径一致、交易时段、健康度） | FR-3/5/6/7 | 0.5d |
| P4 | 单测补充 + 手工验收 | §10 全部 | 0.5d |

---

## 12. 影响面与风险

- **影响范围**：仅行情看板页面及其回调。数据中心、策略中心、服务层不受影响。
- **正向影响**：用户获得完整的自选列表管理能力（增删改查）、日线/分钟线双视图切换。
- **风险**：
  - `row_selectable` + `active_cell` 双点击模式：checkbox 选行（批量删除）与点击行任意位置（切换 K 线）可能互相干扰。`active_cell` 在点击 checkbox 时也会触发。**缓解**：`active_cell` 守卫判断 `column_id`，checkbox 列的 `id` 为 `"select"` 或保持无 column_id 时忽略（经实测 Dash DataTable checkbox 不触发 active_cell）。**待验证**。
  - 日线图与分钟线图的复权口径需保持一致逻辑，避免用户困惑"为什么日线是前复权但分钟线不是"。
  - 6 个回调争夺 `qb-watchlist-store.data` + `qb-table-container.children` 同一 Output（评审 D3）。**缓解**：删除/清空操作收敛到单个写回调，通过 `dash.ctx.triggered` 区分触发源；图表与健康度回调不写 watchlist-store。
  - 日线数据服务层缺失（评审 D1）：需要额外实现 `_fetch_daily_bars` 辅助函数，增加约 30 行代码。

---

## 13. 评审记录（开发 / 设计 / 测试）

> 评审日期 2026-07-28。基于代码走查（`quote_board.py` / `quote_callbacks.py`）与现有测试（`test_dash_data_strategy.py`）逐项核验。**结论：方案方向成立，但存在 5 处开发实现空洞、3 处设计细节、2 处测试断裂须修订 PRD 后方可进入研发。** 对应修订已并入 FR 详细需求、§9 代码改动清单、§10 验收测试。

### 13.1 开发视角

| 编号 | 发现 | 严重度 | 证据 | 修订动作 |
|---|---|---|---|---|
| D1 | **日线数据无服务层接口** | 高 | `DataCenterService` 仅有 `get_minute_bars()` 方法（`data_center_service.py` L644），无 `get_daily_bars()`。`bars_daily` 的查询仅在 `_quote_row` 的日线降级分支和 `factor_callbacks.py` 中以裸 SQL 方式硬编码。PRD §2.2 说"不修改数据服务层"但 FR-2.2 又依赖不存在的方法，自相矛盾。 | 在 `quote_callbacks.py` 内新增 `_fetch_daily_bars(ticker, limit, adj_mode)` 辅助函数，复用已有 `_get_db()`（非服务层修改）。已更新 FR-2.2（见上）和 §9。 |
| D2 | **DataTable 不支持行内组件，× 列不能用 pattern-matching** | 高 | Dash DataTable 的列仅支持 `text` / `markdown` / `numeric` 类型，无法嵌入 `dbc.Button` 或自定义组件。pattern-matching ID（`{"type": "remove", "index": ticker}`）在 DataTable 内无效。PRD §9 写 "pattern-matching" 不成立。 | 改用 `active_cell` 监听 DataTable 单元格点击：当 `active_cell.column_id == "remove"` 时，取 `data[active_cell.row]["code"]` 作为待删除 ticker。已更新 FR-1.1 和 §8 产品决策 5。 |
| D3 | **删除回调 Output 冲突：6 个回调争夺同一 Output** | 高 | 现有 3 个回调写 `qb-watchlist-store.data`（`update_watchlist`/`consume_focus_board`/`prune_watchlist_on_load`，均 `allow_duplicate=True`）。新增 3 个删除回调后共 6 个回调争夺同一 Output，`allow_duplicate` 虽允许注册但运行时触发链复杂，易出现不预期的覆盖顺序。 | 删除/清空操作收敛到**单个**写回调（`on_watchlist_mutation`），所有输出到 watchlist-store/table-container 的删除/清空触发源统一在该回调内用 `dash.ctx.triggered` 分流。保持 `consume_focus_board`/`prune_watchlist_on_load` 不变（它们非删除路径）。已更新 §8 产品决策 6 和 §9。 |
| D4 | **`active_cell` 与 `selected_rows` 交互冲突风险** | 中 | FR-2.3 用 `active_cell` 切换 K 线标的，FR-4 用 `selected_rows` 做批量删除。这两者在 Dash DataTable 中独立：点击 checkbox 只改 `selected_rows` 不触发 `active_cell`（实测确认）；点击单元格只改 `active_cell` 不改 `selected_rows`。因此无冲突，但点 × 列时应同时抑制图表切换。 | 在 `on_table_cell_click` 回调中，检查 `active_cell.column_id`：`"remove"` → 走删除逻辑，不写 `qb-chart-symbol`；其他列 → 切图表。已更新 FR-2.3 和 §8 决策 2。 |
| D5 | **`check_trading_hours` 仅导航触发，缺乏心跳联动** | 中 | 当前 `check_trading_hours` 的 Input 仅 `url.pathname`（`quote_callbacks.py` L379），只在导航到看板时执行一次。交易时段跨越（如 11:30 收盘、13:00 开盘、15:00 收盘）不会自动触发，导致非交易时段 auto-refresh 仍在运行。PRD FR-6 写"新增回调监听 qb-trading-status"但无定时器驱动。 | `check_trading_hours` 新增 `qb-refresh-interval.n_intervals` 作为第二个 Input，每 60 秒评估一次当前时间。输出同时写入 `qb-refresh-interval.disabled`（保持用户手动开关优先级更高）。已更新 FR-6 和 §9。 |
| D6 | **图表每 60 秒不必要重建** | 中 | `render_minute_chart` 以 `qb-refresh-interval.n_intervals` 为 Input（L518），每分钟重建一次 Candlestick figure，即使用户在未切换标的/周期。分钟线数据仅在 16:30 由后台任务更新，盘中不变。 | 从 `render_minute_chart` 移除 `n_intervals` Input。日线图同理（新增的 `render_daily_chart` 也不加 interval）。仅标的/周期变化时重建。已更新 §9。 |

### 13.2 设计视角

| 编号 | 发现 | 严重度 | 建议 |
|---|---|---|---|
| DES-1 | **× 移除列的可发现性** | 中 | DataTable 末尾的 "×" 列无列标题，用户可能不知道点击可删除。建议 hover 时显示 tooltip "移除此标的"，或列标题设 placeholder "操作"。 |
| DES-2 | **移除列与「去缓存」列位置** | 低 | 当前 8 列中「去缓存」在最右（第 8 列），「实时」在第 7 列。新增的"×"移除列应在「去缓存」之后（最右），与操作列集中，符合 Fitts 定律。 |
| DES-3 | **空自选与空图表状态** | 低 | FR-1.3 清空自选后需覆盖所有区域：表格区显示"自选列表为空"（已有），K 线区应同步显示"请先添加标的"，健康度显示"自选为空"。健康度已覆盖（`render_health` 已有 total==0 分支）。需新增 K 线区空态联动。 |
| DES-4 | **复权口径对分钟线的影响预期** | 低 | 当前复权口径（`qb-adj-mode`）仅影响表格中日线降级数据，不影响分钟线。用户可能在日线 Tab 使用复权口径，切换到分钟 Tab 时口径消失。建议在分钟 Tab 提示"复权口径仅影响日线数据"。 |

### 13.3 测试视角

| 编号 | 发现 | 严重度 | 动作 |
|---|---|---|---|
| T1 | **2 个现有测试会断裂** | 高 | `test_fetch_quote_data`（L766）：断言 `data[0]["name"] == "600519"` → FR-3 后 name 变为中文名（如 "贵州茅台"），断言失败。`test_build_quote_table`（L783）：data 中 `"name": "600519"` 同样需改为中文名。 | 更新这两个测试的 mock/断言，增加 symbol_dict 模拟。 |
| T2 | **回调注册顺序变化** | 中 | 新增 `on_watchlist_mutation` / `render_daily_chart` / `on_table_cell_click` / `check_trading_hours` 增 Input 后，`_nth(app, N)` 索引会偏移。现有测试 `test_update_watchlist_add` 用 `_nth(app, 1)` 取 `update_watchlist`（L836）。 | 评估改用 `by_output("qb-watchlist-store")` 代替 `_nth` 索引（如 `test_query_redesign.py` 的做法），消除顺序依赖。或重新核验调整后的索引值。 |
| T3 | **symbol_dict 查询需 mock** | 中 | FR-3 的 name_map 查询涉及 `symbol_dict` 表。现有测试的 `FakeDuckDB` 未模拟该表，FR-3 实现后现有 mock 会因查询无数据返回空名称而降级为代码。 | 需在 `FakeDuckDB` 中增加 `symbol_dict` 查询模拟，或新增独立的 mock 路径。 |

### 13.4 评审结论与必改项

- **方向 ✅**：删除标的、日 K 线、无效交互修复均成立，无需推翻。
- **进入研发前必须完成**：① 确认 `_fetch_daily_bars` 实现路径（D1，已改 FR-2.2/§9）；② × 列改用 `active_cell` 而非 pattern-matching（D2，已改 FR-1.1/§8）；③ 删除回调收敛策略确认（D3，已改 §8/§9）；④ `check_trading_hours` 心跳联动方案（D5，已改 FR-6/§9）；⑤ 更新 2 个断裂测试并考率 `by_output` 化（T1/T2，已改 §10）。
- **风险等级：中**。改动集中在行情看板 Tab，不触服务层/数据中心/策略中心。

### 13.5 修订历史

- v1.0 (2026-07-28) 初稿：B1-B8 问题识别、FR-1~7、信息架构、里程碑。
- v1.1 (2026-07-28) 评审修订：新增 §13 评审记录；据此修订 FR-1.1（× 列实现方案）、FR-2.2（日线数据获取路径 + D1）、FR-2.3（active_cell 细节）、FR-5（已支持 adj_mode 仅缺透传）、FR-6（心跳联动 + D5）、§8（决策 5/6）、§9（代码改动清单逐项核验）、§10（测试矩阵 + T1/T2 断裂标注）、§12（新增 D1/D3 风险项）。

---

> 附录：线框图与交互流程图见本对话内的可视化组件。
