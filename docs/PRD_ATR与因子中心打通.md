# 产品需求文档（PRD）：ATR 波动率因子落地与因子计算中心打通

| 项 | 内容 |
|---|---|
| 文档名称 | ATR 波动率因子落地与因子计算中心打通 |
| 版本 | v1.1（评审修订稿） |
| 创建日期 | 2026-07-30 |
| 角色 | 产品经理（需求方） / 研发（承接方） / 测试（验收） |
| 关联系统 | FisherQuant 因子计算中心（`factor_center`）、因子引擎（`fisher/factor/`） |
| 文档状态 | 评审通过 → 开发中 |

---

## 0. 评审与改进记录（开发 / 设计 / 测试）

> 2026-07-30 三方评审结论：PRD 主体成立，但存在 11 处需修订点，已在对应需求中同步更新（标注【修订】），并据此生成实现任务。

### 0.1 开发视角
- **D1 复权数据在独立表**：`adj_factors`（`adj_type='qfq'`）与行情表分离，`compute_factors` 当前查询不含该列；ATR 前复权须按 `ticker + trade_date` LEFT JOIN，缺失则降级不复权（对应 R1）。→ 见 FR-6【修订】。
- **D2 两套存储矛盾**：`FactorEngine.factor_cache`（DuckDB）与回调实际使用的 `FactorStorage`（parquet）是两套存储，NFR-2"复用 factor_cache" 与现状矛盾；v1 以 `FactorStorage` 为预览/导出唯一来源。→ 见 NFR-2【修订】。
- **D3 注册注入点**：`register_all_factors()` 应在 `fisher/dash_app/app.py` 应用构造**之前**调用（布局构建早于回调注册，须先注册，否则 UI 状态判断全灰），且幂等。→ 见 FR-1【修订】。
- **D4 参数不可配**：现有 `Factor.compute(df)` 不接受参数，计算回调也未传 `default_params`，"period 在线可配"不可达；v1 将 `period` 固为类常量 14，"在线改参"列为后续。→ 见 FR-5【修订】。
- **D5 分钟线无入口**：`compute_factors` 硬编码 `bars_daily`，FR-7 需新增频率选择（日线 / 分钟线 + 周期）+ `bars_minute` 查询 + 按日期 JOIN 复权。→ 见 FR-7【修订】。

### 0.2 设计视角
- **S1 FR-4 自相矛盾**："列表改读 `list_all()`" 与 "未实现灰显" 冲突——只读注册表就看不到未实现项。改为：以 `FACTOR_DEFINITIONS` 为目录，渲染时按注册状态标注（已注册=可用；未注册=灰显禁用+"未实现"）。→ 见 FR-4【修订】。
- **S2 分类中英文不一致**：注册表 `category` 为英文（technical/price/volatility），UI 目录用中文（技术指标/均线/波动率）；v1 在 UI 目录层做中文分类映射，不依赖注册表英文 `category`。→ 见 FR-4【修订】。
- **S3 缺描述**：注册表 `Factor` 无 `description`；列表描述继续由 `FACTOR_DEFINITIONS` 提供，不依赖注册表。

### 0.3 测试视角
- **T1 正确性参照须明确**：v1 采用**简单滚动均值**，参照用 pandas `rolling(period).mean()`，断言 `±1e-6`；Wilder 平滑列为后续开关。→ 见第 6 节【修订】。
- **T2 补充具体单测清单**：见 §7.1。
- **T3 回归防护**：增加"注册后既有因子冒烟测试"，确保 MACD/RSI/Bollinger 等仍可用。

---

## 1. 背景与问题陈述（Background & Problem）

### 1.1 业务背景
ATR（Average True Range，平均真实波幅）是 Wells Wilder 于 1978 年提出的经典波动率指标，核心用途：
- **仓位管理**：按 ATR 设定单笔止损距离（如 2×ATR 止损），实现波动率自适应仓位。
- **止盈/止损绘制**：吊灯止损（Chandelier Exit）、移动止盈线的标准输入。
- **波动率突破策略**：唐奇安通道、波动率突破系统的波动性伸缩因子。
- **风险预警**：识别标的日内波动异常放大的交易日。

