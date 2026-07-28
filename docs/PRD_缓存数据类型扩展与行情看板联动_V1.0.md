# PRD：缓存数据类型扩展与行情看板联动 V1.0

| 项目 | 内容 |
|---|---|
| 需求名称 | 缓存数据类型扩展（分钟线 / 实时快照 / 复权因子 / 财务）并与行情看板联动 |
| 版本 | V1.0.1（评审修订版） |
| 状态 | 评审意见已合入（研发 D / 设计 U / 测试 T，见 §13） |
| 作者 | 产品（高级产品经理） |
| 评审方 | 研发（D-x）、设计（U-x）、测试（T-x），意见清单见 §13 |
| 日期 | 2026-07-28 |
| 关联模块 | `DataCacheService`、`CacheCatalogService`（新增）、行情看板（`quote_board`/`quote_callbacks`）、`AutoLoadService`、`bars_daily`/`bars_minute`/`snapshots`/`corporate_actions`、`cache_catalog`（新增） |
| 关联需求 | V1.3 自动加载历史数据感知与断点续传（已上线）；V1.2 标的搜索优化（已上线） |

---

## 1. 背景

### 1.1 现状问题（已定位代码根因）

| # | 现象 | 根因 |
|---|---|---|
| P1 | 「已缓存数据」页面只有"数据条数/起始日期/最新日期"六列，**无任何"数据类型"维度**，所有缓存被等同视为日线 | `data_cache_callbacks.render_cached_table` 的 `get_cached_table()` 仅 `SELECT ... FROM bars_daily`，字段固定为 `ticker/name/market/records/start_date/end_date`，无类型列 |
| P2 | 行情看板"最新价 / 涨跌幅"实为**日频涨跌**（取 `bars_daily` 最近两日收盘相减），并非真实行情；交易日盘中恒等于昨收变化 | `quote_callbacks._fetch_quote_data` 仅查 `bars_daily` 最近 2 行算 `change_pct`，无实时数据源 |
| P3 | 行情看板"自动刷新(60s)"只是**重复查询同一批旧 DB 行**，不产生任何新数据，"实时"是伪实时 | `qb-refresh-interval` 仅重触发 `update_watchlist`，数据源依旧是静态 `bars_daily` |
| P4 | 行情看板与缓存是**两张皮**：看板自选存于独立 `data/watchlist.json`，缓存页无法把标的"推"进看板，看板也不反映缓存健康度 | 两模块仅通过 `bars_daily` 弱耦合；缓存页无"加入看板"动作，看板无从获知某标的缺哪些数据类型 |
| P5 | 看板"添加标的"下拉来自 `SELECT DISTINCT ticker FROM bars_daily`，**可选出永远取不到分钟/实时数据的死标的**，用户无感知 | `_get_cached_symbols` 只按日线去重，未区分数据类型的覆盖度 |
| P6 | 自动加载只缓存**未复权日线**（沪深300 + 港股前 80）+ 顺带写港股名；`adj_factor` 恒为 `1.0`，**分钟线 / 实时快照 / 复权因子 / 财务数据均不进缓存** | `auto_load_service` 仅写 `bars_daily`；`bars_minute`、`snapshots`、`corporate_actions` 三张物理表已建但**从未被写入**，等于空脚手架 |
| P7 | 缓存宇宙与用户实际关注标的脱节：自动加载覆盖面（指数成分）≠ 用户看板自选，导致看板标的常缺数据 | 自动加载 `initial_universe` 写死"both"（沪深300+港股80），与看板 `watchlist` 无交集计算 |

### 1.2 核心设计转变

V1.3 前：缓存 = 一张日线库存清单；看板 = 脱离缓存、且只有日频伪实时的自选表。

**V1.0（本 PRD）：把缓存升级为"多类型数据资产目录"（DB as Asset Catalog），并让行情看板以缓存为唯一数据源、由新增的"实时快照 / 分钟线"缓存真正驱动报价。**

> 新增 `cache_catalog` 元数据表（每标的 × 每数据类型覆盖度）作为**联动中枢**：缓存目录页用它做类型筛选，行情看板用它显示覆盖度徽标与"去缓存"入口，自动加载用它把"加载宇宙"收敛为 `auto_load_enabled=TRUE` 的显式集合（看板自选默认纳入，一次性获取默认不纳入，见 FR-7.5）。三个模块由此被同一份覆盖度元数据驱动，而非各自为政。

### 1.3 用户价值

- 用户要的不是"库里有没有这只股票"，而是"这只股票**有哪些数据可用**"——日线/分钟/实时/复权/财务是不同决策依据，必须可区分。
- 看板"实时涨跌"长期是昨收差值，盘中毫无意义；引入实时快照后，看板才真正"活"起来。
- 缓存页与看板打通后，数据获取 → 观察分析的闭环从"两次手动粘贴代码"缩短为"一次点击"，显著降低使用摩擦。

---

## 2. 目标与非目标

### 2.1 目标

1. 缓存系统支持**至少 5 类**数据资产：日线（已有）、分钟线、实时快照、复权因子、财务数据；每类在缓存目录页可独立呈现、筛选。
2. 行情看板"最新价 / 涨跌幅"**真正来自实时快照**（`pre_close` 口径），盘中随自动刷新推进。
3. 缓存目录页与行情看板**双向联动**：目录→看板（加入/跳转）、看板→目录（覆盖度回显 + 去缓存）。
4. 看板"添加标的"下拉**只出已缓存标的**，杜绝死标的（含存量 `watchlist` 清理）。
5. 自动加载"加载宇宙"扩展为**显式 `auto_load_enabled` 集合**（覆盖看板自选与用户纳入项），并新增分钟线 / 实时快照的盘中定时增量。

### 2.2 非目标（本期不做）

- 不做多数据源容灾（仍以 akshare 为唯一行情源）。
- 不做分钟线的多周期（1m/15m/30m/60m）全量历史——本期仅缓存**窗口内**（默认 T-60 交易日）的单一周期（默认 5m），多周期作为后续版本。
- 不做财务数据的因子化 / 衍生指标计算，仅入库原始指标。
- 不替换 `data/watchlist.json` 的存储形态（仍用文件，但读写统一收敛到一处服务，便于后续迁库）。

