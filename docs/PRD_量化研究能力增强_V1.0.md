# PRD · 量化研究能力增强 V1.0

> **立项视角**：量化研究员（需求提出）→ 产品经理（本文档整理）
> **关联文档**：`PRD_量化系统能力补齐_对照必备功能清单_V1.0.md`（P0 已交付；其 G5 K线合成 / G6 截面因子 / G7 策略生命周期为并行在办项，本文不重复，仅在 G2、G7 处交叉引用）
> **适用系统**：`fisherquant`（Python Dash + duckdb/polars；回测 `BacktestEngine`、仿真 `PaperEngine`、事前风控 `RiskEngine`、实时风控 `RealtimeRiskMonitor`、因子 `FactorEngine`）

---

## 1. 背景与目标

### 1.1 量化研究员的原话（需求备忘录，产品经理整理为 PRD）

> 系统当前回测/仿真链路在生产可用性上已经不错：单一账本 NAV、T+1 解冻、下单前风险预检、涨跌停封板建模、滑点、完整费用模型（含印花税单边）、Brinson 归因、Walk-forward + Deflated Sharpe 过拟合防护都已具备。但站在**研究有效性**角度，有 8 类问题会直接污染研究结论，必须补齐：
>
> 1. **前视偏差（最高危）**：因子在回测里是"整段历史一次性算完"再喂给策略的，`FactorEngine.compute(df)` 与 `AlphaModelStrategy.set_factor_scores` 没有"仅用截至当前 bar 的数据"的约束。bar *t* 的信号可能用到 bar *t+1* 之后的信息，结论不可信。
> 2. **因子无法被验证**：能算出 MACD/RSI/布林，但没有 IC / RankIC / ICIR / 衰减 / 换手 / 市值行业中性化，研究者无法判断一个因子到底有没有用。
> 3. **组合优化太薄**：只有等权 / 风险平价(ERC) / 分数凯利，没有均值-方差、最小方差、最大夏普，也没有协方差估计（EWMA / 收缩）和再平衡调度。
> 4. **参数靠拍脑袋**：Walk-forward 能评估，但没有"搜索参数"的能力，最优因子窗口、top_k、权重都是硬编码，过拟合防护形同摆设。
> 5. **成本模型偏乐观**：滑点是固定 bps，没有成交量冲击（平方根模型）、买卖价差、参与率(POV)建模，大单成本被严重低估。
> 6. **风险分析只有 VaR/β/MDD**：缺 CVaR(ES)、参数法 VaR、压力测试、行业/风格暴露与集中度(HHI)、流动性风险、盘后风险报告。
> 7. **幸存者偏差**：成分股是"当前快照"，回测历史上包含了已退市股票的未来信息；停牌服务有了，退市处理还没有，没有 point-in-time 股票池。
> 8. **绩效指标缺几块**：没有 Calmar、回撤时长/恢复、偏度峰度、滚动夏普、单笔交易统计（期望收益、盈亏比）。

### 1.2 目标

把 `fisherquant` 从"能跑回测"升级为"研究结论可信、可解释、可优化"的量化研究平台。本 PRD 聚焦**研究方法的严谨性**，不新增实盘/行情接入（见 §3 范围边界）。

### 1.3 量化成功指标

- **R1（零前视）**：在相同数据上，开启/关闭 point-in-time 因子计算，NAV 与交易序列必须不同；新增回归测试断言"bar *t* 的因子值不使用 bar *t* 之后的任何输入"。
- **R2（因子可证伪）**：任意已注册因子可在 ≤2 行调用下产出 IC/RankIC/ICIR/衰减曲线/换手率报告。
- **R3（优化可复现）**：参数搜索以 walk-forward DSR 为目标，固定随机种子后结果可复现（复用 `repro.set_global_seed`）。
- **R4（成本不乐观）**：大单（>20% 当日成交量）在冲击模型下的成交成本显著高于固定 bps。
- **R5（风险可读）**：盘后风险报告覆盖 VaR/CVaR/β/暴露集中度/最大回撤，且单测覆盖核心分支。

