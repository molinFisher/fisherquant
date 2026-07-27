# 数据中心 · 数据查询功能重设计 PRD

| 项 | 内容 |
|---|---|
| 文档版本 | v1.1（含评审记录） |
| 作者 | 高级产品经理（AI 代理） |
| 日期 | 2026-07-27 |
| 状态 | 待评审 |
| 关联模块 | `fisher/dash_app/pages/data_center.py`（`tab-query`）、`fisher/dash_app/callbacks/data_callbacks.py` |
| 上游依赖 | `get_data_service().search_symbols / fetch_bars`（数据服务层不变） |

---

## 1. 背景与问题陈述

现有「数据查询」Tab（`tab-query`）承载了"标的搜索 → 获取数据 → 获取列表 → 财务数据查询"四块功能，经走查与代码核对，存在以下体验与结构问题，用户已逐条提出重设计诉求：

| 编号 | 用户原话 | 当前问题（代码事实） | 影响 |
|---|---|---|---|
| A1 | 标的搜索，取消下面重复的搜索框 | 右侧「财务数据查询」卡内还有 `financials-symbol-input` 搜索框，与左侧"标的搜索"完全重复；且 `query-financials-btn` **没有任何打开回调**（死按钮） | 用户困惑：两个搜索框该用哪个；模块形同虚设 |
| A2 | 标的搜索在失焦或输入回车后自动检索，并展示下面的待选框 | 当前 `symbol-search-input` 已 `debounce=True`（仅回车/失焦触发），但结果塞进 `dcc.Dropdown`（`symbol-search-results`），不是"待选框"；无法多选、无"全选/清空" | 每次只能单选一个标的，批量场景需切到另一个文本框，割裂 |
| A3 | "获取列表"为空时不能"开始获取数据" | `fetch-data-button` 始终可点；空场景仅在点击后才提示"请先选择或输入标的"，属于事后校验 | 误点、空跑、进度条无意义跳动 |
| A4 | 批量输入不需要录入框，重新设计与其他几个功能的交互 | `batch-symbols-input`（`dcc.Textarea`）是独立游离文本框，与"标的搜索""获取列表""开始获取数据"三块彼此割裂，靠两个回调互相清空 | 录入框≠候选，心智割裂；粘贴代码还需手动逗号/换行分隔 |
| A5 | 取消"财务数据查询"模块 | 该模块为死模块（见 A1）；财务数据仍可通过"获取数据"的「数据类型=财务数据」拉取 | 维护噪音、误导用户 |

**核心矛盾**：搜索、候选、已选、批量、财务查询是同一件事（"选哪些标的、取哪些数据"）的五段，却散落在 3 个 Card + 1 个 Modal + 2 个文本框里，缺少单一事实来源（Single Source of Truth）。

---

## 2. 目标与非目标

### 2.1 目标
- **建立"搜索 → 候选 → 已选池 → 获取"单一主线**，所有标的选取动作汇聚到一个可勾选的"待选框"与一个"已选标的池"。
- 消除重复与死模块（A1、A5）。
- 让"开始获取数据"在数据未就绪时**物理不可点**（A3）。
- 用"多选候选 + 搜索框多代码粘贴"替代独立批量文本框（A4）。
- 搜索在"回车/失焦"触发并在下方呈现可勾选待选框（A2）。

### 2.2 非目标（本次不做）
- 不改数据服务层接口（`search_symbols` / `fetch_bars` 签名不变）。
- 不改「已缓存数据 / 自动加载 / 高级功能」三个 Tab 的结构（仅"数据查询"Tab 重设计）。
- 不引入后端批量任务队列（前端 `background` 回调已覆盖）。
- 不做财务数据可视化（仅取消独立查询模块；"数据类型=财务数据"保留为取数口径）。

---

## 3. 用户角色
- **量化研究员**：日常按代码/名称搜索 A股/港股通标的，多选后批量拉取日/分钟线。
- **策略开发者**：已有一份标的清单（代码列表），希望快速粘贴并整体拉取。
- **新手用户**：靠名称/拼音模糊搜索，从待选框里挑。

---

## 4. 设计原则
1. **单一事实来源**：已选标的只存在于 `selected-symbols-store`，候选勾选、池渲染、按钮守卫全部读它。
2. **输入即搜索、失焦即定**：搜索框 `debounce=True`（回车/失焦触发），不增加"搜索"按钮。
3. **批量即多选**：取消独立录入框；批量 = 在待选框多选，或在搜索框粘贴多代码。
4. **防呆优先**：空池时"开始获取数据"禁用，而非事后报错。
5. **最小改动面**：组件 ID 尽量复用，删除项明确，不牵动服务层与既有单测。