---

## 3. 用户故事

- **US-1**：作为量化研究者，我在缓存页看到某标的只有日线，点"加入行情看板"后跳转到看板并定位到它，无需再手动抄代码。
- **US-2**：作为日内交易者，盘中打开看板，希望"最新价 / 涨跌幅"是真实盘口而非昨收差值，且每 60s 自动推进。
- **US-3**：作为用户，我在看板看到某标的只有"日线✓ 实时✗"徽标，点"去缓存"直达数据中心并预筛选该标的，一键补齐实时/分钟。
- **US-4**：作为用户，我在看板点"添加"，下拉里只出现我已缓存的标的；想看的未缓存标的被提示"先去获取"，不再出现加进去却永远空白的行。
- **US-5**：作为用户，我把某只看板自选标的"纳入自动加载"后，它开始每日补齐分钟线 / 实时快照，看板覆盖度徽标从"✗"变"✓"。

---

## 4. 功能需求（EARS 规范）

### FR-1 缓存资产目录（联动中枢）

- **FR-1.1（Ubiquitous）** The system shall 新增 `cache_catalog` 表（DDL 见 §7），逐标的记录 5 类数据资产的覆盖布尔（`has_daily/has_minute/has_realtime/has_adj/has_financials`）及各自时间边界（`daily_start/daily_end/minute_start/minute_end/realtime_ts/fin_report_end`），并含 `auto_load_enabled` 自动加载开关。
- **FR-1.2（Event-driven）** When 任一类数据写库成功, the system shall 在同一事务内 upsert 该标的在 `cache_catalog` 的对应 `has_*` 与边界字段（复用 V1.3 `DuckDBManager.transaction()` 短事务，禁止跨标的长事务）。
- **FR-1.3（Ubiquitous）** The system shall 提供 `get_cache_catalog(market=None, data_type=None, text=None)` 查询接口：按 `data_type ∈ {daily,minute,realtime,adj,financials}` 过滤 `has_<type>=TRUE`，供目录页筛选与看板健康度共用。
- **FR-1.4（Ubiquitous）** The system shall 在 `cache_catalog` 中冗余 `name/market`，使目录页与看板徽标**不依赖 `symbol_dict` JOIN** 即可渲染（性能 + 容错）。
- **FR-1.5（Unwanted）** If 某标的的某一类型数据被删除（如用户清空分钟线）, then the system shall 同步将该 `has_*` 置 FALSE 并更新边界为 NULL，保持目录与物理数据一致。
- **FR-1.6（Ubiquitous）**〔评审新增 D-2〕 The system shall 提供统一的 `CacheCatalogService.record_coverage(db, ticker, data_type, boundary)` 辅助函数，由**所有数据写入方**（`data_center_service.fetch_bars`、`auto_load_service` 各类型补齐）在各自写库所在的同一 `DuckDBManager.transaction()` 内调用，保证"数据行 + 目录覆盖度"原子更新；禁止数据写一处、目录更新另起一事务（否则会漂移，见验收 13）。
- **FR-1.7（Ubiquitous）**〔评审新增 D-6〕 The system shall 所有 `cache_catalog` 的写入/更新**仅经由 `DuckDBManager` 单写连接**（`write_connection`），禁止在回调/线程中新建独立 `duckdb.connect` 写连接——避免重现 V1.3 之前"双进程/独立连接争夺独占锁导致重建空库"的回归。

### FR-2 扩展缓存数据类型

- **FR-2.1（Ubiquitous）** The system shall 支持缓存**分钟线**：写入已存在的 `bars_minute` 表（字段 `ticker/bar_time/open/high/low/close/volume/amount/market`，主键 `(ticker,bar_time)`）；v5 迁移为 `bars_minute` 增加 `period VARCHAR DEFAULT '5'`（P0 仅写默认 '5'，多周期见风险 #4 / P2）。〔评审修订 D-3：删除原"主键扩展为复合键"表述，避免与 §7.4 自相矛盾——多周期主键变更推迟至 P2〕
- **FR-2.2（Ubiquitous）** The system shall 对分钟线实施**窗口缓存策略**：仅缓存最近 `minute_window_days`（默认 60 交易日）内的数据；超出窗口的历史分钟行由清理任务惰性删除（窗口与"当前时间"均可注入，便于自动化测试，见验收 9）。
- **FR-2.3（Ubiquitous）** The system shall 支持缓存**实时快照**：写入 `snapshots` 表（v5 起主键 `(ticker,ts)`，含 `last_price/open/high/low/volume/amount/pre_close/market/change_pct`）；`change_pct = (last_price-pre_close)/pre_close*100` 落库计算避免读时漂移；按 `(ticker,ts)` `INSERT OR REPLACE` 幂等更新（见 §7.4、风险 #6 已解决）。
- **FR-2.4（Ubiquitous）** The system shall 支持缓存**复权因子**：新增 `adj_factors` 表（DDL 见 §7，主键 `(ticker,trade_date,adj_type)`，`adj_type∈{qfq,hfq}`），由 `corporate_actions` 事件（分红/拆送）或 `stock_zh_a_daily(adjust=...)` 因子序列回填；写入后同步刷新 `bars_daily.adj_factor` 或提供视图换算（P1，口径一致性见风险 #3）。
- **FR-2.5（Ubiquitous）** The system shall 支持缓存**财务数据**：新增 `financials` 表（DDL 见 §7，主键 `(ticker,report_date,indicator)`），由 `stock_financial_abstract` 抽取**预定义指标集**（营收/归母净利/ROE/资产负债率等，指标清单在 P2 实现前固化）入库。
- **FR-2.6（State-driven）** While 某数据类型尚未被自动加载或手动获取覆盖, the system shall 在 `cache_catalog` 中保持对应 `has_*=FALSE`，不臆造数据。
- **FR-2.7（Unwanted）** If 上游接口返回空（如停牌、未上市）, then the system shall 不写该行、不改 `has_*` 为 TRUE，仅记录日志。

