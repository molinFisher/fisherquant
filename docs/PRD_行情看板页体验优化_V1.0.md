# PRD 行情看板页体验优化 V1.0

> 版本：v1.1（开发/设计/测试三视角评审后更新）
> 提出视角：产品经理（PM）
> 评审视角：开发(D) / 设计(DES) / 测试(T)——评审结论见 §9
> 关联页面：`/market-watch`（行情看板）、`/data-center`（数据查询/目录）
> 关联代码：
> - `fisher/dash_app/pages/quote_board.py`
> - `fisher/dash_app/callbacks/quote_callbacks.py`（`_build_minute_chart` / `render_minute_chart` / `render_daily_chart` / `batch_goto_cache` / 行内 `goto_cache` 链接）
> - `fisher/dash_app/pages/data_center.py`、`fisher/dash_app/callbacks/data_callbacks.py`（`selected-symbols-store` 待缓存池）

---

## 0. 背景与目标

行情看板是用户日常盯盘与补数据的核心入口。本期收集到 3 个体验痛点，均属**高频操作路径上的"卡点"**，修复收益高、改动范围可控：

1. 1 分钟 K 线在午休（11:30–13:00）出现明显空白带，视觉割裂、不专业。
2. 从看板"去缓存 / 批量去缓存补齐"跳转到数据查询后，**没有把标的带入"待缓存标的"池**，用户必须重新搜索勾选，断了"看板发现缺口 → 一键去补齐"的心智流。
3. 日 K 线时间范围只有 4 档固定周期（1月/3月/6月/1年，实为"最近 N 个交易日"），不支持自定义起止日期，无法满足"看某段特定行情"的需求。

**目标**：让分钟线更干净、补齐路径零摩擦、日线时间维度自由。

---

## 1. 现状问题陈述（Problem Statements）

### S1 — 分钟线午休时间展示不美观
- **现象**：1m/5m 等分钟 K 线在交易日 11:30–13:00 午休区间，图表 X 轴留下一段无数据的空白（candlestick 仍按连续时间排布），观感像"断图"。
- **根因**：`_build_minute_chart`（quote_callbacks.py L882）使用 `go.Candlestick` + 连续 `datetime` 轴，未设置 `rangebreaks` 隐藏每日午休。日线因按"交易日"聚合不存在此问题。
- **影响**：用户第一眼觉得图表"坏了/不专业"，尤其 1m 线午休空白占比高。

### S2 — "去缓存 / 批量去缓存补齐"未带入待缓存标的
- **现象**：在看板点击某行"去缓存"或顶部"批量去缓存补齐"后，跳转到数据查询页，但"待缓存标的"池为空，需重新搜索勾选才能取数。
- **根因（两段断点）**：
  1. 行内 `goto_cache` 链接为 `/data-center?tab=tab-cached&focus={sym}`（quote_callbacks.py L256/L269），而数据查询页 `active_tab` 写死为 `tab-query`（data_center.py L24），`?tab=` 参数**完全未被消费**；
  2. 数据查询页**没有消费 `focus`/`symbols` 去预填 `selected-symbols-store`**（待缓存池）的逻辑（data_callbacks.py 中无 focus/symbols 消费回调）；
  3. "批量去缓存补齐"（`batch_goto_cache`，quote_callbacks.py L536）只跳 `/data-center?tab=tab-cached`，**连标的列表都没传**。
- **影响**：补齐数据的核心链路被"重新选标的"打断，看板健康度提示形同虚设。

### S3 — 日线仅支持固定时间周期
- **现象**：日 K 线时间范围选择器（quote_board.py L93 `qb-daily-range`）只有 1月/3月/6月/1年 4 档，且本质是"最近 N 个交易日"（值 20/60/120/250），无法指定如"2024-01-01 ~ 2024-03-31"的自定义区间。
- **根因**：`render_daily_chart`（quote_callbacks.py L733）把 `qb-daily-range` 的 value 当作 `limit` 传给 `_fetch_daily_bars(ticker, limit=...)`，按条数截断，无起止日期入参。
- **影响**：用户想回看特定事件窗口的日线时被迫拉满 1 年再手动缩放，低效。

