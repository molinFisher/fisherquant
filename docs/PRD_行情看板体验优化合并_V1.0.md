# 行情看板 · 体验优化合并 PRD（V1.0 合并稿）

> 合并日期：2026-07-29 ｜ 状态：合并稿（含原三视角评审，未进入研发）
> 合并来源（4 份，已归档于 `docs/archive/`）：
> - `PRD_行情看板交互优化_V1.0.md`（v1.1，B1–B8）
> - `PRD_行情看板页体验优化_V1.0.md`（v1.1，S1–S3）
> - `行情看板二期优化建议.md`（v1.1，W1–W3）
> - `行情看板日线图优化建议.md`（v1.1，V1–V5）
>
> 关联页面：`/market-watch`（行情看板）、`/data-center`（数据查询/目录）
> 关联代码：`fisher/dash_app/pages/quote_board.py`、`fisher/dash_app/callbacks/quote_callbacks.py`、`fisher/dash_app/callbacks/data_callbacks.py`
> 说明：本稿消除原 4 份文档的交叉重复（日 K 线、范围选择、搜索筛选多处重叠），统一需求编号与验收标准，保留全部实现注意事项（开发/设计/测试评审中的技术陷阱）。

---

## 0. 背景与目标

行情看板是用户日常盯盘与补数据的核心入口。经多轮走查与代码审计，问题集中在五类：**自选不可管、图表太弱、补齐路径断、口径/时段不一致、搜索筛选缺失**。本合并稿把它们重整为 8 个主题需求（§4），便于一次性交付。

**目标**：让用户能完整管理自选、看增强后的 K 线（日/分钟双视图 + 量价/均线）、从看板一键补齐缺口、口径与时段行为一致、并能快速搜索筛选标的。

**非目标（本次不做）**：不引入实时推送（WebSocket/SSE）；不修改数据服务层接口签名；不做多图表联动（除日 K 线成交量副图外）；不做节假日表（仅跳过周末）。

---

## 1. 问题全景（合并去重）

| 主题 | 原编号 | 用户感知问题 | 严重度 |
|---|---|---|---|
| 自选管理 | B1 | 无法删除标的（无删除入口，只能手编 `watchlist.json`） | P0 |
| 自选管理 | B4 | "名称"列显示代码而非中文名 | P1 |
| 自选管理 | B5 | 行选中（checkbox）无任何作用 | P1 |
| 图表·日线 | B2/B3 | 只有分钟 K 线、看不到日 K 线；K 线始终画第一个标的 | P0 |
| 图表·日线 | V1 | 日 K 线无成交量柱，无法判断量价 | P0 |
| 图表·日线 | V2 | 日 K 线无均线（MA5/10/20） | P0 |
| 图表·日线 | V3/W3 | 日 K 线时间范围固定（120 根）且无周末留白处理 | P1 |
| 图表·日线 | V5 | 图表偏矮（320px）、信息密度低 | P2 |
| 图表·日线 | S3 | 日 K 线仅 4 档固定周期，不支持自定义起止日期 | P1 |
| 图表·分钟 | S1 | 分钟 K 线午休（11:30–13:00）出现空白带，像"断图" | P0 |
| 补齐链路 | S2 | 看板"去缓存/批量去缓存补齐"跳转后未带入待缓存标的，需重选 | P0 |
| 口径/时段 | B6 | 复权口径在手动刷新后丢失 | P1 |
| 口径/时段 | B7 | 非交易时段 60s 定时器空转查库 | P2 |
| 口径/时段 | B8 | 健康度仪表盘每 60s 闪烁重建 | P2 |
| 搜索筛选 | W1 | 看板内无筛选搜索，几十标的中手动找 | P0 |
| 搜索筛选 | W2 | 添加搜索仅限已缓存标的，未缓存标的无法加入看板 | P0 |

---

## 2. 信息架构（合并后）