### FR-3 联动机制 A：目录 → 看板（加入 / 跳转）

- **FR-3.1（Event-driven）** When 用户在缓存目录页某行点"加入行情看板", the system shall 将该 `ticker` 写入看板自选（统一收敛到 `_save_watchlist`，去重），置 `cache_catalog.auto_load_enabled=TRUE`（FR-7.5），并跳转至行情看板并定位该标的（见 IC-1）。
- **FR-3.2（Ubiquitous）** The system shall 在缓存目录页提供顶部"批量加入"：对当前筛选结果（或勾选行）批量写入看板自选。
- **FR-3.3（Event-driven）** When 行情看板以 `?focus=<ticker>` 进入, the system shall 确保该 `ticker` 已在看板自选（不在则加入当且仅当其在 `cache_catalog` 有任意 `has_*=TRUE`），并置顶/高亮/滚动至该行；消费后清除 `?focus=` 参数（U-2 / IC-1）。

### FR-4 联动机制 B：看板 → 目录（覆盖度回显）

- **FR-4.1（Ubiquitous）** The system shall 在行情看板每行显示**紧凑型数据覆盖度徽标**（同一单元格内 icon-only 标记组：日/分/实/复 四类，✓绿 ✗灰，hover 出类型名+边界日期；财务为 P2 折叠不显，见 U-1）。
- **FR-4.2（Event-driven）** When 用户点某标的的"去缓存"入口, the system shall 跳转至数据中心 `?tab=tab-cached&focus=<ticker>`，并预置该标的的筛选，便于一键补齐缺失类型；消费后清除 `?focus=`（U-2 / IC-2）。
- **FR-4.3（Ubiquitous）** The system shall 把行情看板变为"缓存健康度仪表盘"：顶部汇总"看板标的中拥有实时/分钟缓存的比例"，缺失类型给一键"批量去缓存"入口。

### FR-5 联动机制 C：看板数据源收敛

- **FR-5.1（Ubiquitous）** The system shall 将看板"添加标的"下拉选项收敛为 `cache_catalog` 中 `has_daily OR has_minute = TRUE` 的标的（即"至少有可观测行情"），替代现行 `SELECT DISTINCT ticker FROM bars_daily`。
- **FR-5.2（Unwanted）** If 用户输入的标的**不在缓存中**, then the system shall 在下拉提示"该标的未在缓存中，请先去数据中心获取"，禁止加入死标的。
- **FR-5.3（Event-driven）**〔评审新增 T-4〕 When 应用启动或看板首次加载, the system shall 对既有 `watchlist.json` 做一次**健康 pruning**：仅保留 `cache_catalog` 中 `has_daily OR has_minute = TRUE` 的标的，移除历史遗留的死标的（IC-3 只约束"新增"路径，不处理存量，故需此步结构性清零死标的）。pruning 结果回写 `watchlist.json`，并打 `watchlist_pruned{removed:[...]}` 埋点。

### FR-6 行情看板实时报价源切换

- **FR-6.1（Ubiquitous）** The system shall 将看板"最新价 / 涨跌幅 / 成交量"的数据源从 `bars_daily` 末两日切换为 `snapshots`（实时快照）：`last_price` 取 `snapshots.last_price`，`change_pct` 取 `snapshots.change_pct`（基于 `pre_close` 的真实盘口涨跌），`volume` 取 `snapshots.volume`（见 IC-4）。
- **FR-6.2（Unwanted）** If 某标的**无实时快照**（如非交易时段、未纳入实时增量宇宙）, then the system shall 降级回退到 `bars_daily` 日频涨跌口径，并在徽标上标记"实时✗（日频）"，不报错不空白（该降级路径须有单元可测，见验收 15）。
- **FR-6.3（State-driven）** While 处于交易时段（复用现有 `check_trading_hours` 逻辑）, the system shall 按 `qb-refresh-interval`（默认 60s，可关）轮询 `snapshots` 推进报价；非交易时段由实时刷新守护线程挂起（FR-7.6），不空转轮询。

### FR-7 自动加载范围与频率扩展

- **FR-7.1（Ubiquitous）** The system shall 将自动加载"加载宇宙"由写死的"沪深300+港股80"扩展为 **`cache_catalog.auto_load_enabled = TRUE` 的标的**（该集合覆盖看板自选与用户显式纳入自动加载的标的，见 FR-7.5）。〔评审修订 D-4：原"watchlist ∪ 全部 has_*=TRUE"会因一次性大批量获取而意外把整库纳入每日自动加载、冲破限频，故改为带开关的显式集合〕
- **FR-7.2（Ubiquitous）** The system shall 在盘中新增**分钟线 / 实时快照的定时增量**：实时快照每 `realtime_poll_min`（默认 60s，受 RateLimiter 约束，避免 akshare 限频）整批刷新看板自选快照；分钟线每日盘后补齐当日。
- **FR-7.3（Ubiquitous）** The system shall 复用 V1.3 的计划生成（FULL/GAP/SKIP）与账本（`symbol_load_state`）机制，新数据类型在同一个"缺什么补什么"框架下扩展，不另起一套。
- **FR-7.4（Unwanted）** If 实时快照刷新触发 akshare 限频/超时, then the system shall 走现有重试（FR-4.2 退避）并跳过该轮，不阻塞日线/分钟补齐主流程，不污染 `cache_catalog`。
- **FR-7.5（Ubiquitous）**〔评审新增 D-4〕 The system shall 在 `cache_catalog` 增加 `auto_load_enabled BOOLEAN DEFAULT FALSE` 字段；"加入行情看板"（FR-3.1）时置 TRUE，一次性手动获取（数据中心"开始获取数据"）默认 FALSE（用户可在缓存目录行勾选"纳入自动加载"显式开启）。自动加载宇宙严格以 `auto_load_enabled=TRUE` 为唯一来源。
- **FR-7.6（Ubiquitous）**〔评审新增 D-5〕 The system shall 以**进程内守护线程**（非 Dash `Interval`）承载盘中实时快照刷新，线程由交易时段门控（复用现有 `check_trading_hours` 逻辑，非交易时段挂起）；该线程与 V1.3 自动加载线程共用 `DuckDBManager` 单写连接串行化，互不阻塞读连接。