作为量化研究平台，FisherQuant 的"因子计算中心"已在 UI 规划 ATR（`FACTOR_DEFINITIONS` 中 `name=atr`，`category=波动率`，`default_params={"period":14}`），但当前无法计算。

### 1.2 当前问题（已实证）
1. **因子注册表为空**：`FactorRegistry` 提供 `register()`，但全代码无任何调用。实测 `list_all()` 返回 `[]`，`get("atr")` 抛 `KeyError`。
2. **已实现因子未接入**：`MACD`/`RSI14`/`BollingerBands`（technical.py）及 `Momentum20D`/`Momentum60D`/`Volatility20D`/`Volatility60D`/`Turnover5D`/`Turnover20D`/`VolumeRatio`（price.py）共 **10 个 Factor 类已编写**，但均未被注册，计算时同样 `KeyError`。
3. **UI 与计算层脱节**：`factor_center.py` 的 `FACTOR_DEFINITIONS` 是写死的展示清单（18 项），与真实 Factor 类无映射；"因子计算"点击会因 `FactorRegistry.get` 失败逐条报错。
4. **ATR 无实现类**：`fisher/factor/` 下不存在 `atr` 相关类。

**结论**：ATR 当前完全不可计算，且因子中心整体处于"展示可用、计算不可用"的瘫痪状态。要支持 ATR，须先把**因子注册/计算链路打通（P0）**，再**实现 ATR 类（P1）**。

---

## 2. 目标与范围（Goals & Scope）

### 2.1 目标
- **G1（P0 基础）**：打通"因子注册 → 计算 → 存储 → 预览"全链路，使已实现的 10 个因子可被 UI 正常调用计算。
- **G2（P1 核心）**：实现 `Atr` 波动率因子（日线 + 分钟线），接入注册表与因子中心，默认周期 14。
- **G3（体验）**：因子列表/下拉按真实注册状态标注，未实现因子灰显禁用并标"未实现"，杜绝误操作。
- **G4（数据正确性）**：ATR 基于**前复权价**计算，避免除权除息造成 TR 异常跳变。

### 2.2 范围
- **范围内**：因子注册装配、`Atr` 因子类（日线/分钟线）、UI 真实态、复权处理、频率选择、单测、预览联调。
- **范围外（本期不做）**：因子参数在线编辑 UI、因子批量调度/定时任务、因子在回测引擎内直接调用、其他波动率因子（Parkinson / Garman-Klass / Yang-Zhang）扩展、分钟线与日线因子结果的并存存储（v1 同一标的因子文件按列覆盖，见 R4）。

---

## 3. 现状技术盘点（Current State，附代码定位）

| 层 | 现状 | 代码位置 | 结论 |
|---|---|---|---|
| 数据层·日线 | `bars_daily` 含 `open/high/low/close/volume/amount/market/adj_factor` | `fisher/store/schema.py:138` | ✅ 支持 ATR |
| 数据层·分钟线 | `bars_minute` 含 `open/high/low/close/volume/amount/market/period` | `fisher/store/schema.py:153` | ✅ 支持 ATR（多周期） |
| 复权数据 | `adj_factors(ticker, trade_date, adj_type, adj_factor)`，含 `qfq`/`hfq` | `schema.py:70` | ✅ 可用于前复权（需 JOIN） |
| 因子基类 | `Factor` ABC：`name`/`category`/`output_columns`/`compute` | `fisher/factor/base.py` | ✅ 可用 |
| 注册表 | `FactorRegistry`：`register/get/list_all/list_by_category` | `fisher/factor/registry.py` | ⚠️ 可用但无人 `register` |
| 计算引擎 | `FactorEngine.compute` 调 `FactorRegistry.get`，含 `factor_cache` 缓存 | `fisher/factor/engine.py` | ⚠️ 链路 OK，但回调未走此路径 |
| 已实现因子 | MACD/RSI14/BollingerBands；Momentum/Volatility/Turnover/VolumeRatio | `technical.py`/`price.py` | ⚠️ 已实现但未注册 |
| UI 因子清单 | `FACTOR_DEFINITIONS` 写死 18 项，含 `atr`（仅占位） | `factor_center.py:24` | ⚠️ 与实现脱节 |
| 计算回调 | `compute_factors` → `FactorRegistry.get(fname)` → `KeyError` | `factor_callbacks.py:87` | ❌ 全部失败 |
| ATR 实现 | 无 | — | ❌ 缺失 |