---

## 2. 范围边界

### 2.1 In-scope（可在现有架构内闭环）
- 因子 point-in-time 计算与回测前视护栏（G1）
- 因子验证分析框架（G2）
- 组合优化器与再平衡（G3）
- 参数/超参搜索（G4）
- 增强成本与市场冲击模型（G5）
- 进阶风险分析（G6）
- 幸存者/成分股偏差控制（G7）
- 绩效指标补全（G8）

### 2.2 Out-of-scope（确需实盘/外部数据，本 PRD 不承接）
- 实盘券商接入（`broker/live.py` 仍为 `NotImplementedError` 占位）—— 见能力补齐 PRD 范围说明。
- 实时 tick 流与高频回测（当前为日频/bar 级事件驱动）。
- 基本面/财务数据抓取管道建设（依赖 `akshare` best-effort，仅做消费侧接口）。
- K线合成引擎、截面因子原始值计算、策略生命周期——由能力补齐 PRD 的 G5/G6/G7 在办，本文 G2 专注"因子验证"、G7 专注"成分股时点"做补强，不重复实现因子本身。

---

## 3. 现状盘点（已具备，避免重复建设）

| 能力 | 位置 | 备注 |
|---|---|---|
| 事件驱动回测 + N+1 成交延迟 | `backtest/engine.py` | 成交流程无前视 |
| T+1 解冻 / 可用持仓校验 | `backtest/engine.py` `position/service.py` | ✅ |
| 事前风控（10 条规则） | `risk/pre_trade.py` `risk/factory.py` | ✅ |
| 停牌过滤 | `market/suspension.py` + `BacktestEngine.suspension_provider` | ✅ |
| 滑点 + 涨跌停封板 + 成交量约束 | `paper/fill.py` `FillSimulator` | 滑点为固定 bps |
| 完整费用（佣金/印花单边/过户/规费） | `paper/fees.py` | ✅ |
| 绩效指标（夏普/索提诺/MDD/β/α/IR/PSR/DSR/费率拖累） | `analytics/performance.py` | 缺 Calmar/回撤时长/单笔 |
| 因子引擎 + 注册表 + 缓存 | `factor/engine.py` `registry.py` `storage.py` | 无 PIT、无验证 |
| 组合方法（等权/ERC/分数凯利） | `portfolio/methods.py` | 无最优化 |
| 实时风险（历史 VaR/β/MDD） | `risk/realtime.py` | 缺 CVaR/压力/暴露 |
| Brinson 归因 | `analytics/attribution.py` | 行业层面 ✅ |
| Walk-forward + DSR 过拟合防护 | `strategy/walk_forward.py` | 仅评估，不搜索 |
| Pipeline YAML → 多因子线性模型 | `strategy/pipeline.py` | 权重需外部给定 |

---

## 4. 需求分组

### G1 · 因子 Point-in-Time 计算与前视护栏（P0）
**问题**：`FactorEngine.compute(df)` 对整段 `df` 一次性计算；`AlphaModelStrategy` 通过 `set_factor_scores` 接收"全历史算好"的分数。回测驱动若一次性喂全量分数，则 bar *t* 信号实质用到了未来数据 → 前视偏差，研究结论不可信。

**需求**
1. `FactorEngine` 增加 `compute_point_in_time(df, as_of_date, date_col="trade_date")`：仅用 `trade_date <= as_of_date` 的行计算因子，结果与整段计算在截至该日处一致（验证无泄漏）。
2. `compute` 增加 `lookahead_guard: bool = True`：当调用方传入的 `df` 包含晚于 `as_of_date`（或当前处理日）的行时，记录/抛出 `LookaheadWarning`，默认开启。
3. 在回测/研究驱动侧提供统一入口 `FactorResearch.run_cross_sectional(universe, factors, end_date)`，按 bar 推进、逐日调用 PIT 因子，保证 `set_factor_scores` 只含截至当日数据。
4. 提供 `assert_no_lookahead(factor, df)` 测试辅助：断言"用全量数据计算的因子值 == 用截至第 t 日数据计算的因子值（对齐 t 之前）"，用于回归护栏。

