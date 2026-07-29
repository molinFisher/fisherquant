# PRD · 时间范围「当日」快捷按钮（评审稿 v1.0）

> 范围：数据中心「获取数据」时间范围选择器 + 行情看板「日线自定义区间」选择器
> 关联代码：`fisher/dash_app/pages/data_center.py`、`pages/quote_board.py`、`callbacks/data_callbacks.py`、`callbacks/quote_callbacks.py`
> 关联文档：`PRD_数据中心高级功能优化_V0.1.md`（现状盘点 §0 第 19 行提及）、`PRD_行情看板页体验优化_V1.0.md`（FR-3 自定义时间段）、`数据中心取数体验优化建议.md`（Q1/D2 日期自动设置）

---

## 0. 背景与已实现功能

用户需求三点：
1. 数据中心「获取数据」时间范围**默认 2024-01-01 → 当日**；
2. 数据中心手动范围控件内增加「当日」按钮；
3. 行情看板自定义范围控件内增加「当日」按钮。

**当前落地状态（实测）**：

| 能力 | 实现位置 | 状态 |
|---|---|---|
| 数据中心默认终点=当日 | `data_center.py:86` `end_date=datetime.date.today().isoformat()` | ✅ 本轮新增（原硬编码 `2024-12-31`） |
| 数据中心「当日」按钮 | `data_center.py:90` `dc-range-today-btn` → 回调 `set_range_today`（`data_callbacks.py:422`） | ✅ 已存在（commit 5f5ab09） |
| 行情看板「当日」按钮 | `quote_board.py:119` `qb-daily-today-btn` → 回调 `set_daily_today`（`quote_callbacks.py:768`） | ✅ 已存在（commit 5f5ab09） |
| 导出起止「当日」按钮（顺带存在） | `data_center.py` `export-today-btn` → `set_export_today`（`data_callbacks.py:433`） | ✅ 已存在，但含死代码（见 §2-F4） |

**行为事实（来自代码）**：
- `set_range_today`：返回 `(today, today)` → 数据中心范围变为**当日单日**。
- `set_daily_today`：返回 `(today, today, "custom")` → 看板区间变当日且自动切到「自定义」档以触发自定义分支渲染。
- 两个回调均 `prevent_initial_call=True` → 仅点击时触发，不随页面加载误触发。
- 布局在 `routing.py:45-49` 的 `render_page` 中**每次进入页面重新构建** → `end_date=today` 在每次导航时按当日重算（非进程启动冻结）。

---

## 1. 开发视角评审（Dev）

| 编号 | 发现 | 严重度 | 说明 |
|---|---|---|---|
| D1 | `on_data_type_change` 仅处理「分钟线」，切回日线/复权/财务时**不重置日期** | 中 | 回调（`data_callbacks.py:414`）对非 `minute` 类型 `return None`（无输出更新），于是从分钟线（近 7 天）切到日线时，范围停留在近 7 天，而非文档 `数据中心取数体验优化建议.md` D2 约定的"每次切类型都重设日期"→ 应为 `2024-01-01 ~ 当日`。与"默认到当日"的新预期不一致。 |
| D2 | `set_export_today` 含**不可达死代码** | 低 | `data_callbacks.py:443` 已 `return today, today`，其后 444–445 行的 `return "2024-01-01","2024-12-31"` 永远执行不到，是历史遗留的半成品逻辑，应清理。 |
| D3 | 「当日」语义为**单日范围**（start=end=today） | 低 | 数据中心的"当日"把起点也设为今天，即只取今日。若产品本意是"保持起点 2024-01-01、仅把终点设今日"，应改为返回 `("2024-01-01", today)`。需与产品确认（见 §4 澄清项）。 |
| D4 | 非交易日点击「当日」取数为空 | 低 | 若 today 为周末/休市，akshare 返回 0 行 → 显示"无数据"，不报错但体验空。可增强为回退最近交易日（非阻塞）。 |
| D5 | 默认终点在「同页面跨午夜」场景不自动刷新 | 低 | 仅导航重建时重算；用户停留在数据中心页跨过 0 点不刷新。绝大多数使用路径（进入页面）已正确，属可接受边界；若需绝对实时可改为页面进入回调设置。 |

**开发结论**：核心功能正确、无崩溃风险；D1 是唯一值得修的逻辑缺口（与文档意图不符），D2 为代码整洁项。

---

## 2. 设计视角评审（Design / UX）