**数据结构证据（schema.py）**：
```sql
CREATE TABLE bars_daily (
  open DOUBLE NOT NULL, high DOUBLE NOT NULL, low DOUBLE NOT NULL,
  close DOUBLE NOT NULL, ..., adj_factor DOUBLE DEFAULT 1.0, ...
);
CREATE TABLE bars_minute (
  open DOUBLE NOT NULL, high DOUBLE NOT NULL, low DOUBLE NOT NULL,
  close DOUBLE NOT NULL, ..., period VARCHAR DEFAULT '5', ...
);
CREATE TABLE adj_factors (
  ticker VARCHAR, trade_date DATE, adj_type VARCHAR, adj_factor DOUBLE,
  PRIMARY KEY (ticker, trade_date, adj_type)   -- adj_type ∈ {qfq, hfq}
);
```

---

## 4. 用户与场景（Users & Scenarios）

| 角色 | 场景 | 诉求 |
|---|---|---|
| 量化研究员 | 在因子中心选标的 + ATR（可选日线/分钟线），一键计算并预览/导出 ATR 序列 | 快速得到可用波动率序列用于止损线设定 |
| 策略开发者 | 编写策略时引用 ATR 数值 | 因子数据可查、可导出（策略内联调用留待后续） |
| 风控人员 | 观察标的 ATR 走势 | 识别波动率异常放大的交易日并预警 |

---

## 5. 功能需求（Functional Requirements）

### P0 — 因子注册与计算链路打通
- **FR-1 注册装配【修订】**：新增 `fisher/factor/__init__.py::register_all_factors()`，导入并注册 `technical.py` 与 `price.py` 的 10 个类 + 新增 `Atr`。**注入点：`fisher/dash_app/app.py` 在 `app.layout = create_layout()` 之前调用一次**（保证布局构建时注册表已就绪，见 D3）；函数幂等。
- **FR-2 注册自检**：`register_all_factors()` 后 `FactorRegistry.list_all()` 非空；可作为测试守卫（TC-1）。
- **FR-3 计算链路验证**：`factor_callbacks.compute_factors` 经 `FactorRegistry.get` 成功取实例并计算；成功结果写入 `FactorStorage`，失败因子在状态区明确报错（现有 catch 保留）。
- **FR-4 UI 真实态【修订·解决 S1/S2】**：以 `FACTOR_DEFINITIONS` 为因子目录（含中文分类/描述），渲染时按 `FactorRegistry` 标注实现状态——已注册因子正常展示、可选；未注册（未实现）因子行灰显、计算下拉中 `disabled` 并标注"未实现"。分类展示用目录内中文 `category`，不依赖注册表英文 `category`。

### P1 — ATR 波动率因子
- **FR-5 实现 `Atr(Factor)`【修订·D4/T1】**：
  - `name="atr"`，`category="volatility"`，默认周期由类常量 `default_period=14` 提供（v1 不做在线改参 UI，"参数可配置"列为后续）。
  - 计算：`TR = max(H−L, |H−preC|, |L−preC|)`；`ATR = TR.rolling_mean(period)`（**v1 简单滚动均值**，Wilder 平滑列为后续开关）。
  - `output_columns = ["atr", "tr"]`（输出 `tr` 便于校验）。
