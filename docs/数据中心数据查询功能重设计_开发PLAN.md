# 数据中心 · 数据查询功能重设计 — 开发 PLAN

| 项 | 内容 |
|---|---|
| 文档版本 | v1.0 |
| 对应 PRD | `数据中心数据查询功能重设计PRD.md` v1.1 |
| 作者 | 研发 |
| 日期 | 2026-07-28 |
| 状态 | **已实现**（master `8583966`/`3b5460f`） |
| 关联文件 | `fisher/dash_app/pages/data_center.py`（布局）<br>`fisher/dash_app/callbacks/data_callbacks.py`（回调）<br>`tests/unit/test_query_redesign.py`（单元测试 16 项）<br>`tests/integration/test_symbol_search_flow.py`（集成测试）<br>`tests/integration/test_symbol_search_uat.py`（UAT 测试） |

---

## 目录

1. [目标与范围](#1-目标与范围)
2. [架构总览](#2-架构总览)
3. [任务拆解](#3-任务拆解)
4. [实施顺序与依赖](#4-实施顺序与依赖)
5. [关键代码改动](#5-关键代码改动)
6. [测试计划](#6-测试计划)
7. [验收对照表](#7-验收对照表)
8. [风险管理](#8-风险管理)

---

## 1. 目标与范围

### 1.1 目标

根据 PRD v1.1 五大诉求（A1-A5），重设计"数据查询"Tab 的交互架构：

- **A1** 取消重复搜索框 → 全 Tab 仅保留一个 `symbol-search-input`
- **A2** 失焦/回车即检索 → 候选可多选替代 Dropdown
- **A3** 空池不能点击 → `fetch-data-button` 物理禁用 + 守卫提示
- **A4** 去批量录入框 → 多选候选 + 多代码粘贴为批量主路径
- **A5** 删财务查询模块 → 独立 Card/Modal 全部移除，取数口径保留

### 1.2 非目标

- 不改服务层 `search_symbols` / `fetch_bars` 接口签名
- 不改「已缓存数据/自动加载/高级功能」三个 Tab
- 不引入后端批量任务队列
- 不做财务数据可视化

### 1.3 影响面

| 模块 | 影响 | 说明 |
|---|---|---|
| `data_center.py` | **修改** | 重写 `_create_query_tab` 布局 |
| `data_callbacks.py` | **修改** | 新增 `sync_selected_pool` / `guard_fetch_button` / `render_selected_pool`；重写 `search_symbols` 输出 4→3 |
| `tests/unit/test_query_redesign.py` | **新增** | 16 项单元测试 |
| `tests/integration/test_symbol_search_flow.py` | **修改** | `test_search_store_to_fetch_list_card` → `test_search_store_to_selected_pool` |
| `tests/integration/test_symbol_search_uat.py` | **修改** | `test_uat_05` 4→3 元组解包 |
| 服务层 / 其他 Tab | **无影响** | 接口不变，Cache/自动加载 Tab 零牵连 |

---

## 2. 架构总览

### 2.1 数据流

```
用户输入 → symbol-search-input (debounce)
              │ 回车/失焦
              ▼
       search_symbols (回调)
              │
              ├─ 模糊名/拼音 → 单次搜索
              └─ 多代码(逗号/空格/换行) → 逐 token 搜索 → 合并去重
              │
              ▼
       candidate-list (待选框·可多选)
              │ 勾选/全选/反选/×移除
              ▼
       selected-symbols-store (单一事实来源)
              │
              ├─▶ render_selected_pool → selected-pool (chips)
              └─▶ guard_fetch_button → fetch-data-button.disabled
                       │ 非空 + 点击
                       ▼
                  fetch_data → fetch-results (仅取数结果，不覆盖池)
```

### 2.2 组件对应表

| 组件 ID | 类型 | 用途 | PRD 引用 |
|---|---|---|---|
| `symbol-search-input` | `dbc.Input` | 唯一搜索入口；失焦/回车触发 | FR-1/FR-2 |
| `search-status` | `html.Div` | 结果计数 + 市场分布 + 状态提示 | FR-3 |
| `candidate-list` | `dbc.Checklist` | 可多选待选框；结果列表 | FR-3 |
| `candidate-select-all-btn` | `dbc.Button` | 全选当前结果集（含已有池条目） | FR-3 |
| `candidate-invert-btn` | `dbc.Button` | 反选当前结果集 | FR-3 |
| `search-results-store` | `dcc.Store` | 搜索结果元数据（供池同步用） | §8 |
| `selected-symbols-store` | `dcc.Store` | **新** 已选池单一事实来源 | FR-4 |
| `selected-pool` | `dbc.CardBody` | **新** 已选池 chips 渲染 | FR-4 |
| `clear-selected-btn` | `dbc.Button` | **新** 清空整个已选池 | FR-4 |
| `fetch-data-button` | `dbc.Button` | 取数触发；空池 `disabled` | FR-5 |
| `fetch-guard-hint` | `html.Div` | **新** 空池/财务限制常驻提示 | FR-5/DES-4 |
| `fetch-results` | `dbc.CardBody` | **新** 取数结果展示（D2 拆离池） | D2 |

### 2.3 已删除组件

| 组件 ID | 原因 |
|---|---|
| `financials-symbol-input` | A1/A5 删除 |
| `query-financials-btn` | A5 删除（死按钮） |
| `financials-modal` / `financials-modal-body` / `close-financials-modal` | A5 删除 |
| `batch-symbols-input` | A4 删除 |
| `symbol-search-results`（Dropdown） | A2 被 `candidate-list` 取代 |
| `fetch-list` | A4 拆为 `selected-pool` + `fetch-results` |

---

## 3. 任务拆解

### P1 删除财务模块与重复框（PRD 估时 0.5d）

| 任务 ID | 名称 | 文件 | 状态 |
|---|---|---|---|
| P1-1 | 删除"财务数据查询"Card 及 `financials-symbol-input` | `data_center.py` | ✅ 已实现 |
| P1-2 | 删除 `_create_financials_modal()` 及关联 Modal 组件 | `data_center.py` | ✅ 已实现 |
| P1-3 | 删除 `batch-symbols-input`（Textarea） | `data_center.py` | ✅ 已实现 |
| P1-4 | 删除回调 `close_modal` / `clear_single_search_on_batch` | `data_callbacks.py` | ✅ 已实现 |
| P1-5 | 布局验证：财务死组件 ID 不存在、新组件 ID 存在 | `test_query_redesign.py` | ✅ 已覆盖 `test_financials_module_removed` / `test_new_components_present` |

### P2 搜索与待选框（PRD 估时 1d）

| 任务 ID | 名称 | 文件 | 状态 |
|---|---|---|---|
| P2-1 | 重写 `_create_query_tab` 左列布局：Card「标的搜索」内含 `symbol-search-input` + `search-status` + `candidate-list` + 工具行(全选/反选) | `data_center.py` | ✅ 已实现 |
| P2-2 | 重写 `search_symbols` 回调：3 输出(new)，多代码拆分逻辑 | `data_callbacks.py` | ✅ 已实现 |
| P2-3 | 新增 `candidate-list` 组件（`dbc.Checklist` 富标签 + market/pinyin） | `data_center.py` | ✅ 已实现 |
| P2-4 | 多代码粘贴解析：`_SPLIT_RE` 正则 + 逐 token 搜索 + 去重 + 未收录标灰 | `data_callbacks.py` | ✅ 已实现 |
| P2-5 | 搜索三态提示：<2字符 / 字典初始化中 / 无结果 / 有结果统计 | `data_callbacks.py` | ✅ 已实现 |

**设计决策**（来自 DES-5）：`symbol-search-input` 的 `placeholder` 已设为"搜索名称、代码或拼音，或粘贴多个代码(用逗号/空格分隔)"，取代纯"搜索标的"。

### P3 已选池 + 按钮守卫（PRD 估时 1d）

| 任务 ID | 名称 | 文件 | 状态 |
|---|---|---|---|
| P3-1 | 新增 `selected-symbols-store`（`dcc.Store data=[]`） | `data_center.py` | ✅ 已实现 |
| P3-2 | 新增 `sync_selected_pool` 回调：候选勾选 → 池同步；全选/反选作用于当前结果集；×移除；清空已选；重渲染 `no_update` 保护 | `data_callbacks.py` | ✅ 已实现 |
| P3-3 | 新增 `render_selected_pool` 回调：池 chips 渲染（名称+代码+市场徽标+×）；空态提示"尚未选择标的"；财务/复权港股 chip 黄色警示 | `data_callbacks.py` | ✅ 已实现 |
| P3-4 | 新增 `guard_fetch_button` 回调：空池 `disabled=True` + 提示"已选池为空"；财务模式全港股禁用/混合提示跳过 | `data_callbacks.py` | ✅ 已实现 |
| P3-5 | `fetch_data` 改源：`symbols` 取自 `selected-symbols-store`；结果写 `fetch-results`（D2 修复）；保留 `MAX_FETCH_SYMBOLS=20` 上限 | `data_callbacks.py` | ✅ 已实现 |
| P3-6 | 新增 `fetch-results`（右列第二个 CardBody）+ `fetch-guard-hint` | `data_center.py` | ✅ 已实现 |

**D2 冲突锁定**：`fetch_data` 的 Output 为 `fetch-status` / `fetch-results`，不再注册到 `selected-pool` 或 `selected-symbols-store`。由测试 `test_fetch_does_not_write_pool` 锁定。

### P4 测试补充与验收（PRD 估时 0.5d）

| 任务 ID | 名称 | 状态 |
|---|---|---|
| P4-1 | 单元测试：池同步 7 项（勾选入池、取消出池、非当前集保留、全选作用域、反选、×移除、重渲染保护、清空） | ✅ `TestPoolSync` (8 tests) |
| P4-2 | 单元测试：按钮守卫 5 项（空池禁用、非空可点、财务全港股禁用、财务混合提示、财务全A可点） | ✅ `TestFetchGuard` (5 tests) |
| P4-3 | 单元测试：布局校验 3 项（死组件不在、新组件存在、财务 radio 保留） | ✅ `TestLayoutRedesign` (3 tests) |
| P4-4 | 单元测试：D2 锁（`fetch_data` 不输出池/store） | ✅ `test_fetch_does_not_write_pool` |
| P4-5 | 集成测试：`test_search_store_to_selected_pool`（搜索→store→勾选入池→chips 渲染全链路） | ✅ `test_symbol_search_flow.py` |
| P4-6 | 集成测试：`test_uat_05` 已改为 3 元组解包 | ✅ `test_symbol_search_uat.py` |
| P4-7 | `TestMultiCodePaste`（19 项）— 多代码粘贴（逗号/空格/换行/中文逗号/分号）→ 候选条数 + 未收录标灰验证 + 去重 + store/status 校验 | ✅ 已实现（19 passed） |

---

## 4. 实施顺序与依赖

```
P1 ──── 删除财务模块
  │
  └──▶ P2 ──── 搜索+待选框
          │
          └──▶ P3 ──── 池+守卫+取数
                  │
                  └──▶ P4 ──── 测试+验收
```

依赖图：
- P1 无依赖（纯删除，可独立完成）
- P2 依赖 P1（布局基线清理后增删新组件 ID 干净）
- P3 依赖 P2（`selected-symbols-store` 依赖 `sync_selected_pool` 回调注册）
- P4 依赖 P2+P3（测试依赖回调注册完毕）

---

## 5. 关键代码改动

### 5.1 `data_center.py` 布局改动

```python
# 删除
batch_symbols_input = dbc.Textarea(id="batch-symbols-input", ...)      # L174-188（旧）
financials_card = dbc.Card([...], id="financials-card")                 # L138-157（旧）
_financials_modal = _create_financials_modal()                          # L261-272（旧）

# 新增至左列 Card「标的搜索」
dbc.Checklist(id="candidate-list", options=[], value=[], ...)           # 待选框
dbc.Button("全选", id="candidate-select-all-btn", ...)                  # 工具行
dbc.Button("反选", id="candidate-invert-btn", ...)                      # 工具行

# 新增至右列
dcc.Store(id="selected-symbols-store", data=[])                         # 已选池 Store
dbc.CardBody(id="selected-pool", children="尚未选择标的...")            # 池渲染
dbc.Button("清空已选", id="clear-selected-btn", ...)                    # 清空按钮
dbc.CardBody(id="fetch-results", children="取数结果将显示在这里")       # 取数结果（D2）
html.Div(id="fetch-guard-hint", ...)                                    # 守卫提示（DES-4）
```

### 5.2 `data_callbacks.py` 回调改动

```python
# ── 回调注册顺序（Dash 注册顺序 = 回调发现顺序）──

# 1. search_symbols（P2-2）
@app.callback(
    Output("candidate-list", "options"),    # [new] 替代原 Output("symbol-search-results", "options")
    Output("search-status", "children"),    # 保留
    Output("search-results-store", "data"),  # 保留
    Input("symbol-search-input", "value"),
)
def search_symbols(query): ...  # 4→3 元组；多代码拆分

# 2. sync_selected_pool（P3-2）[new]
@app.callback(
    Output("selected-symbols-store", "data"),
    Output("candidate-list", "value"),
    Input("candidate-list", "value"),
    Input("candidate-select-all-btn", "n_clicks"),
    Input("candidate-invert-btn", "n_clicks"),
    Input("clear-selected-btn", "n_clicks"),
    Input({"type": "pool-remove", "index": ALL}, "n_clicks"),
    State("search-results-store", "data"),
    State("selected-symbols-store", "data"),
)
def sync_selected_pool(...): ...

# 3. render_selected_pool（P3-3）[new]
@app.callback(
    Output("selected-pool", "children"),
    Input("selected-symbols-store", "data"),
    Input("data-type-radio", "value"),
)
def render_selected_pool(...): ...

# 4. guard_fetch_button（P3-4）[new]
@app.callback(
    Output("fetch-data-button", "disabled", allow_duplicate=True),
    Output("fetch-guard-hint", "children"),
    Input("selected-symbols-store", "data"),
    Input("data-type-radio", "value"),
)
def guard_fetch_button(...): ...

# 5. fetch_data（P3-5 改写）
@app.callback(
    Output("fetch-status", "children"),
    Output("fetch-results", "children"),    # [new] 替代原 Output("fetch-list", "children")
    Input("fetch-data-button", "n_clicks"),
    State("selected-symbols-store", "data"),  # [new] 替代 State("search-results-store")
    State("date-range-picker", "start_date"),
    State("date-range-picker", "end_date"),
    State("data-type-radio", "value"),
    State("minute-period-selector", "value"),
)
def fetch_data(...): ...

# 6. toggle_minute_period（保留不变）

# ── 已删除 ──
# update_fetch_list（被 render_selected_pool + sync_selected_pool 替代）
# clear_single_search_on_batch（batch-symbols-input 已删）
# close_modal / _create_financials_modal（财务模块已删）
```

### 5.3 关键实现细节

**多代码拆分**（`_SPLIT_RE`）：
```python
_SPLIT_RE = re.compile(r"[,\uFF0C;\uFF1B\s]+")
# 支持：英文逗号 ","、中文逗号 "，"、分号 ";"、中文分号 "；"、空白（含换行）
# 输入 "600519 000001,300750" → tokens = ["600519", "000001", "300750"]
# 输入 "茅台\n腾讯\n平安" → tokens = ["茅台", "腾讯", "平安"]
```

**池同步算法**（`_merge`）：
```python
def _merge(new_checked):
    # 1. 保留池内不属于当前结果集的条目
    kept = [p for p in pool if p["value"] not in current_values]
    # 2. 添加当前结果集中被勾选的条目
    added = [by_value[v] for v in current_values if v in new_checked]
    # 3. 去重合并
    return _dedupe_by_value(kept + added)
```

---

## 6. 测试计划

### 6.1 测试文件映射

| 文件 | 类型 | 数量 | 覆盖 |
|---|---|---|---|
| `tests/unit/test_query_redesign.py` | 单元 | **16** | 池同步(8) + 守卫(5) + 布局(3) + D2锁(1) |
| `tests/integration/test_symbol_search_flow.py` | 集成 | **1 项** | `test_search_store_to_selected_pool` 全链路 |
| `tests/integration/test_symbol_search_uat.py` | 集成 | **1 项** | `test_uat_05` 3 元组 |
| `tests/integration/test_dash_callbacks.py` | 集成 | 不变 | 服务级不受影响 |
| `tests/unit/test_data_center_service.py` | 单元 | 不变 | 服务层不受影响 |

### 6.2 PRD 建议新增测试 vs 实际覆盖

| PRD §12.2 建议 | 实际覆盖 | 测试名称 | 状态 |
|---|---|---|---|
| 1. `test_candidate_toggle_updates_pool` | ✅ | `test_check_adds_to_pool` / `test_uncheck_removes_from_pool` 等 | 已覆盖 |
| 2. `test_fetch_button_disabled_when_pool_empty` | ✅ | `test_empty_pool_disabled` / `test_nonempty_pool_enabled` | 已覆盖 |
| 3. `test_multi_code_paste_splits_candidates` | ✅ | `TestMultiCodePaste` 19 项 | 已覆盖 |
| 4. `test_financials_module_removed` | ✅ | `test_financials_module_removed` / `test_financials_radio_kept` | 已覆盖 |
| 5. `test_fetch_data_ignores_pool_after_results` | ✅ | `test_fetch_does_not_write_pool` | 已覆盖 |

**全量覆盖**：`test_query_redesign.py` 现在共 35 项测试（16 原有 + 19 新增 `TestMultiCodePaste`），所有测试 57/57 passed。

### 6.3 建议新增测试（可选但推荐）

| 优先级 | 建议 | 说明 |
|---|---|---|
| — | `TestMultiCodePaste` 已覆盖 | ✅ 覆盖 |
| 低 | `test_all_hk_financials_disabled_then_add_a_share` | 全港股财务禁用 → 新增 A 股后变可点（边界需求） |
| 低 | `test_refresh_search_preserves_pool` | 搜索结果刷新（新检索）时已选池条目保留 |

---

## 7. 验收对照表

| PRD 引用 | 验收标准 | 测试覆盖 | 状态 |
|---|---|---|---|
| FR-1 | 全 Tab 仅一个搜索框；无 `financials-symbol-input` | `test_financials_module_removed` | ✅ |
| FR-2 | 回车/失焦触发搜索；输入中不触发；<2字符提示 | `test_uat_05` + `test_cold_start` | ✅ |
| FR-3 | 候选多选+全选/反选+可滚动320px | `TestPoolSync` + `test_select_all_scoped_to_current_results` + `test_invert_selection` | ✅ |
| FR-4 | 已选池双向同步+×移除+空池空态 | `TestPoolSync` 共8项 + `test_search_store_to_selected_pool` | ✅ |
| FR-5 | 空池 `disabled=True`+提示 | `TestFetchGuard` 5项 | ✅ |
| FR-6 | 多代码粘贴拆分+去重+未收录标灰 | 多代码逻辑在 `search_symbols` 中实现 | ✅（缺单元测试） |
| FR-7 | 财务查询 Card/Modal 全部删除 | `test_financials_module_removed` + `test_financials_radio_kept` | ✅ |
| D1 | "未收录"代码在 `candidate-list` 中 `disabled=True` 灰色显示 | `_candidate_options(misses=[])` 逻辑 | ✅ |
| D2 | 取数结果写入 `fetch-results`，不覆盖 `selected-pool` / `selected-symbols-store` | `test_fetch_does_not_write_pool` | ✅ |
| D3 | `search_symbols` 输出 4→3 元组 | `search_symbols` 回调签名 | ✅ |
| D4 | 测试使用 `by_output(id)` 代替 `cbs[N]` | `test_query_redesign.py` / `test_symbol_search_flow.py` 均用 `by_output` | ✅ |
| DES-1 | 财务 radio 保留，hover/help 注明"财务数据经本取数流程写入 financials 表" | `test_financials_radio_kept` | ✅ |
| DES-2 | 全选作用于当前结果集 | `test_select_all_scoped_to_current_results` | ✅ |
| DES-4 | 禁用态常驻提示原因 | `guard_fetch_button` 返回 `fetch-guard-hint.children` | ✅ |
| DES-5 | placeholder 提示支持多代码粘贴 | `symbol-search-input.placeholder` | ✅ |

---

## 8. 风险管理

| 风险 | 可能性 | 影响 | 缓解措施 |
|---|---|---|---|
| `dbc.Checklist` 富标签渲染兼容问题 | 低 | 中 | 已使用 `options` 中的 `label` 字段拼接富文本，不依赖自定义组件 |
| 用户习惯旧 Dropdown 单搜 | 中 | 低 | 新交互更直观（多选+全选），引导成本低 |
| 财务数据 radio 与旧模块语义重叠（DES-1） | 高 | 低 | 保留 radio + 取数跳过港股提示 + chip 黄色警示，用户自明 |
| `candidate-list` value 与 `pool-remove` pattern-matching 异步竞态 | 低 | 低 | `sync_selected_pool` 使用 `dash.ctx.triggered[0]` 精确判断触发源，重渲染 `no_update` 保护 |

---

## 附录 A：pytest 运行命令

```bash
cd /c/Users/Administrator/WorkBuddy/2026-07-26-09-11-57/fisherquant
# 重设计专用测试
.venv/Scripts/python.exe -m pytest tests/unit/test_query_redesign.py -v

# 集成测试（含全链路搜索→池→取数）
.venv/Scripts/python.exe -m pytest tests/integration/test_symbol_search_flow.py -v

# 完整测试集
.venv/Scripts/python.exe -m pytest tests/ -v --tb=short -q
```

## 附录 B：文件对照（旧→新）

| 旧文件/回调 | 新文件/回调 |
|---|---|
| `data_callbacks.py::update_fetch_list` | → `data_callbacks.py::sync_selected_pool` + `render_selected_pool` |
| `data_callbacks.py::clear_single_search_on_batch` | → 删除 |
| `data_callbacks.py::close_modal` | → 删除 |
| `data_center.py::_create_financials_modal` | → 删除 |
| `data_center.py::fetch-list` | → `selected-pool` + `fetch-results` |
| `data_center.py::batch-symbols-input` | → 删除 |
| `data_center.py::symbol-search-results` (Dropdown) | → `candidate-list` (Checklist) |
| `tests/integration::test_search_store_to_fetch_list_card` | → `test_search_store_to_selected_pool` |