### FR-8 缓存目录页多类型展示与筛选

- **FR-8.1（Ubiquitous）** The system shall 在缓存目录页新增"数据类型"筛选控件（多选：日线/分钟/实时/复权/财务，与"市场"下拉并排，见 U-3），筛选走 `get_cache_catalog(data_type=...)`。
- **FR-8.2（Ubiquitous）** The system shall 在目录表每行增加"覆盖度"列（紧凑徽标组，见 U-1），并保留现有"代码/名称/市场/数据条数/起止日期"基础列（条数聚合需按类型分别统计，见 §7 视图）。
- **FR-8.3（Event-driven）** When 用户点"删除"，the system shall 经 `dbc.Modal` **二次确认**后执行；支持按数据类型删除（删除某标的的分钟线而非整行），并联动 `cache_catalog` 对应 `has_*`（FR-1.5）；整行删除同样经二次确认。〔评审修订 U-4：现行删除无任何确认即执行，属既有风险，本 PRD 统一补齐确认，危险操作按钮 `color="danger"`〕

---

## 5. 流程说明

### 5.1 数据获取 → 目录 → 看板 主链路

```
用户在数据中心搜索并"开始获取数据"（勾选 日线/分钟/实时/复权/财务）
  → 各类型写库（bars_daily / bars_minute / snapshots / adj_factors / financials）
  → 同一事务内 record_coverage 更新 cache_catalog（has_* + 边界，FR-1.6）
  → 缓存目录页刷新，出现该标的且覆盖度徽标正确
  → 用户点"加入行情看板" → 写入 watchlist + auto_load_enabled=TRUE + 跳转看板 ?focus=ticker
  → 看板渲染该标的，显示实时报价（snapshots）与覆盖度徽标
```

### 5.2 自动加载新宇宙（FR-7）

```
定时（或冷启动）：取 加载宇宙 = cache_catalog WHERE auto_load_enabled = TRUE（FR-7.5）
  → 复用 V1.3 计划生成（按市场新鲜度基准）
  → 日线：缺口补齐（现状）
  → 分钟线：窗口内当日补齐
  → 实时快照：盘中由守护线程（FR-7.6）每 60s 批量刷新（受限频）
  → 每类写库成功即 record_coverage 更新 cache_catalog
```

### 5.3 看板健康度回显（FR-4）

```
看板加载 → 读 cache_catalog（批量 ticker IN (...)）→ 每行紧凑徽标
  → 缺失类型 "去缓存" 深链 → 数据中心预筛选 → 用户补齐 → 回到看板徽标翻转
```

---

## 6. 交互说明（联动与组件矩阵）

| 触发点 | 动作 | 目标模块 | 契约 |
|---|---|---|---|
| 缓存目录行"加入行情看板" | 写 watchlist + 置 auto_load_enabled + 跳转 | 行情看板 | IC-1（`?focus=`） |
| 缓存目录"批量加入" | 批量写 watchlist | 行情看板 | IC-1 |
| 看板行"去缓存" | 跳转数据中心预筛选 | 数据中心 | IC-2（`?tab=tab-cached&focus=`） |
| 看板"添加"下拉 | 仅出已缓存标的 | 缓存目录 | IC-3 |
| 看板刷新 | 读 snapshots（实时） | 实时快照 | IC-4 |
| 看板顶部"健康度" | 实时/分钟覆盖率汇总 | cache_catalog | FR-4.3 |

边界交互：
- "加入行情看板"对已在看板的标的，跳转后改为"已存在"提示，不重复写入。
- 实时快照降级（FR-6.2）时，徽标"实时✗（日频）"用 `text-warning`；完全无数据用 `text-muted`。
- 缓存目录"按类型删除"在 `dbc.Modal` 二次确认中明示"将删除该标的的【分钟线】数据，日线及其他类型不受影响"（FR-8.3）。
- 看板"成交量"列统一标注单位（如"万手"），tooltip 给原始值，避免实时/日线量纲（手/股）误读（U-5）。

设计评审补充（已合入）：
- **U-1 徽标紧凑化**：覆盖度徽标不再占 4 列，改为目录页/看板**同一单元格内一组 icon-only 标记**（✓绿/✗灰，顺序 日/分/实/复），hover 显示类型名与边界日期 tooltip；看板行不因 4 徽标挤压（FR-4.1 同步调整）。
- **U-2 聚焦参数清理**：消费 `?focus=` 后通过 `dcc.Location` `replace` 清除该参数，避免用户手动刷新看板时反复置顶（IC-1/IC-2 同步更新）。
- **U-3 筛选布局**：缓存目录页"数据类型"多选与现有"市场"下拉并排置于筛选行，文本搜索框保持原位，避免页面纵向拥挤。
- **U-4 删除二次确认**：现行缓存删除**无任何确认**即执行，属既有风险；本 PRD 要求"整行删除"与"按类型删除"均经 `dbc.Modal` 二次确认（FR-8.3），确认文案明示将删除的数据类型与影响范围；确认按钮在危险操作下用 `color="danger"`。
- **U-5 量纲一致性**：实时快照 `volume` 与日线 `volume` 单位（手/股）可能不同，看板"成交量"列统一标注单位，tooltip 给原始值，避免跨源误读。

---

## 7. 数据结构

随 schema 迁移版本 **v5** 发布（当前 `SCHEMA_VERSION=4`，加新表并同步加入 `_TABLES` 以保证新建库即时建表，模式同 V1.3 的 `symbol_load_state`）。

### 7.1 新增 `cache_catalog`（联动中枢，FR-1）