| 编号 | 发现 | 严重度 | 说明 |
|---|---|---|---|
| S1 | 两模块按钮**摆放不一致** | 低 | 数据中心按钮在日期控件**下方**（竖向，`ms-2 mt-1`）；行情看板按钮在控件**右侧**（flex 横向）。建议统一为"紧贴日期控件右侧"，降低认知成本。 |
| S2 | 标签「当日」语义略隐晦 | 低 | hover 有 `title`（"将时间范围设为今天"/"将日线区间设为今天"），但静态标签未明示"会同时改起止"。可改为「设为今天」或在按钮旁加极小提示；当前 tooltip 已足够，列为锦上添花。 |
| S3 | 看板点「当日」后切到「自定义」档的反馈 | 低 | 自动将 `qb-daily-range` 设为 `"custom"` 是正确的（否则不触发自定义渲染），但用户可能未察觉"自定义"被选中。可在选中态高亮或简短提示。 |
| S4 | 视觉权重 | 低 | 均为 `color="light"` 小按钮，作为快捷入口合适；不影响主流程。 |

**设计结论**：交互闭环成立、无误导；仅样式一致性（S1）值得顺手统一。

---

## 3. 测试视角评审（Test / QA）

| 编号 | 发现 | 严重度 | 说明 |
|---|---|---|---|
| T1 | 已覆盖三个回调单测 | — | `test_quote_board_optimization.py:300-334`：`test_set_daily_today_sets_today_and_custom`、`test_set_range_today_sets_today`、`test_set_export_today_sets_today` 均通过（`pytest -k today` → 3 passed）。 |
| T2 | **缺 `on_data_type_change` 单测** | 中 | 该回调既无测试，又存在 D1 缺口——补测可直接暴露"切回日线未重置"。应加：`minute→(today-7d, today)`；`daily/adj/financials→(2024-01-01, today)`（修复后）。 |
| T3 | **缺布局默认 `end_date==today` 单测** | 低 | 应断言 `create_data_center_layout()` 中 `date-range-picker.end_date == date.today().isoformat()`，防止回归回硬编码。 |
| T4 | 无端到端按钮点击验证 | 低 | 现有测试直接 `cb(1)` 调用，绕过了 Dash 框架；可用 `dash_duo` 模拟点击断言 UI/图表刷新（增强信心，非必需）。 |
| T5 | 看板「当日」→ 图表重渲未测 | 低 | 可加：点击后 `render_daily_chart` 收到 `custom_start=custom_end=today` 且 `daily_range=="custom"` 时走自定义分支。 |

**测试结论**：回调逻辑有基础覆盖；D1 缺口靠 T2 补测可防回归；T3 防默认回退。

---

## 4. 综合 Action Items

| ID | 项 | 视角 | 严重度 | 建议动作 |
|---|---|---|---|---|
| A1 | 补全 `on_data_type_change`：日线/复权/财务 → `(2024-01-01, today)`；分钟线 → `(today-7d, today)` | Dev | 中 | 改 `data_callbacks.py:414`，并加 T2 单测 |
| A2 | 清理 `set_export_today` 死代码（删除 444–445 不可达行） | Dev | 低 | 直接删 |
| A3 | 统一两模块「当日」按钮为"紧贴日期控件右侧" | Design | 低 | 改 `data_center.py` 按钮外层为 flex（参照 `quote_board.py:109-124`） |
| A4 | 「当日」语义澄清：单日（当前）vs 保持起点仅设终点 | Dev/Design | 低 | 与产品确认；若选后者改 `set_range_today`/`set_daily_today` 返回起点 |
| A5 | 增加布局默认 `end_date==today` 单测（T3） | Test | 低 | 加 `tests/unit/test_data_center_layout.py` 或并入现有 |
| A6 | 非交易日「当日」回退最近交易日（可选增强） | Dev | 低 | 后续，不阻塞 |

---

## 5. 修订后验收标准（AC）

- **AC-1**：进入数据中心页，时间范围默认 `2024-01-01 ~ 当日`（`end_date == today`，T3 守护）。
- **AC-2**：点击数据中心「当日」→ 范围变为当日单日（`start == end == today`）。
- **AC-3（A1 修复后）**：切换数据类型——分钟线→近 7 天；日线/复权/财务→`2024-01-01 ~ 当日`。
- **AC-4**：行情看板选「自定义」后点「当日」→ 区间=当日且自动切到「自定义」档，日 K 仅显示当日。
- **AC-5**：单测覆盖 `set_range_today` / `set_daily_today` / `set_export_today` / `on_data_type_change` / 布局默认（T1+T2+T3）。
- **AC-6**：导出起止「当日」按钮正常（无死代码告警），起止均设今日。

---

## 6. 评审结论

功能**已可用、无阻断性缺陷**，满足用户三点诉求。需跟进的中优先级项仅 **A1（切回日线未重置日期，与文档意图不符）**；其余为一致性/整洁/增强类低优先级项。建议 A1+A2+A3+A5 随下一次提交一并处理，A4 待产品确认语义。

> 注：本评审稿为对既有实现（commit 5f5ab09 + 本轮默认日期修改 1463102）的复盘，不阻塞当前线上版本。