**AC-G1.1**：固定一只标的、一段含未来的数据，对 `compute`（整段）与 `compute_point_in_time(as_of=第 t 日)` 在 `t` 之前的值逐点相等；`t` 之后 `compute` 有值、`PIT` 为 null。
**AC-G1.2**：开启 `lookahead_guard` 且传入含未来行的 `df` 时，触发 `LookaheadWarning`（不崩溃，可计数）。
**AC-G1.3**：新增回测回归：同一策略，开启 PIT 前后 NAV/成交序列不同（证明护栏生效），且开启后指标下降或持平（无"未来函数"抬升）。
**AC-G1.4**：`assert_no_lookahead` 对 MACD/RSI/布林通过。

### G2 · 因子验证分析框架（P1，补强能力补齐 PRD 的 G6 截面因子）
**问题**：能算出因子值，但无法判断因子是否有效、是否稳定、是否换手过高、是否受市值/行业干扰。

**需求**
1. `factor/analytics.py` 新增：
   - `information_coefficient(factor_series, forward_return, method="pearson"|"spearman")` → IC；`rank_ic` 默认 spearman。
   - `icir(ic_series)` = mean(IC)/std(IC)（时序）。
   - `factor_decay(factor_series, forward_return, lags=20)` → 各滞后阶 IC，输出衰减曲线数据。
   - `factor_turnover(factor_panel, dates)` → 日度因子值自相关/换手率。
   - `neutralize(factor_series, style_cols, industry_cols, method="ols"|"rank")` → 市值/行业中性化后的纯净因子。
   - `zscore_cross_section(factor_panel, by_date=True)` → 截面 z-score 标准化。
2. `FactorValidator.validate(factor_name, panel, forward_returns)` 输出结构化报告：`{ic_mean, ic_std, icir, ic_positive_ratio, half_life, turnover, neutralized_ic}`。
3. 与 `FactorEngine` 缓存打通：验证结果可落 `factor_cache` / `FactorStorage`，复用现有存储。

**AC-G2.1**：对一个已知单调有效的合成因子，`validate` 给出 IC>0、ICIR>0.5、正相关占比>60%。
**AC-G2.2**：`neutralize` 后因子的市值/行业暴露（与市值/行业的截面相关）显著下降（|ρ|<0.1）。
**AC-G2.3**：`factor_decay` 在滞后 1~5 阶 IC 单调下降，half_life 有值。
**AC-G2.4**：所有函数有单测，覆盖空值/全常量/单标的等边界。

### G3 · 组合优化器与再平衡（P1）
**问题**：现有 `methods.py` 仅等权/ERC/凯利，无均值-方差类优化与协方差估计，无法做风险预算约束下的最大化收益。

**需求**
1. `portfolio/optimizer.py` 新增（默认 long-only、可加杠杆开关）：
   - `mean_variance(mu, Sigma, risk_aversion, constraints)` → 最大效用权重。
   - `min_variance(Sigma, constraints)`。
   - `max_sharpe(mu, Sigma, rf, constraints)`。
   - 约束：单标的上限 `max_weight`、行业上限、L2 正则（`risk_aversion` 等效）、可选 `sum(w)=1`（不允许现金）或 `<=1`（保留现金）。
2. 协方差估计 `portfolio/cov.py`：
   - `ewma_cov(returns, span=60)`；
   - `shrunk_cov(returns, method="ledoit_wolf")` 基础收缩估计（不依赖 scipy，可用 numpy 实现）。
3. `portfolio/rebalance.py`：
   - `schedule_rebalance(current_w, target_w, method="periodic"|"threshold", threshold=0.05)` → 是否触发再平衡及调仓单。
   - 与 `PortfolioBuilder.build_orders` 衔接，复用风险预检。