---

## 5. 重设计后的信息架构（数据查询 Tab）

```
数据查询 Tab（tab-query）
├─ 左列（width=6）
│   ├─ Card「标的搜索」            ← 唯一搜索入口（A1/A2）
│   │   ├─ symbol-search-input   （debounce=True；支持多代码逗号/空格/换行粘贴）
│   │   ├─ search-status         （结果计数 + 市场分布 / 初始化中 / 未找到）
│   │   └─ candidate-list        【新增·待选框】多选候选列表 + 全选/清空工具条
│   └─ Card「获取数据」          （参数）
│       ├─ date-range-picker
│       ├─ data-type-radio       （日线 / 分钟线 / 财务数据 ← 保留为取数口径，见 §9）
│       ├─ minute-period-selector（仅分钟线时显示）
│       ├─ fetch-data-button     （空池时 disabled，A3）
│       └─ 进度条 + fetch-status
└─ 右列（width=6）
    └─ Card「已选标的池」         ← 原"获取列表"升级（A4）
        ├─ selected-pool         （可移除的标的 chips + 已选计数）
        └─ 空态："请先搜索并勾选标的"
   （「财务数据查询」Card 与 financials Modal 已删除，A5）
```

---

## 6. 功能需求（FR）

### FR-1 统一搜索入口，删除重复搜索框（对应 A1）
- **需求**：全 Tab 仅保留 `symbol-search-input` 一个搜索框；删除右列「财务数据查询」卡及其内部 `financials-symbol-input`。
- **验收**：
  - 页面上不存在第二个标的搜索输入框。
  - `query-financials-btn`、`financials-symbol-input`、`financials-modal`、`financials-modal-body`、`close-financials-modal`、`_create_financials_modal` 全部从代码中移除，应用正常启动、该 Tab 无报错。

### FR-2 搜索触发时机：失焦 / 回车即检索（对应 A2）
- **需求**：`symbol-search-input` 保持 `debounce=True`（值仅在回车或失焦时提交），提交即调用 `search_symbols` 检索；不新增"搜索"按钮。
- **验收**：
  - 输入中（未回车/未失焦）不触发检索、不发请求。
  - 回车或输入框失焦后，立即发起检索并刷新待选框与状态行。
  - 输入 < 2 字符：待选框清空，状态行提示"请输入至少 2 个字符"。
  - 字典初始化未完成时提示"标的列表初始化中，请稍候…"；无匹配提示"未找到匹配的标的，试试代码、名称或拼音"。

### FR-3 待选框：可勾选候选列表（对应 A2）
- **需求**：检索结果以"待选框"（`candidate-list`）呈现，替代原 `dcc.Dropdown`；支持多选、全选、清空。
- **验收**：
  - 每个候选行展示：☑ 勾选框 + 名称 + 代码 + 市场徽标（A股红 / 港股蓝）+ 拼音缩写。
  - 待选框可滚动（最大高度约 320px），结果多时不撑破布局。
  - 提供「全选」「清空」操作，作用于当前结果集。
  - 勾选态与"已选标的池"双向同步（见 FR-4）。

### FR-4 已选标的池（获取列表升级）（对应 A4）
- **需求**：原"获取列表"升级为"已选标的池"，由独立 `selected-symbols-store` 驱动；池内每个标的可单独移除（×）。
- **验收**：
  - 在待选框勾选候选 → 即时出现在右列"已选标的池"，并显示"已选 N 个"。
  - 池内标的点击 × → 从池中移除，且待选框对应勾选框取消勾选。
  - 未选任何标的：右列显示空态"请先搜索并勾选标的"，且"开始获取数据"按钮禁用（见 FR-5）。
  - 删除 `batch-symbols-input`（`dcc.Textarea`）及其配套回调 `clear_single_search_on_batch`。

### FR-5 开始获取数据按钮守卫（对应 A3）
- **需求**：`fetch-data-button` 在"已选标的池"为空时 `disabled=True`，非空时可点。
- **验收**：
  - 池为空：按钮置灰、不可点击、不触发 `fetch_data`。
  - 池非空（≥1）：按钮可点，点击走原有 `fetch_data` 流程（后台回调 + 进度）。
  - 移除前："点击后才提示请先选择标的"的事后校验分支可保留为兜底，但主路径应为禁用。