---

## 2. 用户场景（User Stories）

- **US1（盯盘）**：作为日内交易者，我希望 1 分钟 K 线在午休处自然断开、不显示空白，以便专注交易时段的价格结构。
- **US2（补数据）**：作为看板用户，我在健康度区看到"分钟覆盖 8/10"，点击"批量去缓存补齐"后，这 10 个标的应**自动进入待缓存池并停在"获取数据"页**，我只需点"开始获取数据"即可。
- **US3（补数据-单标）**：作为看板用户，我对某行点"去缓存"，希望该标的自动进入待缓存池、停在获取数据页，且默认数据口径与看板一致（如日线/分钟线）。
- **US4（回看）**：作为研究用户，我希望日线可切到"自定义"，选起止日期后只加载该区间日 K 线，便于对照特定公告/行情窗口。

---

## 3. 功能需求（Functional Requirements，EARS 式）

### FR-1 分钟线隐藏午休空白（对应 S1，P0）
- **系统应（Ubiquitous）**：当渲染分钟 K 线（`_build_minute_chart`）时，对 X 轴设置 `rangebreaks=[dict(bounds=["11:30", "13:00"])]`，隐藏每日午休空白带；不破坏 rangeslider 与 tooltip。
- **验收**：1m K 线在 11:30 与 13:00 之间无空白带，交易时段连续；多日数据午休均被正确隐藏；切换周期（1/5/15/30/60m）均生效。

### FR-2 去缓存 / 批量补齐带入待缓存池（对应 S2，P0）
- **系统应（Ubiquitous）**：数据查询页加载时，若 URL 携带 `?focus=<ticker>` 或 `?symbols=<t1,t2,...>`，应将对应标的**预填入 `selected-symbols-store`（待缓存池）**，并将激活 Tab 切到"获取数据"（`tab-query`），使用户落点即可点"开始获取数据"。
- **当（Event-driven）** 用户从看板点击行内"去缓存"：链接应携带该标的（如 `?focus={sym}`），且**目标 Tab 为获取数据页**（而非已缓存页），落入后即预填该标的。
- **当（Event-driven）** 用户点击"批量去缓存补齐"：链接应携带当前看板全部标的（如 `?symbols={逗号分隔}`，上限取 MAX_FETCH_SYMBOLS=20），落入后预填整池。
- **系统应（Ubiquitous）**：预填时若 URL 携带 `?data_type=` 提示本次补齐的默认数据类型（默认 `daily`），并在搜索区/UI 给出"已从看板带入 N 个标的"的可读提示。
- **验收**：
  - 单行"去缓存" → 数据查询页"获取数据"Tab 激活，待缓存池含该标的，无需重新搜索；
  - "批量去缓存补齐" → 待缓存池含看板全部标的（≤20），"获取数据"Tab 激活；
  - 消费后清除 `focus`/`symbols` 参数（避免刷新重复预填，参照既有 `_strip_focus` 思路）。

### FR-3 日线支持自定义时间段（对应 S3，P1）
- **系统应（Ubiquitous）**：在日线时间范围选择器（`qb-daily-range`）增加"自定义"选项；选中后展示 `dcc.DatePickerRange`（起止日期）。
- **当（Event-driven）** 用户选择"自定义"并设置起止日期：`render_daily_chart` 按 `[start, end]` 区间加载日线，而非"最近 N 条"。
- **Where（Optional）** 用户选择固定档（1月/3月/6月/1年）：维持现状的"最近 N 个交易日"行为，不回归。
- **系统应（Ubiquitous）**：自定义区间为空或仅选一边时，回退到默认档（6月/120 条），并给出轻量提示。
- **验收**：选"自定义"+"2024-01-01~2024-03-31"后，日 K 线仅显示该区间；切回固定档行为不变；自定义区间下均线/成交量/复权口径与现有逻辑一致。

---

## 4. 信息架构与交互（IA）

### 4.1 分钟线（不变结构，仅渲染层）
```
行情看板 → 分钟线 Tab → qb-minute-chart
   └─ _build_minute_chart：+ rangebreaks 午休隐藏（FR-1）
```