**AC-G3.1**：`max_sharpe` 在给定 μ/Σ 下，夏普高于等权与 ERC（合成数据可证）。
**AC-G3.2**：`max_weight=0.1` 时，任一权重不超过 0.1。
**AC-G3.3**：`shrunk_cov` 输出为对称半正定矩阵；与样本协方差差异在合理范围。
**AC-G3.4**：`schedule_rebalance(threshold)` 在权重漂移 > 阈值时返回需调仓，否则空。

### G4 · 参数/超参搜索（P1）
**问题**：Walk-forward 能评估但参数靠硬编码；没有"搜索"使过拟合防护真正生效。

**需求**
1. `strategy/optimize.py`：
   - `grid_search(space, objective_fn, n_jobs=1)`、`random_search(space, n_iter, objective_fn, seed)`。
   - `objective_fn` 默认封装 `walk_forward(..., n_trials=...)` 的 `deflated_sharpe_ratio` 作为目标（缓解多重比较）。
2. 搜索空间声明：策略参数（因子窗口、top_k、模型权重）、组合方法（optimizer 类型、risk_aversion、max_weight）。
3. 输出：`best_params`、`cv_results`（每组的 train/test/DSR）、`overfit_report`（样本内 vs 样本外衰减）。
4. 复用 `repro.set_global_seed` 保证可复现（满足 R3）。

**AC-G4.1**：给定含噪声但存在真实最优窗口的合成问题，`grid_search` 能找回最优窗口附近。
**AC-G4.2**：`overfit_report` 同时给出样本内 DSR 与样本外 DSR；当样本外 << 样本内时标记"疑似过拟合"。
**AC-G4.3**：固定 seed 两次运行结果一致。

### G5 · 增强成本与市场冲击模型（P1）
**问题**：固定 bps 滑点低估大单成本，缺少买卖价差与参与率建模。

**需求**
1. `paper/impact.py` 新增（与 `FillSimulator` 解耦、可选装配）：
   - `sqrt_impact(participation_rate, adv, volatility, coeff)` → 平方根市场冲击成本（占价比）。
   - `bid_ask_cost(spread_bps)` → 价差成本。
   - `pov_slippage(order_qty, bar_volume, base_bps, impact_coeff)` → 参与率相关滑点。
2. `FillSimulator` 增加 `impact_model` 注入点：成交价 = raw_price × (1 ± (base_slippage + impact))，买 + 卖 −。
3. `FeeCalculator` 增加可选"按手收费"组件 `per_lot_fee`（A股部分券商/期货场景）。

**AC-G5.1**：参与率 20% 的冲击成本 > 参与率 1% 的冲击成本（R4）。
**AC-G5.2**：注入 `impact_model` 后，`check_fill` 成交价相对无冲击情形偏移方向正确（买更高、卖更低）。
**AC-G5.3**：`per_lot_fee` 组件在启用时叠加到 `total`。

### G6 · 进阶风险分析（P1）
**问题**：实时风控仅历史 VaR/β/MDD，缺尾部风险与暴露结构。

**需求**
1. `risk/analytics.py` 新增：
   - `cvar(returns, confidence=0.975)` → 期望短缺（历史分位均值）。
   - `parametric_var(returns, confidence, dist="normal"|"t")` → 参数法（t 用 `_norm_*` 风格近似或简易矩匹配）。
   - `stress_test(portfolio_returns, scenarios)` → 给定情景冲击（如沪深300 -7%、利率 +50bp、行业 β 冲击）下的组合损益。
   - `exposure_concentration(weights, sectors)` → 行业/风格暴露与 HHI 集中度。
   - `liquidity_risk(weights, adv, max_participation)` → 估算清仓所需天数/冲击。
2. `analytics/report.py` 增加 `post_trade_risk_report(nav_series, weights, sectors, benchmark)` 汇总 VaR/CVaR/β/暴露/MDD，输出 dict + 供前端展示的结构。

**AC-G6.1**：`cvar` ≥ `var`（同一置信度下 ES 不小于 VaR）。
**AC-G6.2**：`exposure_concentration` 单行业 100% 权重时 HHI=1；等权 10 行业时 HHI=0.1。
**AC-G6.3**：`stress_test` 在 -7% 市场冲击下组合损益为负且量级合理。
**AC-G6.4**：`post_trade_risk_report` 字段完整、单测覆盖。