### FR-6 批量输入重设计：多选 + 多代码粘贴（对应 A4）
- **需求**：以"待选框多选"作为批量主路径；并支持在 `symbol-search-input` 粘贴多个代码（逗号/空格/换行分隔），系统自动拆分并分别匹配，将匹配到的标的作为候选列出，用户再统一勾选加入池。
- **验收**：
  - 搜索框粘贴 `600519 000001 300750`（或逗号/换行）并回车/失焦 → 待选框列出这 3 个（命中则显示名称，未命中显示原始代码并标"未收录"）。
  - 不再提供任何独立批量录入文本框。
  - 池内标的去重（同一代码只出现一次）。
- **设计取舍**：保留"粘贴多代码"入口而非完全禁用手动代码录入，是为兼容"已有一份代码清单"的研究员；但入口复用主搜索框，不再新增文本框，满足"A4 不需要录入框"。

### FR-7 取消"财务数据查询"模块（对应 A5）
- **需求**：删除「财务数据查询」Card、`_create_financials_modal` 及财务查询相关回调（`close_modal` 等）。
- **验收**：
  - 该 Tab 不再出现"财务数据查询"标题与输入框。
  - 财务数据取数能力通过「获取数据 → 数据类型=财务数据」保留，不丢失（决策见 §9）。
  - 无残留 `dcc.Modal(id="financials-modal")` 组件导致 Dash 布局告警。

---

## 7. 关键交互流程（用户旅程）

**单标的**：输入"茅台"→ 回车 → 待选框出现"贵州茅台 600519"→ 勾选 → 右列池出现该标的 → 设日期/类型 → 点"开始获取数据"。

**批量（多选）**：输入"银行"→ 回车 → 待选框列出多家银行 → 点「全选」→ 右列池出现全部 → 点"开始获取数据"一次性拉取。

**批量（粘贴代码）**：在搜索框粘贴 `600519,000001,300750` → 回车 → 待选框列出 3 个 → 勾选所需 → 入池 → 获取。

**防呆**：未勾选任何候选 → 右列空态 → "开始获取数据"置灰 → 无法误点。

---

## 8. 状态与数据模型（新增/调整 Store）

| Store | 类型 | 用途 |
|---|---|---|
| `search-results-store`（保留） | list[dict] | `search_symbols` 返回的匹配项（含 code/name/market/pinyin_abbr/value） |
| `selected-symbols-store`（**新增**） | list[str] | 已选标的池的标准代码列表（单一事实来源），驱动池渲染与按钮守卫 |
| `fetch-progress-status`（保留） | dict | 取数进度 |

---

## 9. 产品决策与开放问题

1. **「数据类型=财务数据」是否保留？**
   - 决策：**保留**。`fetch_data` 仍支持 `data_type="financials"`（经 `svc.fetch_bars` 拉财务数据）。取消的是"独立财务查询 UI 模块"，不是"财务数据取数能力"。避免功能回退。
   - 待确认：若产品方认为"财务数据"作为数据类型也与模块语义重复，可一并移出 `data-type-radio`（仅留 日线/分钟线）。需产品负责人拍板。

2. **多选待选框的实现形态**：PRD 不锁死组件，工程可用 `dbc.Checklist`（自定义富标签）或 `dash_table.DataTable`（行多选）。建议 `dbc.Checklist` 以最小改动复用现有 `search_symbols` 输出结构。

3. **多代码粘贴的"未收录"标的是否可入池？**
   - 建议：未收录代码仍可入池（取数时由服务层报错并在 `fetch-status` 列出），降低用户负担；但默认标灰提示。

---

## 10. 代码改动清单（实施指引，供研发）