```
行情看板（/market-watch）
├─ 工具栏 Row
│   ├─ 搜索添加（全量搜索 Dropdown，multi=True）【W2】
│   ├─ 看板内筛选 Input【W1】
│   ├─ 手动刷新 + 自动刷新(60s) + 清空自选【B1】
├─ 参数 Row
│   ├─ 复权口径【保留，刷新保持 B6】
│   └─ 分钟周期【不变】
├─ 健康度仪表盘【仅在池变化时重建 B8】
├─ 行情表格
│   └─ 列：代码 | 名称(中文) | 最新价 | 涨跌幅 | 成交量 | 覆盖度 | 实时 | 去补齐 | 移除(×)
│   └─ 行选中 → 批量删除【B5】；行点击 → 切换 K 线标的【B3】
└─ K 线区（Tabs：分钟线 / 日线）
    ├─ 分钟线 Tab：rangebreaks 隐藏午休【S1】
    └─ 日线 Tab：成交量副图 + 均线 + 时间范围(固定档+自定义) + 跳过周末【V1-V5,S3】
```

---

## 3. 功能需求（FR，按主题分组）

### 3.1 自选管理 — 删除 / 中文名 / 行选中（B1/B4/B5）

**FR-1.1 单行移除**：DataTable 新增 `remove` 列（text 类型，每行 "×"）。用 `active_cell` 监听点击：当 `active_cell.column_id == "remove"` 时，取 `data[row]["code"]` 作为待删标的 → 从 watchlist 移除 → 保存 → 刷新。**不二次确认**（误删可重加）。

**FR-1.2 选中批量删除**：保留 `row_selectable="multi"`，选中后显示"删除选中 (N)"按钮 → 批量移除选中标的。选中为 0 时按钮隐藏。

**FR-1.3 清空自选**：工具栏"清空自选"按钮（`danger` + `dbc.Modal` 二次确认）→ 确认后 `watchlist=[]`。

**FR-1.4 名称列中文名**：`_quote_row` 新增 `name_map` 参数，按 `ticker.split(".")[0]` 查 `symbol_dict` 取中文名；未命中降级显示代码。

> **删除回调收敛（关键）**：单行× / 批量删 / 清空 三路删除统一收敛到**单个**写回调（如 `on_watchlist_mutation`），用 `dash.ctx.triggered` 分流输出到 `qb-watchlist-store.data` / `qb-table-container.children`；其余写同一 Output 的回调（`consume_focus_board`/`prune_watchlist_on_load`）保持 `allow_duplicate`。

### 3.2 图表·日 K 线新增与标的可切换（B2/B3）

**FR-2.1 K 线 Tabs**：原单 `dcc.Graph` 包入 `dbc.Tabs`，分"分钟线/日线"。
**FR-2.2 日 K 线图**：新增 `qb-daily-chart`（`dcc.Graph`）。日线数据经 `_fetch_daily_bars(ticker, limit=120, adj_mode)` 直接查 `bars_daily`（服务层无 `get_daily_bars`，在回调内复用 `_get_db()`，不改动服务层签名）。
**FR-2.3 点击行切换标的**：新增 `dcc.Store(id="qb-chart-symbol", data=watchlist[0])`；`active_cell` 监听行点击（忽略 `remove` 列）→ 写 `qb-chart-symbol`；分钟/日 K 线均以它为 State。当前标的在表格高亮。

### 3.3 图表·日 K 线增强（V1–V5 + W3）

**FR-3.1 成交量柱（P0-1）**：`_build_daily_chart` 改用 `make_subplots(rows=2, shared_xaxes=True, row_heights=[0.75,0.25])`，row2 成交量柱；颜色按中国惯例 `close >= open → 红`，否则绿。
**FR-3.2 均线（P0-2）**：主图叠加 MA5/MA10/MA20（浅蓝/橙/紫）。MA 值在 `_fetch_daily_bars` 中预计算（`ma5/ma10/ma20` 字段），不足周期赋 `None` 跳过绘制。参数固定不可配。
**FR-3.3 时间范围固定档（P1-1）**：日线 Tab 内 `qb-daily-range` RadioItems（1月/3月/6月/1年 = 20/60/120/250，默认 6月）。`render_daily_chart` 新增 Input 透传 limit。
**FR-3.4 跳过周末留白（W3）**：`_build_daily_chart` 设 `rangebreaks=[dict(bounds=["sat","mon"])]`（subplot 中须 `row=1`）。法定节假日不自动识别（留待后续）。
**FR-3.5 美化（P2-1）**：标题含口径标识（不复权/前复权/后复权）；`hovermode="x unified"`；`rangeslider_visible=True`（subplot 须 `row=1`）；浅色网格；图表加高。

### 3.4 图表·日线自定义时间区间（S3）