### 4.2 去缓存链路（修复前后对比）
```
【修复前】 看板"去缓存" ──url(?tab=tab-cached&focus=sym)──▶ 数据查询(active_tab 写死 tab-query)
                                                    ✗ focus 未消费 → 待缓存池为空
【修复后】 看板"去缓存" ──url(?focus=sym&data_type=daily)──▶ 数据查询(tab-query 激活)
                                                    ✓ 消费 focus → 预填 selected-symbols-store
```
```
【修复前】 看板"批量去缓存补齐" ──url(?tab=tab-cached)──▶ 数据查询（无标的）
【修复后】 看板"批量去缓存补齐" ──url(?symbols=t1,t2,…)──▶ 数据查询(tab-query 激活)
                                                    ✓ 消费 symbols → 预填整池
```

### 4.3 日线时间范围（新增自定义）
```
行情看板 → 日线 Tab → qb-daily-range
   ├─ 1月(20) / 3月(60) / 6月(120) / 1年(250)   # 维持
   └─ 自定义 ──▶ dcc.DatePickerRange(start, end) ──▶ render_daily_chart(start,end)
```

---

## 5. 代码改动清单（Code Change List）

| 文件 | 位置 | 改动 |
| --- | --- | --- |
| `callbacks/quote_callbacks.py` | `_build_minute_chart` (L882) | 分钟图 `fig.update_xaxes(rangebreaks=[dict(bounds=["11:30","13:00"])])`；建议同步 `hovermode="x unified"`（FR-1，见 DES-3） |
| `callbacks/quote_callbacks.py` | 行内 `goto_cache` 链接 (L256/L269) | 链接改为 `/data-center?tab=tab-query&focus={sym}&data_type=...`（落到**获取数据**页）；文案建议改为"去补齐"（DES-1）（FR-2） |
| `callbacks/quote_callbacks.py` | `batch_goto_cache` (L536) | 读取 `_load_watchlist()` 取全部标的，跳转 `/data-center?tab=tab-query&symbols={逗号分隔,≤20}&data_type=daily`（FR-2，见 D-7） |
| `callbacks/quote_callbacks.py` | `_fetch_daily_bars` (L826) | 新增可选 `start`/`end`：给定区间时改 `WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date ASC`（不再 LIMIT）；否则维持 `DESC LIMIT`（FR-3） |
| `callbacks/quote_callbacks.py` | `render_daily_chart` (L728) | 新增 Input `qb-daily-custom-range` 的 `start_date`/`end_date`；`if daily_range=="custom":` 走 start/end，否则 `limit=int(daily_range)`（**必须重构 `daily_range or 120`，否则 "custom" 字符串会被当 limit**，见 D-8）（FR-3） |
| `pages/quote_board.py` | `qb-daily-range` (L93) | 选项追加 `{"label":"自定义","value":"custom"}`；同 Tab 下新增 `dcc.DatePickerRange(id="qb-daily-custom-range")`（默认隐藏，选中"自定义"时显示，见 DES-4）（FR-3） |
| `callbacks/data_callbacks.py` | **新增** `consume_cache_intent` | 消费 `?tab=tab-query`/裸 `?focus=`/`?symbols=` → 预填 `selected-symbols-store`（`[{"value":t,"label":t}]` 同构，见 D-3）+ 切 `active_tab="tab-query"` + 清除参数（复用 `_strip_focus` 思路，扩展剥 `symbols`/`data_type`，见 D-5）+ UI 提示"已从看板带入 N 个标的"（FR-2，见 DES-2） |
| `callbacks/data_cache_callbacks.py` | 既有 `consume_focus` (L233) | **不改动**（仅处理 `tab=tab-cached`→已缓存页筛选，与新增 `consume_cache_intent` 互补，见 D-1）；二者同写 `url.search`/`data-center-tabs.active_tab` → 新回调须 `allow_duplicate=True`（D-1/D-4） |