```sql
CREATE TABLE IF NOT EXISTS cache_catalog (
    ticker           VARCHAR PRIMARY KEY,   -- 标准代码，覆盖度定位键
    market           VARCHAR,                -- a_share / hk_connect
    name             VARCHAR,                -- 冗余名称，免 JOIN symbol_dict
    has_daily        BOOLEAN DEFAULT FALSE,  -- 日线覆盖
    has_minute       BOOLEAN DEFAULT FALSE,  -- 分钟线覆盖
    has_realtime     BOOLEAN DEFAULT FALSE,  -- 实时快照覆盖
    has_adj          BOOLEAN DEFAULT FALSE,  -- 复权因子覆盖
    has_financials   BOOLEAN DEFAULT FALSE,  -- 财务数据覆盖
    auto_load_enabled BOOLEAN DEFAULT FALSE, -- 是否纳入自动加载宇宙（FR-7.5）
    daily_start      DATE,                   -- 日线最早交易日
    daily_end        DATE,                   -- 日线最新交易日
    minute_start     TIMESTAMP,              -- 分钟线最早
    minute_end       TIMESTAMP,              -- 分钟线最新
    realtime_ts      TIMESTAMP,              -- 最近一次快照时间
    adj_type         VARCHAR,                -- qfq / hfq / none
    fin_report_end   DATE,                   -- 财务最新报告期
    last_update      TIMESTAMP,              -- 最近一次任一类型写库时间
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 7.2 新增 `adj_factors`（FR-2.4）

```sql
CREATE TABLE IF NOT EXISTS adj_factors (
    ticker     VARCHAR NOT NULL,
    trade_date DATE NOT NULL,
    adj_type   VARCHAR NOT NULL,   -- qfq / hfq
    adj_factor DOUBLE NOT NULL,
    PRIMARY KEY (ticker, trade_date, adj_type)
);
```

### 7.3 新增 `financials`（FR-2.5）

```sql
CREATE TABLE IF NOT EXISTS financials (
    ticker      VARCHAR NOT NULL,
    report_date DATE NOT NULL,
    report_type VARCHAR,           -- 年报 / 中报 / 一季报 / 三季报
    indicator   VARCHAR NOT NULL,  -- 营业收入 / 归母净利润 / ROE / 资产负债率 ...
    value       DOUBLE,
    unit        VARCHAR,           -- 元 / % / 倍
    PRIMARY KEY (ticker, report_date, indicator)
);
```

### 7.4 既有表扩展（v5）

```sql
-- bars_minute 增加周期列，支持多周期（本期仅写默认 '5'）
ALTER TABLE bars_minute ADD COLUMN IF NOT EXISTS period VARCHAR DEFAULT '5';
-- 注：物理主键 (ticker,bar_time) 暂不 ALTER 为复合键以减小迁移风险；
--     多周期冲突由应用层在写入前按 (ticker,bar_time,period) 去重（INSERT OR REPLACE）保证。

-- snapshots 重新定义主键为 (ticker, ts)，去掉无意义的 id 自增列，
-- 使实时刷新可按 (ticker, ts) 幂等 upsert（原 id BIGINT PK 无法支撑按标的更新，D-1 已解决）。
-- 既有库 snapshots 为空脚手架（从未写入）；迁移前断言为空后 DROP+CREATE，非空则中止报错（见验收 17）。
DROP TABLE IF EXISTS snapshots;
CREATE TABLE snapshots (
    ticker      VARCHAR NOT NULL,
    ts          TIMESTAMP NOT NULL,
    last_price  DOUBLE,
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    volume      BIGINT,
    amount      DOUBLE,
    pre_close   DOUBLE,
    market      VARCHAR DEFAULT 'a_share',
    change_pct  DOUBLE,
    PRIMARY KEY (ticker, ts)
);
```

> 说明：`bars_daily`（日线，已用）、`bars_minute` / `snapshots` / `corporate_actions`（物理表已建但**从未被自动加载或缓存服务写入**）在本 PRD 中被正式纳入写入与目录体系，从"空脚手架"转为"已用资产"。`snapshots` 主键由 v5 起改为 `(ticker,ts)`。

### 7.5 目录聚合视图（供 FR-8.2 按类型统计条数）

```sql
CREATE VIEW IF NOT EXISTS v_cache_summary AS
SELECT
    c.ticker, c.name, c.market, c.auto_load_enabled,
    c.has_daily, c.has_minute, c.has_realtime, c.has_adj, c.has_financials,
    c.daily_start, c.daily_end, c.realtime_ts,
    (SELECT COUNT(*) FROM bars_daily d WHERE d.ticker = c.ticker)        AS daily_rows,
    (SELECT COUNT(*) FROM bars_minute m WHERE m.ticker = c.ticker)       AS minute_rows,
    (SELECT COUNT(*) FROM snapshots  s WHERE s.ticker = c.ticker)        AS realtime_rows,
    (SELECT COUNT(*) FROM adj_factors a WHERE a.ticker = c.ticker)       AS adj_rows,
    (SELECT COUNT(*) FROM financials f WHERE f.ticker = c.ticker)        AS fin_rows