**FR-4 自定义时间段**：`qb-daily-range` 增加"自定义"选项 → 显示 `dcc.DatePickerRange(start, end)`；`render_daily_chart` 在 `daily_range == "custom"` 时按 `[start, end]` 走 `_fetch_daily_bars` 的 `WHERE trade_date BETWEEN ? AND ?` 分支（**必须显式 `if daily_range == "custom"` 分支**，否则字符串 "custom" 被当 limit → 生产 bug）。区间空/单边回退默认 6月并提示。

### 3.5 图表·分钟线午休隐藏（S1）

**FR-5 分钟线 rangebreaks**：`_build_minute_chart` 设 `rangebreaks=[dict(bounds=["11:30","13:00"])]` + `hovermode="x unified"`；不破坏 rangeslider。多周期（1/5/15/30/60m）均生效。隔夜跳空保持原样（本期不处理）。

### 3.6 数据补齐链路 — 去补齐带入待缓存池（S2）

**FR-6 去补齐带入标的**：
- 行内链接改文案「**去补齐**」，跳转 `/data-center?tab=tab-query&focus={sym}&data_type=daily`（落到**获取数据**页而非已缓存页）。
- "批量去缓存补齐" 读 `_load_watchlist()` 取全部标的 → 跳 `/data-center?tab=tab-query&symbols={逗号分隔,≤20}&data_type=daily`。
- 数据查询页**新增 `consume_cache_intent`** 回调：消费 `?focus=`/`?symbols=` → 预填 `selected-symbols-store`（同构 `[{"value":t,"label":t}]`）→ 切 `active_tab="tab-query"` → 清除参数（复用 `_strip_focus` 扩展剥 `symbols`/`data_type`/`tab`）。
- 预填后顶部显式提示「已从看板带入 N 个标的」。

> **互补既有 `consume_focus`**：既有 `consume_focus`（处理 `tab=tab-cached` 已缓存筛选）保留不破坏；新 `consume_cache_intent` 三输出（`selected-symbols-store` / `data-center-tabs.active_tab` / `url.search`）**全部 `allow_duplicate=True`**（因既有写方无 allow_duplicate）。两者按 `tab` 分流、互不冲突。

### 3.7 实时/口径/健康度（B6/B7/B8）

**FR-7 复权口径刷新保持（B6）**：`update_watchlist` 新增 `State("qb-adj-mode","value")` 透传 `adj_mode` 到 `_fetch_quote_data`（该函数已支持 adj_mode 参数，仅原调用缺透传）。
**FR-8 交易时段联动（B7）**：`check_trading_hours` 改为双 Input（`url.pathname` + `qb-refresh-interval.n_intervals`），每 60s 评估，非交易时段输出 `qb-refresh-interval.disabled=True`；用户手动开关优先级最高。
**FR-9 健康度不闪烁（B8）**：`render_health` 移除 `n_intervals` Input，仅 `qb-watchlist-store.data` 变化才重建。

### 3.8 搜索与筛选（W1/W2）

**FR-10 看板内筛选（W1）**：DataTable 上方新增 `qb-table-filter` Input；新增回调 Output `qb-data-table.data`，State 全量数据，按 `code`/`name` 不区分大小写过滤；空输入恢复全部。不影响删除/计数。
**FR-11 全量搜索添加（W2）**：
- `qb-add-symbol-dropdown` 改 `multi=True` + 动态搜索：监听 `search_value` → 调 `get_data_service().search_symbols(query)`（全市场 A/港股，复用现有服务，前 20 条）。
- **放开 `_is_dead_symbol` 拦截**：未缓存标的允许加入 watchlist，表格标记"等待获取"；添加时若无任何数据则同步 `fetch_bars([symbol], daily)` 拉日线。
- `update_watchlist` 适配 `new_symbol` 为 `list` 时遍历去重添加。

---

## 4. 验收标准（合并）