> 评审修正（v1.1）：
> - **不再凭空新建、也不破坏既有 `consume_focus`**：FR-2 的"预填待缓存池"由新增的 `consume_cache_intent`（处理 `tab-query`）承担；既有 `consume_focus`（处理 `tab-cached`）保持不变，二者按 `tab` 值分流、互不冲突。
> - **无需新增 `dcc.Location`**：应用级 `dcc.Location(id="url", refresh=False)` 已在 `layout.py` L155 注册，两个消费回调直接复用 `Input("url","search")`。
> - `selected-symbols-store` 当前唯一写入方 `sync_selected_pool`（data_callbacks.py L136，**无 allow_duplicate**），新回调写它必须 `allow_duplicate=True`，且预填数组须与其同构（`[{"value":ticker,"label":name}]`）。

---

## 6. 验收标准（Acceptance）

- **A1（FR-1）**：1m 分钟线午休无空白带；5/15/30/60m 同样无午休空白；rangeslider 仍可拖动。
- **A2（FR-2）**：单行"去缓存"与"批量去缓存补齐"落点后，待缓存池分别含该标的 / 含看板全部标的（≤20），且激活"获取数据"Tab；刷新不重复预填。
- **A3（FR-3）**：日线"自定义"可选起止日期并仅加载该区间；固定档行为不变；边界（空区间）回退默认并提示。
- **A4（非回归）**：现有日线/分钟线渲染、看板健康度、已缓存数据页、取数流程均不受影响；单测通过。

---

## 7. 风险与开放问题（Risks / Open Questions）

- **R1（FR-2 URL 长度）**：`?symbols=` 逗号拼接看板全部标的，看板上限 ≤ MAX_FETCH_SYMBOLS=20，URL 很短，风险低；若未来放开看板上限需改共享 `dcc.Store` 方案。
- **R2（FR-2 口径一致性）**：`data_type` 默认 `daily`（最常用、与看板主视图一致）。**已决策**：单行"去补齐"与"批量补齐"均默认 `daily`；若后续要"按缺失最多的类型智能推荐"作为增强，不阻塞本期。
- **R3（FR-1 跨午夜/多日）**：`rangebreaks` 的 `bounds=["11:30","13:00"]` 对多日数据每日生效；本期仅 A 股/港股，直接隐藏午休即可。后续接入期货/虚拟币（无午休）再按市场类型开关。
- **R4（FR-3 数据完整性）**：自定义区间若超出已缓存范围，缺失部分不自动补取（与现有"仅展示已缓存"一致）；如需"区间不足则提示去取数"可作为增强，本期不强制。
- **R5（FR-3 跨日跳空）**：分钟线除午休外，上一交易日 15:00 与下一交易日 9:30 之间仍有隔夜跳空；本期 `rangebreaks` 仅处理午休（与需求一致），隔夜跳空保持原样（可选未来增强）。
- **R6（D-8 类型混合）**：`qb-daily-range` 选项由纯 int（20/60/120/250）混入字符串 `"custom"`，回调里 `daily_range or 120` 对 `"custom"` 会误判为有效 limit，**必须显式 `if daily_range == "custom"` 分支**，否则生产 bug。

---

## 8. 评审结论（开发 / 设计 / 测试三视角，v1.1 新增）

### 8.1 开发视角（D）