FROM cache_catalog c;
```

---

## 8. 接口契约（Interface Contracts）

**IC-1 目录→看板（加入/跳转）**
- 入口：缓存目录页行内按钮 `btn-cache-add-to-board`（独立 id，沿用 V1.3 U-5 组件 id 可寻址约束）。
- 行为：调用统一 `add_to_watchlist(ticker)` → 写 `data/watchlist.json`（去重）；置 `cache_catalog.auto_load_enabled=TRUE`（FR-3.1/FR-7.5）；`dcc.Location` 跳转 `pathname=/quote-board`、`search=?focus=<ticker>`。
- 看板侧：读 `url.search` 的 `focus` 参数（新增回调 `Input("url","search")`），命中则在 `update_watchlist` 前确保该 ticker 入 `watchlist`（仅当其 `cache_catalog` 有任一 `has_*=TRUE`），并置顶高亮；**消费后通过 `replace` 清除 `?focus=` 参数，避免手动刷新反复置顶（U-2）**。

**IC-2 看板→目录（去缓存）**
- 入口：看板行内 `btn-qb-goto-cache`（独立 id）。
- 行为：跳转 `pathname=/data-center`、`search=?tab=tab-cached&focus=<ticker>`；数据中心 `tab-cached` 初始化时读 `focus` 预置 `cache-filter-input` 为该 ticker 并触发 `render_cached_table`；**消费后同样 `replace` 清除 `?focus=`（U-2）**。

**IC-3 看板数据源收敛**
- 替换 `quote_callbacks._get_cached_symbols`：由 `SELECT DISTINCT ticker FROM bars_daily` 改为 `SELECT ticker, name FROM cache_catalog WHERE has_daily OR has_minute ORDER BY ticker`；下拉 `options` 的 `label` 用 `name(ticker)` 更友好。
- 未匹配输入时附加一条 `{"label":"未在缓存中？去获取 →","value":"__goto_fetch__","disabled":True}` 提示项（U-3）。

**IC-4 实时报价源切换**
- 替换 `quote_callbacks._fetch_quote_data` 数据源：`snapshots` LEFT JOIN `cache_catalog`；`last_price=snapshots.last_price`、`change_pct=snapshots.change_pct`、`volume=snapshots.volume`；无快照行则降级读 `bars_daily` 末两日（FR-6.2，须有单元可测路径，见验收 15）。
- 查询以 `ticker IN (...)` 批量 `JOIN`，避免 N 次点查（沿用 V1.3 聚合查询思路）。

---

## 9. 数据指标与埋点

| 指标 | 口径 | 目的 |
|---|---|---|
| 看板实时覆盖率 | 看板标的中 `has_realtime=TRUE` 占比 | 目标 > 80%（P0 后） |
| 看板分钟覆盖率 | 看板标的中 `has_minute=TRUE` 占比 | 监控日内数据供给 |
| 缓存→看板转化率 | "加入行情看板"点击数 / 目录页访问数 | 验证联动价值 |
| 看板死标的占比 | 无任一 `has_*` 的看板标的占比 | 目标降至 0（IC-3 + FR-5.3 后结构性归零） |
| 每标的平均缓存类型数 | `SUM(has_*)/COUNT(*)` | 衡量资产多样性 |
| 实时刷新成功率 |  snapshots 刷新成功批次 / 总批次 | 监控限频影响 |
| 自动加载宇宙规模 | `auto_load_enabled=TRUE` 标的数 | 监控限频预算，防意外膨胀（FR-7.5） |

埋点事件（沿用 V1.3 `logger` 结构化 key=value，caplog 可断言）：`cache_type_written{ticker,type}`、`cache_add_to_board{ticker}`、`qb_goto_cache{ticker}`、`qb_quote_source{ticker,source}`（source∈snapshot/daily_fallback）、`realtime_snapshot_refreshed{ok,failed}`、`watchlist_pruned{removed:[...]}`。

---

## 10. 验收标准

1. **多类型入库**：手动获取某 A 股标的的日线+分钟+实时+复权+财务 → `cache_catalog` 该标的 5 个 `has_*` 全 TRUE，各边界字段非空；`v_cache_summary` 五类 `rows` 均 > 0。
2. **目录筛选**：选"数据类型=分钟"筛选 → 结果集恰为 `has_minute=TRUE` 的标的，无漏无多。
3. **实时报价真源**：交易时段内对某看板标的，其"最新价"等于 `snapshots.last_price` 且"涨跌幅"基于 `pre_close`（与 `bars_daily` 昨收差值可不同）；暂停实时刷新进程后看板仍显示最后快照，不报错。
4. **降级正确**：对某无快照标的，看板显示日频涨跌且徽标"实时✗（日频）"为 `text-warning`，不空白不报错。
5. **联动A**：缓存目录点"加入行情看板" → `watchlist.json` 含该 ticker（去重），`cache_catalog.auto_load_enabled=TRUE`，URL 跳至 `/quote-board?focus=<ticker>`，看板置顶高亮该行，刷新看板后不再反复置顶（参数已清除）。
6. **联动B**：看板某标的"分钟✗" → 点"去缓存" → URL 跳至 `/data-center?tab=tab-cached&focus=<ticker>`，目录页预筛选定位该标的，参数被消费后清除。
7. **联动C**：看板"添加"下拉仅含 `cache_catalog` 中 `has_daily OR has_minute` 的标的；输入未缓存代码时下拉提示"未在缓存中？去获取 →"，且不可加入死标的（含 FR-5.3 存量 pruning，见验收 16）。
8. **自动加载宇宙收敛**：将一只非沪深300/非港股80的标的"纳入自动加载"（`auto_load_enabled=TRUE`）→ 触发自动加载后该标的出现在加载计划并被补齐；未纳入的已缓存标的不会被自动加载（FR-7.5 开关语义）。
9. **分钟窗口**：以**可注入时钟** `now`（默认当前时间）与 `minute_window_days`（默认 60）判定窗口，构造数据早于 `now - window` 的分钟行 → 惰性清理后 `cache_catalog.minute_start` 前移至窗口起点（同 V1.3 FR-1.7 可注入，不依赖真实运行 60 天）。
10. **实时增量限频安全**：模拟 akshare 限频 → 实时刷新走重试退避、跳过该轮，日线/分钟补齐主流程不受影响，`cache_catalog` 不被污染（无 FALSE→TRUE 的误标）。
11. **删除联动**：删某标的"分钟线"类型（经二次确认）→ 仅 `bars_minute` 该标的数据减少，`cache_catalog.has_minute` 置 FALSE，`daily` 等其他类型不受影响；整行删除同样经确认。
12. **写库幂等**：同一标的同一区间重复获取**日线/分钟/实时/复权/财务**各类数据 → 对应表（`bars_daily`/`bars_minute`/`snapshots`/`adj_factors`/`financials`）行数不变（沿用 `INSERT OR REPLACE` 主键语义），`cache_catalog` 各边界不漂移。
13. **落库事务**（T-1）：单标的某类型写库与 `cache_catalog` 覆盖度更新在**同一 `DuckDBManager.transaction()`** 内（FR-1.6）；单测 `monkeypatch` `record_coverage` 抛异常 → 断言数据行与目录覆盖度**均回滚**（无"有数据但目录不显示"或反之）。
14. **存量兼容**：v5 迁移在既有库上可幂等重放；`bars_minute` 的 `ADD COLUMN IF NOT EXISTS period` 不报错；`snapshots` 仅当为空时 DROP+CREATE（非空则中止报错，见验收 17）；新建库 `_TABLES` 即时建全表。
15. **降级单元可测**（T-2）：单测构造 `snapshots` 对某标的为空 → 看板该标的取 `bars_daily` 末两日日频涨跌，`change_pct` 来源标记 `daily_fallback`，徽标"实时✗（日频）"为 `text-warning`；该用例不依赖网络。
16. **存量看板 pruning**（T-4）：构造 `watchlist.json` 含 3 只死标的（不在 `cache_catalog`）→ 看板首次加载后 `watchlist.json` 仅剩缓存标的，看板表格无空白死行；埋点 `watchlist_pruned` 记录移除列表。
17. **快照迁移安全**（T-7/T-8）：既有库 `snapshots` 为空时 v5 迁移 DROP+CREATE 成功且新 PK `(ticker,ts)` 生效；若（异常）`snapshots` 非空则迁移中止并报错，不静默丢数据。

**验收前提**：第 3/10 条依赖真实网络与交易时段，标记 `network`/`trading-hours`，UAT 在交易日盘中验一次；限频基准沿用 `max_per_minute=60`（同 V1.3 T-1 约定）。第 9/13/15/16 条使用可注入时钟/monkeypatch，不依赖真实环境。

---

## 11. 优先级与排期建议

| 优先级 | 范围 | 说明 |
|---|---|---|
| **P0** | FR-1 目录中枢 + `CacheCatalogService.record_coverage` + FR-2.1/2.3（分钟/实时入库）+ FR-3/FR-4/FR-5/FR-6/FR-8 联动与看板切换 + FR-7.1/7.2/7.5/7.6 宇宙收敛与实时增量 | 直接回应"扩展数据类型 + 与看板联动"核心诉求；改动集中于 `DataCacheService`/`CacheCatalogService` + `cache_catalog` + `quote_callbacks` + `auto_load_service` + schema v5 |
| **P1** | FR-2.4 复权因子 + 看板涨跌幅口径统一（bars_daily.adj_factor 联动） | 数据完整性 / 收益计算正确性 |
| **P2** | FR-2.2 多周期分钟 + FR-2.5 财务入库 + 看板财务徽标 | 分析页复用，看板不强依赖 |

估算：P0 ≈ 5.5 人日（含 `cache_catalog` 写入事务改造/共享 `record_coverage`、看板三联动、实时源切换、进程内实时刷新守护线程、存量 `watchlist` pruning、schema v5 + 存量用例改写）、P1 ≈ 2.5 人日、P2 ≈ 2 人日（含测试）。

---

## 12. 风险与待确认问题

| # | 风险/问题 | 建议 |
|---|---|---|
| 1 | 实时快照频率/限速：akshare 实时接口有频限，`max_per_minute=60` 下全市场快照不可行 | 实时增量**只覆盖自动加载宇宙（通常数十~数百只）**，单轮批量拉取受 RateLimiter 约束；超出预算分轮（同 V1.3 增量续接） |
| 2 | 分钟线数据量远大于日线：全市场分钟历史会撑爆存储 | 严格窗口缓存（默认 T-60 交易日），不做全市场分钟历史；窗口参数可配置 |
| 3 | 复权口径一致性：引入 `adj_factors` 后，日线展示也要同步切换前/后复权，否则看板与回测口径打架 | P1 统一全局复权开关；`bars_daily.adj_factor` 现状恒 1.0（未复权），新口径上线前保持日线未复权展示，避免静默错误 |
| 4 | `bars_minute` 主键未含 `period`，多周期会有键冲突（D-3 已澄清：P0 不扩主键） | 本期仅写默认 5m；多周期（P2）再 ALTER 复合主键，迁移前由应用层 `INSERT OR REPLACE` 去重兜底 |
| 5 | 看板 `data/watchlist.json` 与新增 `cache_catalog` 双源，易不一致 | 看板读写统一收敛到 `_save_watchlist/_load_watchlist`（已存在），新增"加入看板"动作只走这一处；后续版本可迁库 |
| 6 | `snapshots` 原 `id BIGINT PRIMARY KEY` 无法支撑按标的幂等更新（**D-1 已解决**） | v5 将 `snapshots` 主键改为 `(ticker, ts)` 并去掉 `id` 列（§7.4）；实时刷新按 `(ticker,ts)` `INSERT OR REPLACE`，无需 id 生成策略 |
| 7 | 自动加载宇宙扩展后，用户看板膨胀会拉长加载时间（**D-4 已通过 `auto_load_enabled` 收敛**） | 加载计划（FULL/GAP/SKIP）天然跳过已新鲜标的；实时增量独立于日线补齐，互不阻塞；`auto_load_enabled` 默认仅看板自选纳入，一次性获取不自动纳入 |
| 8 | 存量 `bars_minute`/`snapshots` 为空表，既有 `test_*` 不涉及，但 v5 迁移需兼容既有库（**D-1/T-7 已明确空表守卫**） | `bars_minute` 用 `ADD COLUMN IF NOT EXISTS`；`snapshots` 迁移前断言为空再 DROP+CREATE，非空中止报错（验收 14/17） |
| 9 | 实时快照落库 `change_pct` 与读时计算口径可能漂移（盘中 `pre_close` 固定为昨收） | `change_pct` 落库时严格用 `snapshots.pre_close`（接口返回的前收），与盘口一致 |
| 10 | 进程内实时刷新守护线程与 V1.3 自动加载线程、Dash 请求线程的并发写 | 三者均走 `DuckDBManager` 单写连接串行化（FR-1.7），无独立写连接；线程启停随应用生命周期，非交易时段挂起而非退出 |

---

## 13. 三方评审意见清单与处理结果（2026-07-28）

### 13.1 研发视角（D）

| # | 意见 | 结论 | 落点 |
|---|---|---|---|
| D-1 | `snapshots` 现有 `id BIGINT PRIMARY KEY` 无法支撑"按标的 upsert"，原 PRD 只说"ALTER ADD change_pct"未解决主键矛盾 | ✅ 已修订 | §7.4：`snapshots` 主键改为 `(ticker,ts)` 并去掉 `id`；实时刷新按 `(ticker,ts)` `INSERT OR REPLACE`；风险 #6 标注已解决 |
| D-2 | `cache_catalog` 写入与各类数据写库的事务边界未定义，易漂移（"数据写了、目录没更"或反之） | ✅ 已修订 | 新增 FR-1.6（统一 `record_coverage` 辅助函数，所有写入方在同一 `transaction()` 内调用）、FR-1.2 明确同事务、验收 13 定义回滚注入测试 |
| D-3 | FR-2.1 同时写"增加 period 列"与"主键扩展为复合键"，与 §7.4"暂不 ALTER 主键"自相矛盾 | ✅ 已修订 | FR-2.1 删除"主键扩展"表述，明确 P0 仅写默认 5m、多周期推迟至 P2（风险 #4 同步澄清） |
| D-4 | 原"加载宇宙 = watchlist ∪ 全部 has_*=TRUE"会因一次性大批量获取把整库纳入每日自动加载、冲破限频 | ✅ 已修订 | 新增 `auto_load_enabled` 开关（FR-7.5、§7.1）；宇宙改为 `auto_load_enabled=TRUE`（FR-7.1）；"加入看板"置 TRUE、一次性获取默认 FALSE；指标表增"自动加载宇宙规模" |
| D-5 | 盘中实时刷新承载机制未定义（Dash `Interval` 不适合常驻轮询且会随页面关闭停止） | ✅ 已修订 | 新增 FR-7.6：进程内守护线程 + 交易时段门控，复用 `check_trading_hours`，与自动加载线程共用单写连接；风险 #10 补并发说明 |
| D-6 | 未约束 `cache_catalog` 写入连接，可能重现 V1.3 前"独立连接争锁重建空库"回归 | ✅ 已修订 | 新增 FR-1.7：所有 catalog 写仅经 `DuckDBManager.write_connection`，禁独立 `duckdb.connect` 写连接 |

### 13.2 设计视角（U）

| # | 意见 | 结论 | 落点 |
|---|---|---|---|
| U-1 | FR-4.1 每行 4 个独立徽标占 4 列，看板 15 行将视觉过载 | ✅ 已修订 | FR-4.1 改为同一单元格内紧凑 icon-only 标记组（✓绿/✗灰，hover 出类型+边界）；目录页同款（FR-8.2） |
| U-2 | `?focus=` 不清除，用户手动刷新看板会反复置顶该行 | ✅ 已修订 | IC-1/IC-2 消费参数后 `replace` 清除 `?focus=`；FR-3.3/FR-4.2 同步 |
| U-3 | 缓存目录页新增"数据类型"筛选后，与原"市场"+文本筛选纵向堆叠拥挤 | ✅ 已修订 | §6：数据类型多选与"市场"下拉并排置于筛选行 |
| U-4 | 缓存删除当前**无任何确认**即执行（既有风险），PRD 未覆盖 | ✅ 已修订 | FR-8.3 要求"整行删除"与"按类型删除"均经 `dbc.Modal` 二次确认，危险按钮 `color="danger"`；§6 补边界交互 |
| U-5 | 实时 `volume` 与日线 `volume` 量纲（手/股）不同，看板"成交量"直接拼易误读 | ✅ 已修订 | §6 边界：成交量列统一标注单位（如"万手"），tooltip 给原始值 |

### 13.3 测试视角（T）

| # | 意见 | 结论 | 落点 |
|---|---|---|---|
| T-1 | 验收 13"同事务回滚"无可注入构造方式，难以断言 | ✅ 已修订 | 验收 13 明确定义：`monkeypatch` `record_coverage` 抛异常 → 断言数据行与目录覆盖度均回滚 |
| T-2 | FR-6.2 降级路径无单元可测用例，易回归 | ✅ 已修订 | 新增验收 15：构造 `snapshots` 空 → 断言日频降级 + `daily_fallback` 标记 + `text-warning` 徽标，不依赖网络 |
| T-3 | 验收 9"连续运行超 60 天"不可自动化 | ✅ 已修订 | 验收 9 改为可注入 `now`/`minute_window_days` 判定窗口，构造越界数据验证清理，同 V1.3 FR-1.7 |
| T-4 | IC-3 只约束"新增"路径，既有 `watchlist.json` 里的死标的不会被清掉 | ✅ 已修订 | 新增 FR-5.3（启动/首次加载 pruning 存量 watchlist）+ 验收 16（构造 3 死标 → 断言清零 + `watchlist_pruned` 埋点） |
| T-5 | 验收 12 幂等未指明各表 | ✅ 已修订 | 验收 12 枚举五张目标表（`bars_daily`/`bars_minute`/`snapshots`/`adj_factors`/`financials`）分别断言行数不变 |
| T-6 | `financials` 指标未预定义，"抽取关键指标"实现时易各填各的 | ✅ 已修订 | FR-2.5 明确"预定义指标集（营收/归母净利/ROE/资产负债率等），P2 实现前固化清单" |
| T-7 | `snapshots` DROP+CREATE 若遇非空会静默丢数据 | ✅ 已修订 | §7.4 + 风险 #8：迁移前断言为空，非空则中止报错；新增验收 17 覆盖空/非空两分支 |
| T-8 | 实时刷新守护线程（D-5）缺并发与生命周期测试指引 | ✅ 已修订 | 风险 #10：三写方共用 `DuckDBManager` 单写连接串行化；建议 T 增"线程启停随应用生命周期、非交易时段挂起"用例 |

---

## 14. 流转提醒（按项目流程）

- 本 PRD 评审后建议：上传项目资料库归档；将 P0/P1/P2 拆为研发子事项并附本 PRD。
- schema v5 迁移涉及存量库（已有 `bars_minute`/`snapshots`），请数据负责人确认迁移窗口；`snapshots` 非空属异常场景，迁移脚本须显式报错而非静默。
- 验收第 3/10 条依赖真实网络与交易时段，UAT 安排在交易日盘中验证一次；限频基准同 V1.3 T-1 约定。第 9/13/15/16 条使用可注入时钟/monkeypatch，纳入 CI 门禁。