| 编号 | 覆盖 | 验收要点 |
|---|---|---|
| A1 | FR-1.1/1.2/1.3 | 行× 删除即时生效并同步 `watchlist.json`；批量删/清空（带确认）可用 |
| A2 | FR-1.4 | 名称列显示中文名；未命中降级代码 |
| A3 | FR-2.2/2.3 | 日/分钟 Tabs 切换；点行切换 K 线标的并高亮 |
| A4 | FR-3.1/3.2/3.4/3.5 | 日线含成交量副图（阳红阴绿）、MA5/10/20、跳过周末、hover 统一、rangeslider 可拖 |
| A5 | FR-3.3/FR-4 | 固定档切换 limit 生效；"自定义"按起止区间加载、空区间回退默认 |
| A6 | FR-5 | 分钟线午休无空白带，多周期均生效 |
| A7 | FR-6 | 单行/批量"去补齐"落点激活获取数据 Tab 且预填待缓存池（≤20），刷新不重复预填 |
| A8 | FR-7/8/9 | 刷新保持口径；非交易时段停自动刷新；健康度心跳不重建 |
| A9 | FR-10/11 | 看板内筛选生效；全量搜索可加未缓存标的并标记"等待获取" |

---

## 5. 代码改动清单（合并去重）

| 对象 | 位置 | 处理 | 关联 FR |
|---|---|---|---|
| `qb-minute-chart` | quote_board.py | 包入 Tabs；新增日线 Tab | 2.1 |
| `qb-daily-chart`（新） | quote_board.py | 日线 Graph | 2.2 |
| `qb-chart-symbol`（新） | quote_board.py | Store 当前 K 线标的 | 2.3 |
| `qb-delete-selected-btn`/`qb-clear-all-btn`/`qb-clear-modal`（新） | quote_board.py | 批量删/清空/确认弹窗 | 1.2/1.3 |
| `qb-table-filter`（新） | quote_board.py | 筛选 Input | 10 |
| `qb-daily-range`（改） | quote_board.py | 加"自定义" + DatePickerRange | 3.3/4 |
| `qb-add-symbol-dropdown`（改） | quote_board.py | `multi=True` | 11 |
| DataTable `remove` 列 / 名称 / 高亮 | quote_board.py `_build_quote_table`/`_quote_row` | active_cell 取 ticker；name_map；chart_symbol 高亮 | 1.1/1.4/2.3 |
| `_fetch_daily_bars`（改） | quote_callbacks.py | 预计算 ma5/10/20；新增 `start`/`end` BETWEEN 分支 | 3.2/4 |
| `_build_daily_chart`（重写） | quote_callbacks.py | make_subplots 双行；成交量+均线+rangebreaks(row=1)+hover+rangeslider | 3.1–3.5 |
| `_build_minute_chart`（改） | quote_callbacks.py | rangebreaks 午休 + hovermode unified | 5 |
| `render_daily_chart`（改） | quote_callbacks.py | 新增 `qb-daily-range` Input + `qb-daily-custom-range` 起止；显式 `if daily_range=="custom"` | 3.3/4 |
| `render_minute_chart`（改） | quote_callbacks.py | 读 `qb-chart-symbol`；移除 n_intervals Input | 2.3 |
| `on_table_cell_click`（新） | quote_callbacks.py | active_cell 分流出删除/切图表 | 1.1/2.3 |
| `on_watchlist_mutation`（新） | quote_callbacks.py | 三路删除统一收敛 | 1.1/1.2/1.3 |
| `on_delete_selected`（新） | quote_callbacks.py | selected_rows → 批量删 | 1.2 |
| `on_clear_watchlist_confirm`（新） | quote_callbacks.py | 清空确认 | 1.3 |
| `check_trading_hours`（改） | quote_callbacks.py | 双 Input + 输出 disabled | 8 |
| `render_health`（改） | quote_callbacks.py | 移除 n_intervals Input | 9 |
| `update_watchlist`（改） | quote_callbacks.py | 透传 adj_mode；适配 list 新增；放开死标拦截 | 7/11 |
| 行内 `goto_cache` 链接（改） | quote_callbacks.py | 改「去补齐」+ `tab=tab-query&focus=&data_type=` | 6 |
| `batch_goto_cache`（改） | quote_callbacks.py | 读 `_load_watchlist()` 拼 `symbols=` | 6 |
| `consume_cache_intent`（新） | data_callbacks.py | 消费 focus/symbols 预填待缓存池，三输出 allow_duplicate | 6 |
| 看板内筛选回调（新） | quote_callbacks.py | qb-table-filter → qb-data-table.data | 10 |
| 搜索下拉回调（新） | quote_callbacks.py | search_value → search_symbols | 11 |

---

## 6. 里程碑