### G7 · 幸存者/成分股偏差控制（P2，补强能力补齐 PRD G2 停牌）
**问题**：股票池为当前快照，回测历史上含已退市标的的未来信息；停牌有了，退市没有；无 point-in-time 成分股。

**需求**
1. `market/universe.py` 新增：
   - `PointInTimeUniverse`：`members_as_of(date)` 返回截至该日"在市且未退市"的成分股，剔除未来才上市/已退市的标的。
   - `add_delisted(ticker, delist_date)`、`is_listed(ticker, date)`。
2. 与 `SuspensionService` 协同：回测某日可用股票 = `members_as_of(date)` − `suspended(date)`。
3. 数据来源：`akshare` best-effort 拉取上市/退市日期，失败则降级为空（不影响回测，仅提示）。

**AC-G7.1**：给定"2020 上市、2023 退市"的标的，`members_as_of(2024)` 不含该标的，`members_as_of(2022)` 含。
**AC-G7.2**：`akshare` 不可用时返回空且不抛异常（降级）。

### G8 · 绩效指标补全（P2）
**需求**（均落入 `analytics/performance.py` / `stats.py`）
1. `calmar_ratio(nav, trading_days=252)` = 年化收益 / 最大回撤。
2. `drawdown_duration(nav)` → 最长水下时长（交易日）与恢复点。
3. `skew` / `kurtosis` 样本矩。
4. `rolling_sharpe(nav, window=60)` → 滚动序列。
5. 单笔交易统计：`trade_stats(trades)` → 平均盈/亏、期望收益、盈亏比、最大连胜/连亏。
6. 以上并入 `compute_all_metrics` 输出（向后兼容，新增 key）。

**AC-G8.1**：`calmar_ratio` 与手算一致；零回撤时返回 0 或 inf 不崩。
**AC-G8.2**：`trade_stats` 对含盈亏的 trades 给出正的期望收益口径正确。
**AC-G8.3**：`compute_all_metrics` 新增字段不破坏既有调用方。

---

## 5. 优先级汇总

| 编号 | 需求 | 优先级 | 依赖 |
|---|---|---|---|
| G1 | 因子 PIT + 前视护栏 | **P0** | 无 |
| G2 | 因子验证分析 | P1 | G1（验证基于 PIT 因子） |
| G3 | 组合优化器 + 再平衡 | P1 | 无（依赖 numpy，已用） |
| G4 | 参数/超参搜索 | P1 | G3（搜索组合方法）、walk_forward（已有） |
| G5 | 成本/冲击模型 | P1 | 无 |
| G6 | 进阶风险分析 | P1 | 无 |
| G7 | 幸存者/成分股控制 | P2 | `SuspensionService`（已有） |
| G8 | 绩效指标补全 | P2 | 无 |

**实施顺序建议**：G1 → G2 → (G3/G5/G6 可并行) → G4（依赖 G3）→ G7/G8。

---

## 6. 设计约束（非功能）

- **D1（研究可信优先）**：任何"因子计算/信号生成"入口默认开启前视护栏（G1），关闭需显式传参并留痕。
- **D2（可复现）**：所有随机过程（搜索、冲击模拟）走 `repro.set_global_seed`，满足 R3。
- **D3（不破坏现有回测）**：G1 默认行为变更后，全量回归 0 失败、NAV 数值在有 PIT 开关下仅因剔除前视而下降（不会"变好"）。
- **D4（依赖收敛）**：仅用已引入依赖（numpy/polars）；不引入 scipy/sklearn，统计函数自行实现（与 `performance.py` 的 `_norm_*` 一致风格）。
- **D5（可观测）**：G2/G6 报告为纯 dict，可序列化落库/前端展示；不设全局副作用。
- **D6（降级安全）**：G5/G7 涉及外部数据（akshare）时 best-effort 降级，不阻断回测。