| 对象 | 位置 | 处理 |
|---|---|---|
| `financials-symbol-input` | `data_center.py` L143-147 | 删除（A1/A5） |
| 「财务数据查询」Card | `data_center.py` L138-157 | 删除（A5） |
| `_create_financials_modal()` | `data_center.py` L261-272 | 删除（A5） |
| `query-financials-btn` / `financials-modal` / `financials-modal-body` / `close-financials-modal` | `data_center.py` | 删除（A5，且 open 回调本就缺失） |
| `symbol-search-input` | 保留 | `debounce=True` 已满足回车/失焦触发（A2）；增加多代码解析 |
| `dcc.Dropdown("symbol-search-results")` | 替换为 `candidate-list` | A2/A3 |
| `batch-symbols-input`（Textarea） | 删除 | A4 |
| `fetch-list`（获取列表） | **拆为两个容器**：`selected-pool`（已选标的池，仅由候选勾选/移除驱动）+ `fetch-results`（取数进度/结果，复用 `fetch-status` 或新增）。见下方冲突解决（D2） | A4 |
| `fetch-data-button` | 新增 `disabled` 守卫（同时受 `guard_fetch_button` 与 `fetch_data` 的 `running` 配置控制） | A3 |
| `selected-symbols-store`（新增 `dcc.Store`） | 新增 | A4 |
| 回调 `search_symbols` | 输出由 4 元组 `(options, value, status, store)` 改为 3 元组 `(candidate_children, status, store)`；**多代码拆分在回调内**：检测分隔符 → 逐 token 调服务 → 合并去重（服务层接口不变） | A2/A6 |
| 回调 `fetch_data` | `symbols` 来源改为 `selected-symbols-store`；移除 `batch-symbols-input` 解析；**结果写 `fetch-results`，不再写 `selected-pool`**（避免覆盖已选列表） | A4 |
| 回调 `update_fetch_list` | 删除（其"选中回填富卡片"职责由 `on_candidate_toggle` + `selected-pool` 渲染取代） | A4 |
| 回调 `clear_single_search_on_batch` | 删除（依赖已删文本框） | A4 |
| 回调 `close_modal`（financials） | 删除 | A5 |
| 回调 `toggle_minute_period` | 保留 | — |
| **新增** `on_candidate_toggle` | 候选勾选/取消 → 写 `selected-symbols-store` 并渲染 `selected-pool` | A3/A4 |
| **新增** `guard_fetch_button` | 池空 → `fetch-data-button.disabled=True` | A3 |

> **冲突解决（评审 D2）**：现 `fetch_data` 与 `update_fetch_list` 都写 `Output("fetch-list","children")`（`update_fetch_list` 用 `allow_duplicate`）。重设计后 `selected-pool` 由候选勾选驱动，若 `fetch_data` 仍写同一容器，点击"开始获取数据"会覆盖已选列表。故必须将"已选列表"与"取数结果"拆为两个容器，`fetch_data` 仅写 `fetch-results`。
>
> **测试索引脆弱（评审 D4）**：现有集成测试用 `cbs[0]`/`cbs[2]` 依赖回调注册顺序；本次会新增 `on_candidate_toggle`/`guard_fetch_button`、删除 `clear_single_search_on_batch`/财务 `close_modal`，顺序必变。研发改动后须同步重排测试索引，或（推荐）给 `capture_dash_callbacks` 增加"按 Output 组件 id 查找回调"的辅助，消除顺序依赖。
>
> 服务层 `search_symbols` / `fetch_bars` 与「已缓存数据 / 自动加载」Tab 的既有修复（轮询不重建表格）**不受影响**。

---

## 11. 边界与异常

- 搜索 < 2 字符 / 字典初始化中 / 无结果：待选框清空或显对应状态，池不受影响。
- 待选框滚动：结果集大时限制最大高度并滚动，不撑破卡片。
- 池去重：重复勾选同一代码只保留一份。
- 取数进行中（`fetch_data` `running` 状态）：按钮显示"获取中…"并禁用，与空池禁用互不冲突。
- 网络/服务异常：`search_symbols` 失败显示"搜索服务暂时不可用，请稍后重试"，不影响池与按钮守卫逻辑。

---

## 12. 验收与测试

### 12.1 功能验收（手工）
- [ ] 全 Tab 仅一个搜索框；无"财务数据查询"卡片/弹窗。
- [ ] 输入回车/失焦即出候选；输入中不出。
- [ ] 候选可多选、全选、清空；勾选即入右列池。
- [ ] 池空时"开始获取数据"置灰不可点；入池后变可点。
- [ ] 搜索框粘贴多代码 → 待选框列出多个 → 统一入池。
- [ ] 池内 × 可移除，且待选框勾选同步取消。