- **FR-6 复权处理【修订·D1】**：计算前按 `adj_factors`（`adj_type='qfq'`）对 OHLC 做前复权——`前复权价 = raw_price / qfq_factor`，并以最新日因子归一（使最新价=原始价）。计算查询通过 LEFT JOIN `adj_factors` 取得 `adj_factor` 列传入；若某标的缺 `adj_factors`（全 null），**降级为不复权计算并状态区告警**（R1），不阻断。
- **FR-7 多周期【修订·D5】**：ATR 计算逻辑对频率无感（仅依赖 OHLC+复权）。在"因子计算"页新增**频率选择**（日线 / 分钟线 + 分钟周期下拉）；`compute_factors` 据此查询 `bars_daily` 或 `bars_minute`，两类均按日期 LEFT JOIN `adj_factors(qfq)` 做前复权（分钟线按 `bar_time` 取日期）。
- **FR-8 注册与 UI**：`Atr` 注册后，UI"atr"项由灰显变为可用，计算回调自然支持（复用 FR-3 链路）。
- **FR-9 预览/导出**：因子预览页可展示 `atr`/`tr` 列；导出沿用既有因子导出能力（v1 预览/导出以日线为主，分钟线结果覆盖同标的因子文件，见 R4）。

### 非功能需求（NFR）
- **NFR-1 性能**：单标的 ATR 在内存 `polars.DataFrame` 完成；日线万级行 < 100ms，分钟线十万级行 < 500ms。
- **NFR-2 缓存【修订·D2】**：v1 以 `FactorStorage`（parquet，按标的）作为计算结果的预览/导出唯一来源，与现有架构一致；`FactorEngine.factor_cache`（DuckDB）另一套缓存本期不接入，列为后续性能优化（避免双写不一致）。
- **NFR-3 可测试**：ATR 有独立单测（公式、滚动均值参照、首值 `null`、除权连续性、缺复权降级、参数常量）。
- **NFR-4 兼容性**：不破坏现有 MACD/RSI/Bollinger；不动 `bars` 表结构；注册幂等。

---

## 6. ATR 计算规格（Specification）【修订·T1】

**公式**
```
TR_t = max(H_t − L_t, |H_t − C_{t-1}|, |L_t − C_{t-1}|)
ATR_t = mean(TR_{t−period+1} … TR_t)            # 【v1】简单滚动均值（参照 pandas rolling(period).mean()，AC-3 据此断言）
        # 后续开关：Wilder 平滑 ATR_t = (ATR_{t-1}·(period−1) + TR_t) / period
```

- **前复权**：`qfq_factor = raw_close / qfq_close`（来自 `adj_factors.adj_type='qfq'`）。`前复权价 = raw_price / qfq_factor`，再除以「最新日 qfq_factor / 最新日 raw」归一，使最新价=原始价、历史价向下调整。ATR 在 前复权 OHLC 上计算，避免除权缺口造成 TR 虚假放大。
- **输入列**：`open`/`high`/`low`/`close`（+ 计算查询注入的 `adj_factor`）。
- **输出列**：`atr`（DOUBLE）、`tr`（DOUBLE，便于校验）。
- **参数**：`period`（v1 固定 14，见 D4）。
- **边界**：前 `period−1` 行为 `null`（首值不足窗口）。

---

## 7. 验收标准（Acceptance Criteria）
- **AC-1**：`register_all_factors()` 后 `FactorRegistry.list_all()` 含 macd/rsi_14/bollinger/momentum_20d/60d/volatility_20d/60d/turnover_5d/20d/volume_ratio/atr（**≥ 11 项**）。
- **AC-2**：因子中心"因子计算"对任一已注册因子计算成功，预览页可见对应因子列。
- **AC-3**：ATR 计算结果与 pandas 参照（`tr.rolling(period).mean()`）在 `±1e-6` 内一致；含一个除权日样例中 ATR 无异常跳变。
- **AC-4**：未实现因子（如 `sma_5`/`ema_12`/`volume_sma`）在 UI 列表灰显、计算下拉 `disabled` 并标"未实现"。
- **AC-5**：单测全部通过（见 §7.1）。