---

## 7. 测试与验收（测试视角）

- **T1**：G1 单测覆盖 `compute_point_in_time` 对齐、`lookahead_guard` 触发、`assert_no_lookahead` 对全部已注册因子通过。
- **T2**：G1 回测集成测试：开启 PIT 前后 NAV 不同，证明护栏生效（回归门禁）。
- **T3**：G2 用合成单调因子验证 IC/ICIR/衰减/中性化断言。
- **T4**：G3 用已知 μ/Σ 验证 max_sharpe > 等权/ERC、约束生效、协方差半正定。
- **T5**：G4 合成"存在真实最优"问题验证搜索找回 + 可复现。
- **T6**：G5 冲击随参与率单调递增、方向正确。
- **T7**：G6 CVaR≥VaR、HHI 边界、压力情景符号正确。
- **T8**：G8 `compute_all_metrics` 向后兼容 + 新指标数值正确；全量回归 0 失败。

---

## 8. 实施计划

### 8.1 Action Items（建议拆分）
- **A1** [G1] `factor/engine.py`：`compute_point_in_time` + `lookahead_guard`；新增 `exceptions.LookaheadWarning`；`tests/unit/test_factor_pit.py`。
- **A2** [G1] 研究驱动入口 `FactorResearch.run_cross_sectional`；回测侧默认走 PIT；`assert_no_lookahead` 测试辅助；新增回测回归测试。
- **A3** [G2] `factor/analytics.py`（IC/RankIC/ICIR/decay/turnover/neutralize/zscore）+ `FactorValidator`；`tests/unit/test_factor_analytics.py`。
- **A4** [G3] `portfolio/optimizer.py` + `portfolio/cov.py` + `portfolio/rebalance.py`；`tests/unit/test_portfolio_optimizer.py`。
- **A5** [G4] `strategy/optimize.py`（grid/random + walk_forward 目标 + overfit_report）；`tests/unit/test_strategy_optimize.py`。
- **A6** [G5] `paper/impact.py` + `FillSimulator.impact_model` 注入 + `FeeCalculator.per_lot_fee`；`tests/unit/test_paper_impact.py`。
- **A7** [G6] `risk/analytics.py`（CVaR/parametric_var/stress/exposure/liquidity）+ `post_trade_risk_report`；`tests/unit/test_risk_analytics.py`。
- **A8** [G7] `market/universe.py` `PointInTimeUniverse` + 与 `SuspensionService` 协同；`tests/unit/test_market_universe.py`。
- **A9** [G8] `analytics/performance.py` + `stats.py` 新增 Calmar/回撤时长/矩/滚动/单笔；并入 `compute_all_metrics`；`tests/unit/test_performance_extra.py`。
- **A10** [收尾] 全量回归门禁（0 失败），更新 `docs/` 索引与本文档状态。

### 8.2 Definition of Done
- 所有 G1–G8 对应 Action Items 完成并通过单测。
- 全量 `pytest` **0 失败**（满足 D3/T8）。
- G1 前视护栏默认开启，回归测试证明"开启后 NAV 不优于关闭"（无未来函数抬升）。
- G2/G6 报告可经 `FactorStorage` / `post_trade_risk_report` 落库或前端展示。
- 本文档 §8.1 状态回写（实现/挂起）。

---

## 9. 风险与依赖
- **R-1（前视护栏可能压低历史"漂亮"指标）**：G1 上线后部分历史回测结果会变差，属正确行为，需在发布说明中明示，避免被误读为"退化"。
- **R-2（无 scipy/sklearn）**：G2/G3/G6 的统计函数需自实现，注意数值稳定性（参考现有 `_norm_*` Acklam 近似写法）。
- **R-3（协方差奇异性）**：小样本/高相关下 `Sigma` 可能近奇异，`shrunk_cov` 与 `max_weight` 约束兜底。
- **R-4（外部数据）**：G7 的上市/退市数据依赖 `akshare`，降级为空不影响回测，但 PIT 保护力度下降，需在报告中提示数据覆盖度。