### 12.2 测试影响与补测（评审修订 v1.1，修正原误判）
- **原 v1.0 结论"tests 对这些组件 ID 无任何引用、不破坏 73 用例"是错误的**（当时 grep 范围过窄）。经全量 `grep tests/` 复核，实际牵连如下：
  - **会断裂（UI 回调级，必须重写）**：
    - `tests/integration/test_symbol_search_uat.py::test_uat_05_no_match_guidance`：第 114 行 `opts, val, status, store = search_cb("minimax")` 依赖 `search_symbols` **4 元组**输出 → 重设计变 3 元组后解包失败。
    - `tests/integration/test_symbol_search_flow.py::test_search_store_to_fetch_list_card`：第 112 行 4 元组解包 + 第 110/117 行用 `cbs[2]`（即 `update_fetch_list`，重设计后删除/改造）→ 断裂。
  - **不受影响（仅测服务层）**：`tests/integration/test_dash_callbacks.py::TestSearchFetchFlow`、`tests/unit/test_data_center_service.py`（含 `test_fetch_financials`，测的是 `fetch_bars(..., data_type="financials")` 服务层，删 UI 模块不影响）、`tests/unit/test_regression_fixes.py` 均直接调服务层 `search_symbols/fetch_bars`，UI 重设计不动服务层，故安全。
  - **财务模块删除测试安全**：financials 在测试中仅出现在服务层 `test_fetch_financials`；`conftest.py`/`test_dash_callbacks.py` 实际无 `financials-modal` 等 UI 引用（早期命中为 `__pycache__` 误判），删除 UI 模块不破测试。
- **必须重写**（与研发同步）：上述 2 个 UI 回调测试改为 3 元组 + 新的池回调（`on_candidate_toggle` / `selected-pool` 渲染）；并改用"按 Output id 查找回调"替代 `cbs[N]` 下标。
- **建议新增**：
  1. `test_candidate_toggle_updates_pool`：勾选候选 → `selected-symbols-store` 含该代码。
  2. `test_fetch_button_disabled_when_pool_empty`：池空 → `disabled=True`；入池 → `False`。
  3. `test_multi_code_paste_splits_candidates`：搜索框多代码 → 待选框条数正确（验证 D1 回调内拆分）。
  4. `test_financials_module_removed`：布局不再含 `financials-modal` 组件。
  5. `test_fetch_data_ignores_pool_after_results`：取数结果写 `fetch-results`、不覆盖 `selected-pool`（锁住 D2 修复）。

---

## 13. 影响面与风险

- **正向**：删除死模块与重复框，代码量净减；交互主线清晰；防呆降低误操作。
- **风险**：`candidate-list` 多选组件若用 `dbc.Checklist`，富标签需自定义渲染；建议复用 `search_symbols` 现有 `matches` 结构（已含 name/code/market/pinyin_abbr），改动小。
- **回归**：仅"数据查询"Tab；服务层、缓存 Tab、自动加载 Tab 不受影响。

---

## 14. 里程碑建议

| 阶段 | 内容 | 估时 |
|---|---|---|
| P1 | 删除财务数据查询模块 + 重复搜索框（FR-1/FR-7） | 0.5d |
| P2 | 待选框替代 Dropdown + 搜索多代码（FR-2/FR-3/FR-6） | 1d |
| P3 | 已选标的池 + 按钮守卫 + fetch_data 改源（FR-4/FR-5） | 1d |
| P4 | 单测补充 + 手工验收 | 0.5d |

---

---

## 15. 评审记录（开发 / 设计 / 测试）

> 评审日期 2026-07-27。基于代码走查（`data_center.py` / `data_callbacks.py` / `data_center_service.py`）与现有测试（`tests/integration`、`tests/unit`）逐项核验。**结论：方案方向成立，但存在 2 处开发实现空洞、1 处组件职责冲突、2 个集成测试将断裂，须修订 PRD 后方可进入研发。** 对应修订已并入 §6/§10/§12.2。

### 15.1 开发视角

| 编号 | 发现 | 严重度 | 证据 | 修订动作 |
|---|---|---|---|---|
| D1 | 多代码粘贴缺少实现层 | 高 | `DataCenterService.search_symbols(self, query: str)` 仅接受单字符串、内部 `normalize_query`+单次 `LIKE`；传 `"600519,000001"` 整体匹配命中 0 条。PRD FR-6 写"系统自动拆分"却未指定在哪层 | 拆分在 `search_symbols` **回调内**：检测分隔符→逐 token 调服务→合并去重；服务层接口不变（已写入 §6/§10） |
| D2 | `fetch-list` 双写冲突 | 高 | `fetch_data` 与 `update_fetch_list` 都写 `Output("fetch-list","children")`（`allow_duplicate`）。若把它当"已选池"由候选驱动，取数结果会覆盖已选列表 | 拆为 `selected-pool`（仅候选驱动）+ `fetch-results`（取数结果）；`fetch_data` 不写池（已写入 §10） |
| D3 | `search_symbols` 输出元数变化 | 中 | 现返回 4 元组 `(options,value,status,store)`；重设计改 3 元组 `(candidate_children,status,store)`，按 4 元组解包的调用方必断 | 同步改回调与测试；§10 标注 4→3 |
| D4 | 回调注册顺序致测试索引脆弱 | 中 | 测试用 `cbs[0]`/`cbs[2]` 依赖顺序；本次增 `on_candidate_toggle`/`guard_fetch_button`、删 `clear_single_search_on_batch`/财务 `close_modal`，顺序必变 | 测试改用"按 Output id 查找"；建议 `capture_dash_callbacks` 增 `by_output(id)`（写入 §10/§12.2） |
| D5 | 财务数据取数仅支持 A 股 | 低 | `fetch_bars` 的 `financials` 分支用 `ak.stock_financial_abstract(symbol=code)`（code 已去后缀），港股无效。保留 radio 可接受但需提示 | UI 对港股标的禁用/提示"财务数据仅支持 A 股"（写入 §9 待确认项） |