- **D-1（重要）既有 `consume_focus` 已存在，勿重复造轮子**：`data_cache_callbacks.py` L233 的 `consume_focus` 已消费 `?focus=`，但只用于**已缓存页筛选**（`cache-filter-input` + 激活 `tab-cached`），**不是**预填 `selected-symbols-store`。FR-2 应**互补新增** `consume_cache_intent` 处理 `tab=tab-query`/裸 `focus`/`symbols`，二者按 `tab` 分流、互不冲突。
- **D-2（重要）`batch_goto_cache` 当前不读标的**：L536 函数体无任何标的来源，只返回 `?tab=tab-cached`。须先 `_load_watchlist()` 取全部自选（同文件 `prune_watchlist_on_load` 已用该 helper），拼成 `symbols=` 传参；上限 `min(len(wl), 20)`。
- **D-3（重要）预填数据形状必须同构**：`selected-symbols-store` 元素是 `{"value":ticker,"label":name}`（见 `sync_selected_pool`/`_candidate_options`）。预填须构造 `[{"value":t,"label":t} for t in tickers]`（label 可改从 `symbol_dict` 解析中文名，但 `value` 必填），否则 `fetch_data` 读 `item["value"]` 会出错。
- **D-4（重要）`allow_duplicate` 必加**：新 `consume_cache_intent` 写三个输出——`selected-symbols-store`（`sync_selected_pool` L136 已写且无 allow_duplicate）、`data-center-tabs.active_tab`、`url.search`（既有 `consume_focus` 已写且无 allow_duplicate）。新回调这三个输出**全部**需 `allow_duplicate=True`。
- **D-5（低）参数清除复用既有工具**：剥参逻辑复用 `quote_callbacks._strip_focus`（L919），扩展其同时剥除 `symbols`/`data_type`/`tab`，避免刷新重复预填；不要新写解析。
- **D-6（中）`url.search` 双写顺序**：`consume_focus` 与 `consume_cache_intent` 同触发于 `url.search` 变化；同一变更下两回调都会跑，`consume_focus` 在 `tab!=tab-cached` 时 `no_update`，`consume_cache_intent` 在 `tab!=tab-query` 且无裸 `focus`/`symbols` 时 `no_update`。需保证"清参"只由命中的那个回调返回，避免两个都回写 search 造成抖动。建议：`consume_cache_intent` 命中时回写已剥参的 search；`consume_focus` 保持现状。
- **D-7（低）"补齐"范围可更聪明**：v1 直接传全部自选（fetch 幂等、已限速），但若只传"健康度不达标"的标的体验更佳。本期不做，留作增强。
- **D-8（重要）`daily_range` 类型混合**：见 R6，`render_daily_chart` 必须显式分支 `if daily_range == "custom"`。

### 8.2 设计视角（DES）

- **DES-1（重要）命名与心智对齐**："去缓存"字面是"去看已缓存"，但实际要落到"获取数据"页并预填**待缓存池**，语义错位。建议行内链接文案改为「**去补齐**」或「**去获取**」；批量按钮保留"批量去缓存补齐"亦可，但落点同为获取数据页。已缓存内容用户本就可从「已缓存数据」Tab 直接查看。
- **DES-2（中）带入后需显式反馈**：预填成功后应在获取数据页给出可读提示，如顶部 `alert`「已从看板带入 N 个标的，可直接点击『开始获取数据』」，降低"为什么池子里多了东西"的困惑（复用 `search-status` 或新增 `data-center-intent-banner`）。
- **DES-3（中，FR-1 一致性）**：分钟图当前未设 `hovermode`，日图是 `x unified`。建议 `_build_minute_chart` 加 `rangebreaks` 同时设 `hovermode="x unified"`，午休隐藏后 hover 体验与日图一致。
- **DES-4（低，FR-3 渐进展示）**：`dcc.DatePickerRange` 默认隐藏，仅当选中"自定义"时显示（用 `hidden` 属性或 `style` 控制），避免常驻占用空间；选中其它固定档时隐藏并清空其值。
- **DES-5（低）自定义区间边界提示**：区间为空/只选一边时回退默认（120/6月）并在 DatePickerRange 旁给轻量 `text-muted` 提示，与 FR-3 验收一致。

### 8.3 测试视角（T）

- **T-1（重要，FR-1）**：`rangebreaks` 是渲染属性。单测直接调 `_build_minute_chart(symbol, period, bars)` 构造 figure，断言 `fig.layout.xaxis.rangebreaks` 含 `dict(bounds=["11:30","13:00"])`（注意它不是 subplots，`update_xaxes` 落到 `layout.xaxis`）。可用系统 Python（已装 plotly）。
- **T-2（重要，FR-2）**：用 `tests/helpers/dash_harness.capture_dash_callbacks` + monkeypatch `url.search`/`pathname`，定位 `consume_cache_intent` 按 `by_output("selected-symbols-store","data")` 取得；断言其返回值（a）形状为 `[{"value":..,"label":..}]`、（b）`active_tab=="tab-query"`、（c）回写的 `url.search` 已剥除 `focus`/`symbols`。注意既有 `consume_focus` 同 Input，须确认 harness 能区分两回调。
- **T-3（中，FR-2 链接生成）**：单测 `_quote_row`/`_empty_row` 的 `goto_cache` 字段含 `tab=tab-query` 与正确 symbol；单测 `batch_goto_cache`（需注入 watchlist）返回的 pathname/search 含 `symbols=` 且条数 ≤20。
- **T-4（中，FR-3）**：`_fetch_daily_bars(ticker, start, end)` 用内存库断言只返回 `[start,end]` 内行；`render_daily_chart(chart_symbol, adj_mode, "custom", start, end)` 走区间分支而非 limit（可用 monkeypatch 验证调用签名）。
- **T-5（低，非回归）**：既有日图周末 `rangebreaks`（`row=1`）、`consume_focus`（cached-tab）用例须仍通过；新增 FR 不破坏现有图表/健康度/取数流程。