### 7.1 单测清单（T2 / T3）
- **TC-1** `register_all_factors()` 后 `list_all()` 含 macd/rsi_14/bollinger/atr 等 ≥ 11 项（FR-2 守卫）。
- **TC-2** 各已注册因子冒烟：样例 OHLC DataFrame 上 `compute` 不抛错且产出 `output_columns`（防回归）。
- **TC-3** ATR 公式：合成 OHLC，断言 `tr == max(H−L, |H−preC|, |L−preC|)`。
- **TC-4** ATR 滚动均值：断言 `atr` 与 pandas `tr.rolling(period).mean()` 一致（±1e-6）。
- **TC-5** 边界：前 `period−1` 行 `atr`/`tr` 为 `null`。
- **TC-6** 除权日连续性：构造一日 `adj_factor` 突变，断言 ATR 无异常跳变（对比不复权基线）。
- **TC-7** 缺复权降级：无 `adj_factor` 列时不抛错，退化为不复权（R1）。
- **TC-8** UI 状态映射：`FACTOR_DEFINITIONS` 中 `atr` 标"可用"、`sma_5` 等未实现项标"未实现"（FR-4）。

---

## 8. 里程碑与排期（建议）
- **M1（P0，约 0.5 人天）**：`register_all_factors` + app.py 启动装配 + UI 真实态 + 联调已注册因子。
- **M2（P1，约 0.5~0.8 人天）**：`Atr` 类实现（日线+分钟线+前复权）+ 频率选择 UI/回调 + 单测 + 预览/导出联调。
- **合计约 1~1.3 人天。**

---

## 9. 风险与依赖（Risks & Dependencies）
- **R1 复权因子缺失**：部分标的 `adj_factors` 为空，ATR 退化为未复权计算并在状态区告警（不阻断）。
- **R2 历史回滚风险**：此前曾因版本回滚误删功能，需通过单测 + "启动自检"防回归。
- **R3 性能**：分钟线数据量大，ATR 计算须 `polars` 向量化（现有技术栈已满足）。
- **R4 分钟/日线因子共存**：v1 同一标的因子文件（`data/factors/<symbol>/factors.parquet`）按列覆盖，先算日线 ATR 再算分钟线 ATR 会相互覆盖；v1 以日线为主、分钟线为辅，并存存储列为后续。

---

## 10. 成功指标（Success Metrics）
- 因子中心"计算成功率"从 **0% → 100%**（已注册因子）。
- 用户可计算因子数量从 **0 → ≥ 11**。
- ATR 上线后被策略/风控引用次数（后续埋点）。

---

## 附录 A：因子实现状态清单（本期目标）

| 因子 | 实现类 | 现状 | 本期 |
|---|---|---|---|
| macd | `MACD` | 已实现未注册 | ✅ 注册可用 |
| rsi_14 | `RSI14` | 已实现未注册 | ✅ 注册可用 |
| bollinger | `BollingerBands` | 已实现未注册 | ✅ 注册可用 |
| momentum_20d / 60d | `Momentum20D` / `Momentum60D` | 已实现未注册 | ✅ 注册可用 |
| volatility_20d / 60d | `Volatility20D` / `Volatility60D` | 已实现未注册 | ✅ 注册可用 |
| turnover_5d / 20d | `Turnover5D` / `Turnover20D` | 已实现未注册 | ✅ 注册可用 |
| volume_ratio | `VolumeRatio` | 已实现未注册 | ✅ 注册可用 |
| **atr** | `Atr`（新增） | **缺失** | ✅ 新增实现 |
| sma_5/10/20/60、ema_12/26、volume_sma、momentum/volatility/turnover 外 | — | 无实现类 | 灰显"未实现"（后续） |