### 15.2 设计视角

| 编号 | 发现 | 严重度 | 建议 |
|---|---|---|---|
| DES-1 | 财务数据 radio 与已删模块语义重叠 | 中 | 删模块后"数据类型=财务数据"仍在，用户易困惑"财务数据去哪查"。建议保留并在 hover/help 注明"财务数据经本取数流程写入 financials 表" |
| DES-2 | 「全选/清空」语义歧义 | 中 | "全选"应作用于**当前待选框结果集**（受 200 上限约束），非全市场；"清空"指清已选池。建议待选框工具条用「全选/反选」，池区用「清空已选」 |
| DES-3 | 候选区与已选区信息冗余 | 低 | 已选标的在候选列表（打勾）与池（chip）双处出现。建议选中候选在列表中置灰/降对比，强化"已加入"态 |
| DES-4 | 禁用态需给原因 | 低 | 空池禁用时仅置灰不够，应在按钮下方常驻提示"请先在左侧勾选标的"，与 FR-3 状态行呼应 |
| DES-5 | 混合输入模式边界 | 低 | 搜索框同时承载"模糊名/拼音"与"多代码粘贴"，以是否含分隔符判定。中文名一般无空格，冲突概率低；建议 placeholder 明确"搜索名称/代码，或粘贴多代码" |

### 15.3 测试视角

| 编号 | 发现 | 严重度 | 动作 |
|---|---|---|---|
| T1 | 现有 UI 回调级测试将断裂（**修正原 PRD 误判**） | 高 | `test_uat_05`（4 元组解包）、`test_search_store_to_fetch_list_card`（4 元组 + `cbs[2]`）须重写；服务级测试（`TestSearchFetchFlow`/`test_data_center_service`/`test_regression_fixes`）不受影响 |
| T2 | 须新增测试锁住新行为 | 中 | 见 §12.2 新增 5 项，其中 `test_fetch_data_ignores_pool_after_results` 锁住 D2、`test_multi_code_paste_splits_candidates` 锁住 D1 |
| T3 | 测试基建改进 | 低 | `capture_dash_callbacks` 增"按 Output id 查找"，消除 `cbs[N]` 顺序脆弱（呼应 D4） |

### 15.4 评审结论与必改项
- **方向 ✅**：单一主线、防呆、删死模块均成立，无需推翻。
- **进入研发前必须完成**：① FR-6 明确多代码在回调层拆分（D1，已改）；② FR-4/§10 明确 `fetch-list` 拆为 `selected-pool`+`fetch-results`（D2，已改）；③ §10 标注 `search_symbols` 输出 4→3（D3，已改）；④ §12.2 更正测试影响并列出 2 个必改测试 + 5 个新增项（T1/T2，已改）；⑤ §9 补充财务 radio 标注与全选/清空语义（DES-1/2，建议产品拍板）。
- **风险等级：中**。改动集中在"数据查询"Tab 与 2 个集成测试，不触服务层/缓存/自动加载。

### 15.5 修订历史
- v1.0 (2026-07-27) 初稿：五大诉求映射、信息架构、FR-1~7、代码改动清单、里程碑。
- v1.1 (2026-07-27) 评审修订：新增 §15 评审记录；据此修订 §6（多代码拆分层）、§10（`fetch-list` 冲突解决 + 输出 4→3 + 测试索引脆弱）、§12.2（修正"测试无牵连"误判，列出 2 个必改测试 + 5 个新增项）；§9 待确认项补充财务 radio 标注。

---

> 附录：重设计后线框图见本对话内的可视化组件（Mockup）。