| 阶段 | 内容 | 估时 |
|---|---|---|
| P1 | 自选管理（删除/清空/中文名/行选中）+ 看板内筛选 | 1.5d |
| P2 | 日 K 线新增 + 标的切换 + 增强（量/均线/周末/美化） | 1.5d |
| P3 | 日线范围（固定档+自定义）+ 分钟午休 | 1d |
| P4 | 去补齐带入待缓存池 + 全量搜索添加 | 1.5d |
| P5 | 口径/时段/健康度修复 + 单测补充 + 手工验收 | 1d |

---

## 7. 评审记录（开发 / 设计 / 测试 合并要点）

> 评审日期 2026-07-28/29，基于代码走查。下列为**必须落地的技术陷阱**（合并去重后）。

### 7.1 开发视角（D，关键）
- **D-删除 Output 冲突**：6 回调争 `qb-watchlist-store.data`，须收敛单写回调 + `dash.ctx.triggered` 分流（B3 评审）。
- **D-active_cell 非 pattern-matching**：DataTable 不支持行内组件，× 列用 `active_cell.column_id=="remove"` 取 `data[row]["code"]`，不可 pattern-matching。
- **D-consume_cache_intent 三输出 allow_duplicate**：既有 `consume_focus`/`sync_selected_pool` 无 allow_duplicate，新回调必须全加（S2 评审 D-1/D-4）。
- **D-预填同构**：`selected-symbols-store` 元素须 `[{"value":ticker,"label":name}]`，否则 `fetch_data` 读 `item["value"]` 出错。
- **D-daily_range 类型混合**：`if daily_range == "custom"` 必须显式分支，否则 "custom" 被当 limit（S3 R6/D-8）。
- **D-rangebreaks 在 subplot 须 row=1**：日线 `make_subplots` 下 `update_xaxes(rangebreaks=..., row=1)`（V/W3 评审 D5）。
- **D-make_subplots 必导入**：`from plotly.subplots import make_subplots`，裸 Figure 不支持多行子图（V 评审 D1）。
- **D-MA 在 `_fetch_daily_bars` 计算**：每根 bar 附 ma5/10/20，不足周期 None（V 评审 D2/D4）。
- **D-批量删 search_value 与 value 分离**：`dcc.Dropdown` 搜索回调以 `search_value` 为 Input、仅 Output `options`（W2 评审 D3）。
- **D-初始加载仍用 `load_qb_symbols`**：搜索回调只处理用户输入，两者不冲突（W2 评审 D4）。

### 7.2 设计视角（DES）
- **DES-去补齐命名**：行内文案改「去补齐/去获取」，落点与语义对齐（S2 DES-1）。
- **DES-带入后显式提示**：顶部 alert「已从看板带入 N 个标的」（S2 DES-2）。
- **DES-时间选择器置于日线 Tab 内**：避免分钟 Tab 下出现不相关控件（V DES-3）。
- **DES-成交量阳红阴绿**：`close >= open` 为红（V DES-1）。
- **DES-筛选框独立 Row**：与批量删除 bar 分区（W2 DES-1）。
- **DES-未缓存标的可同步拉日线**：添加时若无数据调 `fetch_bars`（W2 DES-2）。

### 7.3 测试视角（T）
- **T-断裂测试**：`test_fetch_quote_data`/`test_build_quote_table` 断言 `name=="600519"` 在 FR-1.4 后失效，须改中文名 mock；`test_update_watchlist_add` 须适配 `multi=True` 的 list 入参。
- **T-回调索引偏移**：新增回调后 `_nth(app, N)` 偏移，建议改 `by_output(...)` 消除顺序依赖。
- **T-_rangebreaks 单测**：直接调 `_build_minute_chart` 断言 `layout.xaxis.rangebreaks` 含午休 bounds。
- **T-consume_cache_intent**：用 `by_output("selected-symbols-store","data")` 定位，断言形状/active_tab/回写 search 已剥参。
- **T-_build_daily_chart 无现测**：须补成交量副图、均线数值、hovermode、空 symbol 边界等单测（需 mock `_get_db`）。

---

## 8. 修订历史
- 2026-07-28/29 原 4 份 PRD 各自初稿 + 三视角评审（v1.1）。
- 2026-07-29 **合并稿 V1.0**：消除 4 份交叉重复（日 K 线、范围选择、搜索筛选），统一 FR/验收/代码清单/评审要点，原 4 份归档 `docs/archive/`。