### 8.4 评审结论与必改项

- **方向 ✅**：三个痛点根因清晰、方案改动集中（渲染层 + 1 个互补回调 + 1 个选择器），风险低。
- **进入研发前必须完成**：① 复用/互补 `consume_focus`，新增 `consume_cache_intent` 并给三个输出加 `allow_duplicate`（D-1/D-4）；② 预填数组同构 `{"value","label"}`（D-3）；③ `batch_goto_cache` 读 `_load_watchlist()` 拼 `symbols`（D-2）；④ `render_daily_chart` 显式 `if daily_range=="custom"` 分支（D-8/R6）；⑤ 行内文案改「去补齐」、带入后显式提示（DES-1/DES-2）。
- **风险等级：低-中**。改动不触接口签名与既有数据表；仅新增 1 回调 + 1 选择器 + 渲染属性。

---

## 9. 实施里程碑（Milestones）

| 里程碑 | 内容 | 估时 |
| --- | --- | --- |
| P1 | FR-1 分钟线午休隐藏（rangebreaks + hovermode 统一） | 0.5d |
| P2 | FR-2 去补齐带入待缓存池（链接改造 + 新增 `consume_cache_intent` 互补既有 `consume_focus` + Tab 驱动 + 提示） | 1d |
| P3 | FR-3 日线自定义时间段（选择器 + DatePickerRange + 取数 BETWEEN 扩展） | 0.5d |
| P4 | 单测补充（T-1~T-5）+ 手工验收 | 0.5d |

---

## 10. 评审记录与决策（已据 §8 结论落实）

详细评审意见见 §8（开发 D-1~D-8 / 设计 DES-1~DES-5 / 测试 T-1~T-5）。本节仅记录已拍板的决策：

1. **FR-2 落点 = 获取数据页（tab-query）+ 预填待缓存池**；既有 `consume_focus`（cached 页筛选）保留不破坏，二者按 `tab` 分流。
2. **行内链接文案改为「去补齐」**（DES-1），落点与文案对齐心智；批量按钮同为 tab-query 预填。
3. **默认 `data_type=daily`**（R2 已决策）；带入后顶部显式提示「已从看板带入 N 个标的」（DES-2）。
4. **`selected-symbols-store` 预填须同构 `{"value":t,"label":t}`**，且新回调三输出加 `allow_duplicate=True`（D-3/D-4）。
5. **FR-3 须显式 `if daily_range=="custom"` 分支**，否则 "custom" 字符串误当 limit（D-8/R6）。

---

## 11. 修订历史

- v1.0 (2026-07-29) 初稿：基于看板 3 个痛点（分钟线午休空白 / 去缓存未带入标的 / 日线仅固定周期），给出 S1-S3、FR-1~3（EARS）、IA、代码改动清单、验收、风险与里程碑。
- v1.1 (2026-07-29) 开发/设计/测试三视角评审：① 修正 FR-2 方案——复用应用级 `dcc.Location`、互补既有 `consume_focus` 新增 `consume_cache_intent`（明确 allow_duplicate 与同构预填）；② 修正 `batch_goto_cache` 须读 watchlist 拼 symbols；③ 修正 FR-3 `daily_range` 类型混合须显式分支；④ 补充 DES「去补齐」命名与带入提示、T-1~T-5 测试方法；⑤ 章节重新编号（§8 评审 / §9 里程碑 / §10 决策 / §11 历史）。
