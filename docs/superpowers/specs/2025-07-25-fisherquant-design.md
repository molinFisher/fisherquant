# FisherQuant 量化交易系统 — 架构设计

> 日期：2025-07-25
> 状态：设计完成，待审批

---

## 1. 概述

FisherQuant 是一个面向个人使用的量化交易系统，覆盖策略研究、回测、模拟交易到实盘的全流程。目标市场为 **A 股 + 港股通**，支持股票、ETF、可转债三种资产类型。

### 核心原则

- **同一套策略代码，改一行配置即可在回测/模拟/实盘间切换**
- **模块间通过事件总线解耦，接口先行**
- **YAGNI — 不引入当前不需的复杂度**

---

## 2. 整体架构

### 2.1 14 核心模块 + 3 系统支撑模块

```
┌─────────────────────────────────────────────────────────────────┐
│                    事件总线 (Event Bus) — 双模                     │
│                   asyncio 进程内 (默认) / Redis (可选)              │
├──────────┬──────────┬──────────┬──────────┬─────────────────────┤
│ 行情网关   │ 数据存储  │ 因子引擎  │ 策略引擎  │ 组合优化器           │
│ Market   │  Store   │ Factor   │ Strategy │ Portfolio           │
│ Gateway  │          │ Engine   │ Engine   │ Builder             │
├──────────┴──────────┴──────────┴──────────┴─────────────────────┤
│  订单管理 (OMS) ←→ 执行通道 (Broker) ←→ 持仓服务 (Position)        │
├─────────────────────────────────────────────────────────────────┤
│  模拟交易引擎 (Paper) │ 回测引擎 (Backtest)                        │
├─────────────────────────────────────────────────────────────────┤
│  风控引擎 (Risk)  │ 绩效分析 (Analytics)                          │
├─────────────────────────────────────────────────────────────────┤
│  告警通知 (Alert)  │  Web 监控面板 (Monitor)                       │
├─────────────────────────────────────────────────────────────────┤
│  调度器 (Scheduler)  │  日志 (Logging)  │  配置 (Config)           │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 模块职责

| 模块 | 职责 | 关键接口 |
|------|------|----------|
| **Market Gateway** | 实时/历史行情接入，统一行情格式 | 可插拔适配器 (akshare 默认) |
| **Data Store** | DuckDB 持久化，缓存，Schema 迁移 | 统一读写接口，可替换后端 |
| **Factor Engine** | 因子计算管线、注册/发现、结果缓存 | 内置 40+ 因子，`CustomFactor` 扩展 |
| **Strategy Engine** | 策略生命周期 + YAML 管线解析 | 策略基类、热加载、状态序列化 |
| **Portfolio Builder** | 信号汇总→权重→目标持仓→订单 | 等权/风险平价/凯利/透传 |
| **Paper Engine** | 模拟成交 + 费用 + 市场规则，实现 `BrokerAdapter` | **回测和模拟盘共用** |
| **OMS** | 订单状态机、条件单模拟 | 7 种订单状态 |
| **Broker Gateway** | 券商适配抽象 | `BrokerAdapter` 接口，`PaperEngine` 实现 |
| **Position Service** | 持仓/成本核算/多币种混仓 | 加权平均成本法 |
| **Risk Engine** | 三级风控：预交易(同步阻断) + 实时监控 + 盘后归因 | 可配置规则集 |
| **Backtest Engine** | 回测调度 + `TimePlayer` + 复用 `PaperEngine` | 成交逻辑不重复实现 |
| **Analytics** | 绩效指标、Brinson/Barra 归因、报告生成 | HTML/JSON/PDF 三格式 |
| **Alert** | 告警路由、节流、聚合 | 控制台 + Web 面板，预留外部渠道 |
| **Monitor** | FastAPI Web 仪表盘，WebSocket 实时推送，JWT 认证 | 登录保护，4 个面板页面 |
| **Scheduler** | 统一管理开盘/午休/收盘/日终/定时调仓钩子 | APScheduler |
| **Logging** | 按模块分级，结构化 JSON 输出，每日轮转 | 终端彩色 + JSON 双输出 |
| **Config** | YAML + 环境变量 + pydantic 校验 | 配置优先级：环境变量 > 文件 > 默认值 |

---

## 3. 事件总线

### 3.1 双模设计

```yaml
# configs/system.yaml
event:
  backend: asyncio       # default: 进程内，零依赖
  # backend: redis       # 可选升级
```

### 3.2 核心事件类型

```
MarketSnapshot       — 实时行情快照
Bar                  — K 线闭合 (日/分)
Signal               — 策略信号
OrderPending         — 订单待提交
OrderAcked           — 券商已受理
OrderPartiallyFilled — 部分成交
OrderFilled          — 完全成交
OrderRejected        — 被拒绝 (风控/交易所)
OrderCancelled       — 已撤销
PositionUpdate       — 持仓变动
RiskAlert            — 风控告警
MarketOpen           — 开盘
MarketClose          — 收盘
MarketMidBreak       — 午休开始
MarketMidResume      — 午休恢复
DividendEvent        — 除权除息
SplitEvent           — 拆股/合股
SuspensionEvent      — 停牌
ResumptionEvent      — 复牌
SystemError          — 系统异常
```

### 3.3 事件流转

```
Market Gateway →(Bar)→ Strategy Engine →(Signal[])→ Portfolio Builder
    ↓                                                     ↓
    │                                (合并信号 → 权重 → 目标持仓 → Order[])
    ↓                                                     ↓
    │                                              Risk Engine
    ↓                                           ↙               ↘
    │                               (通过) OMS → Broker        (拒绝) Alert
    ↓                                              ↓
    └──────────(OrderFilled)────→ Position Service → Monitor/Analytics
```

---

## 4. 技术栈

| 组件 | 选型 | 版本 |
|------|------|------|
| 语言 | Python | 3.11+ |
| 行情数据 | akshare (默认，可插拔) | latest |
| 数据处理 | polars (多核向量化) | latest |
| 存储 | DuckDB (嵌入式 OLAP) | latest |
| 文件格式 | Parquet (分区) | — |
| 事件总线 | asyncio PubSub / Redis (可选) | — |
| Web 框架 | FastAPI + WebSocket | latest |
| 前端 | Jinja2 + HTMX + Chart.js (CDN) | — |
| 配置管理 | YAML + pydantic v2 | latest |
| 调度 | APScheduler | latest |
| 认证 | python-jose (JWT) + passlib | latest |
| 包管理 | uv | latest |
| 测试 | pytest + pytest-asyncio | latest |

### 数据频率

| 模块 | 日线 | 分钟线 | Tick |
|------|------|--------|------|
| Strategy (CTA) | ✓ 默认 | ○ 可选 | — |
| Factor Engine | ✓ 默认 | △ 部分需分钟线 | — |
| Backtest | ✓ 默认 | ○ 付费源 | — |
| Paper Engine | ✓ | ○ | — |
| Monitor 实时推送 | ✓ (3s 刷新) | — | — |
| Position 估值 | ✓ | ✓ | — |

akshare 默认提供日线，分钟线为可选升级项。策略需声明最小数据频率，启动时校验。

---

## 5. 市场规则：A 股 vs 港股通

### 5.1 完整规则矩阵

| 约束 | A 股 | 港股通 |
|------|------|--------|
| T+N | T+1 (买入次日可卖) | T+0 (当日可卖)，T+2 交收 |
| 涨跌停 | 主板 ±10%, 科创/创业 ±20%, 北交所 ±30%, ST ±5% | 无 |
| 新股首日 | 主板 ±44%, 科创/创业无限制 | 无特殊限制 |
| 交易单位 | 100 股整数倍 | 每手不固定 (100~10000) |
| 碎股 | — | 零股卖出折价 0.25%+ |
| 手续费 | 佣金 万2.5 + 过户费 0.001% + 规费 0.00687% | 佣金 + 征费 0.0027% + 交易费 0.00565% |
| 印花税 | 卖出 0.05% | 买卖双向各 0.1% |
| 结算费 | — | 成交额 0.002% |
| 汇率 | — | HKD→CNY, 汇兑成本 1~3% |
| 做空 | 融券受限 | 港股通不支持 |
| 日额度 | — | 南向 105 亿 RMB |
| 股息税 | 持股 >1年 免税 | 统一 20% |
| 交易日历 | A 股交易日 | 香港公众假日 |
| 交易时段 | 9:15-9:25 集合, 9:30-11:30/13:00-15:00 | 9:00-9:30 竞价, 9:30-12:00/13:00-16:00/16:00-16:10 |
| 收市竞价 | — | 16:00-16:10 |
| 熔断 | 指数 7%/13% (规则存在) | — |
| 盘中临停 | 新股首日 ±30%/±60% 临停 10min | — |

### 5.2 ETF / 可转债 特殊规则

| 品种 | T+N | 涨跌停 | 印花税 | 交易单位 |
|------|-----|--------|--------|----------|
| ETF | T+1 | 同板块规则 | 免 | 100 份 |
| 可转债 | T+0 | 无 | 免 | 10 张 (1000元面值) |

### 5.3 多品种混仓

同一组合可持有 A 股 + 港股通 + ETF + 可转债，按标的归属市场自动选择规则。`MarketRules` 接口化，新增市场只需实现 `ExchangeRules`。

---

## 6. 公司行为处理

### 6.1 停牌

| 场景 | 处理 |
|------|------|
| 盘中停牌 | 该标的后续 Bar 跳过，挂单撤销 |
| 持有停牌标的 | 市值按最后成交价冻结 |
| 复牌 | 按实际开盘价恢复，不补中间 Bar |
| 长时间停牌 (N 天) | 标记"不可交易"，调仓时跳过 |

### 6.2 除权除息

- 回测统一使用**前复权价格**计算收益
- 事件层记录 `DividendEvent`，包含 ex_date、每股分红、送转比例
- 持仓自动调整：股数增加 / 现金到账（扣除红利税）

### 6.3 拆股/合股

- `SplitEvent` 记录日期和比例
- 持仓自动调整，历史价格已复权

### 6.4 港股通标的调整

- 定期调入/调出事件，影响可交易范围

### 6.5 数据来源

以上事件全部从 akshare 接口预获取并存入 DuckDB，回测时按日期匹配应用。

---

## 7. 策略体系

### 7.1 策略谱系

```
Strategy (基类)
├── CTABase              — 单标的技术面趋势跟踪
│   ├── MomentumStrategy  (动量突破)
│   ├── MeanReversion     (均值回归)
│   └── GridTrading       (网格交易)
├── FactorBase           — 多因子截面选股
│   ├── AlphaModel       (因子打分，选前 N)
│   └── RotationalModel  (轮动，定期切换)
├── PairTrade            — 配对交易 / 统计套利
├── EventDriven          — 事件驱动
│   ├── Arbitrage       (套利)
│   ├── Calendar        (日历效应、ST 脱帽、业绩预告)
│   └── BlockBreak      (涨停板开板追踪)
├── MLStrategy           — 机器学习 (sklearn 管线)
└── CompositeStrategy    — 多策略叠加
```

### 7.2 YAML 管线 (无需写代码)

```yaml
pipeline:
  - stage: data       # 数据准备
    universe: csi300
    lookback: 252d
  - stage: factor     # 因子
    factors: [momentum_20d, volatility_60d, pb_ratio]
  - stage: model      # 信号模型
    type: ml          # ml | linear | custom
    model: xgboost
    target: forward_return_10d
  - stage: portfolio
    top_k: 30
    weight: equal_risk
  - stage: risk
    max_sector_exposure: 0.3
    stop_loss: -0.08
```

### 7.3 多策略同标的冲突

```yaml
portfolio:
  conflict_mode: weighted_merge   # skip_conflict | weighted_merge | first_wins
```

| 模式 | 行为 |
|------|------|
| `skip_conflict` | 重叠标的当日不交易 |
| `weighted_merge` | 按策略权重加权合并信号 |
| `first_wins` | 先到信号为准 |

### 7.4 因子库

```
Factor (基类)
├── PriceFactor      — 量价 (动量、波动率、换手率...)
├── FundamentalFactor — 基本面 (PE、PB、ROE...)
├── TechnicalFactor  — 技术指标 (MACD、RSI、布林带...)
└── CustomFactor     — 用户自定义，函数注册
```

因子计算结果缓存 (同因子+同参数+同日期不重复计算)。

### 7.5 策略生命周期

```python
class Strategy(ABC):
    async def on_init(self) -> None:       ...
    async def on_bar(self, bar: Bar) -> None: ...
    def on_signal(self) -> list[Signal]:   ...
    async def on_order_filled(self, order: Order): ...
    async def on_risk_close(self, order: Order): ...
    def serialize_state(self) -> dict:     ...    # 系统重启恢复
    def restore_state(self, state: dict):  ...
```

策略自动从 `strategies/` 目录注册，配置按名称引用。支持热加载 (开发中策略修改不重启系统)。

---

## 8. 模拟交易引擎 (Paper Engine)

### 8.1 定位

`PaperEngine` 实现 `BrokerAdapter` 接口，**回测和模拟盘共用同一套成交逻辑**。唯一差异在时间驱动：

- 回测模式：`TimePlayer` 驱动，历史数据逐 Bar 回放
- 模拟盘模式：系统时钟驱动，实时行情触发

### 8.2 成交判定

| 订单类型 | 成交条件 | 成交价 |
|----------|----------|--------|
| 限价买单 | `low <= limit_price` | `min(limit_price, 成交价)` |
| 限价卖单 | `high >= limit_price` | `max(limit_price, 成交价)` |
| 市价买单 | 下一 Bar | 开盘价 + 滑点 |
| 市价卖单 | 下一 Bar | 开盘价 - 滑点 |

成交价模式可配置：`next_open` | `current_close` | `vwap` | `random`。

### 8.3 涨跌停流动性模拟

可配置两种模式：
- **纯规则**：涨停不买，跌停不卖（默认）
- **概率模型**：按封板金额/成交额比率估算成交概率

### 8.4 下单前自动校验链

```
1. 交易时段检查
2. 价格涨跌停检查 (按板块区分)
3. 数量取整 (整手/整股，按品种)
4. 资金可用性检查 (含预估费用)
5. 持仓可用性检查 (T+1 / 冻结)
6. 港股通日额度检查
```

### 8.5 费用计算

| 品种 | 佣金 | 印花税 | 过户费 | 规费 | 结算费 |
|------|------|--------|--------|------|--------|
| A 股 | 万2.5 | 0.05%(卖) | 0.001% | 0.00687% | — |
| ETF | 万1.0 | 免 | — | — | — |
| 可转债 | 万0.5 | 免 | — | — | — |
| 港股通 | 万2.5 | 0.1%(双) | — | 0.00835% | 0.002% |

所有费率 `configs/fees.yaml` 可覆盖。

### 8.6 订单有效期

默认**当日有效** (Day)，收盘自动撤销所有未成交单。`GTC` 预留扩展。

### 8.7 持久化与恢复

未成交订单写入 DuckDB，系统重启后恢复。初始资金/持仓从配置加载。

---

## 9. 订单管理 (OMS)

### 9.1 订单状态机

```
NEW → PENDING → (风控通过) → SUBMITTED → ACKED → PARTIALLY_FILLED → FILLED
                            ↘ REJECTED                  ↘ CANCELLED
```

### 9.2 订单类型

| 订单 | A 股 | 港股通 | 实现方式 |
|------|------|--------|----------|
| 限价单 | ✓ | ✓ | 直接发送券商 |
| 市价单 | ✓ (五档即成剩撤) | ✓ | 直接发送券商 |
| 止损单 | ✗ | ✗ | **OMS 本地条件单模拟** |
| 止盈单 | ✗ | ✗ | **OMS 本地条件单模拟** |

止损/止盈单存放于 OMS 本地条件单队列，行情触发后 OMS 自动生成市价单发送。

---

## 10. 持仓服务 (Position Service)

- **成本核算**：加权平均法
- **多币种**：港股通 HKD 自动换算 CNY (引用每日参考汇率)
- **T+1 解禁**：A 股买入后次日 `available` 解锁
- **冻结管理**：下单时冻结，成交/撤销时调整
- **历史快照**：每日收盘自动保存至 DuckDB

---

## 11. 风控引擎 — 三级体系

### Level 1: 预交易 (同步阻断)

| 规则 | 说明 |
|------|------|
| MaxPosition | 单票仓位 ≤ 总资产 N% |
| NetExposure | 净暴露限制 |
| SectorLimit | 单行业暴露 ≤ N% |
| DailyLossLimit | 当日累计亏损 ≥ N% 停止 |
| OrderSizeLimit | 单笔 ≤ 日均成交量 N% |
| PriceLimit | 涨停不追/跌停不卖 |
| TPlusOne | 品种 T+1 检查 |
| Blacklist | 黑名单标的禁止买入 |

### Level 2: 实时监控

VaR (历史模拟法 99%)、组合 Beta、日内最大回撤、保证金占用率。每秒计算，超标触发平仓。

### Level 3: 盘后归因

Brinson 归因 (配置效应 + 选股效应 + 交互效应)，Barra 归因预留。

---

## 12. 回测引擎

### 12.1 架构

```
BacktestEngine
├── TimePlayer        — 历史数据时间轴回放，发布 Bar 事件
├── PaperEngine       — 复用模拟交易引擎 (成交/费用/规则)
└── Analytics         — 绩效统计
```

不重复实现成交逻辑。`TimePlayer` 把系统时钟替换为历史数据迭代。

### 12.2 绩效指标

累计/年化收益率、夏普比率、索提诺比率、最大回撤、胜率、盈亏比、波动率、Beta、Alpha、信息比率、换手率。

### 12.3 输出

- 净值曲线 vs 基准叠加图
- 回撤曲线
- 月度收益热力图
- HTML + JSON + PDF 三格式报告

---

## 13. 绩效分析

### 实时指标
当日盈亏、日内最大回撤、仓位比例 — 监控面板消费。

### 日终报告
全部绩效指标 + Brinson 归因，自动生成。

### 基准对比
支持多基准组合 (如 70% CSI300 + 30% HSI)。

---

## 14. 告警通知

### 渠道

| 渠道 | 说明 |
|------|------|
| 控制台输出 | 终端打印 (开发/本地运行) |
| Web 面板 | 监控面板告警 Tab，WebSocket 实时推送 + 历史日志 |
| 预留扩展 | `AlertChannel` 接口，后续接入钉钉/企业微信/邮件 |

### 机制

- **节流**：同事件类型 N 秒内不重复
- **静默时段**：可配免打扰时间，CRITICAL 除外
- **聚合**：多个 INFO 级事件合并一条消息

---

## 15. Web 监控面板

### 技术

FastAPI + WebSocket (后端)，Jinja2 + HTMX + Chart.js CDN (前端)。无 Node.js 构建步骤。

### 认证

首次启动生成随机 admin 密码，写入 `~/.fisher/credentials`。JWT token，24h 过期。`--reset-password` 重置。

### 页面

| 页面 | 内容 |
|------|------|
| 登录 `/login` | 用户名+密码 |
| 概览 `/dashboard` | 当日盈亏、资产曲线、持仓卡片、信号列表 |
| 交易日志 `/dashboard/orders` | 订单流水，按标的/日期过滤 |
| 风控面板 `/dashboard/risk` | 实时指标仪表盘、行业暴露饼图、事件日志 |
| 策略状态 `/dashboard/strategy` | 策略运行状态、最近信号、参数查看 |
| 告警 `/dashboard/alerts` | 告警历史、按级别过滤 |
| 设置 `/dashboard/settings` | 修改密码 |

### WebSocket 推送通道

- `/ws/overview` — 概览 (每 3 秒)
- `/ws/risk` — 风控指标 (每秒)
- `/ws/orders` — 订单推送 (事件驱动)
- `/ws/alerts` — 告警推送 (事件驱动)

行情刷新遵守 akshare 频率限制 (2 次/秒)，监控面板推送与之解耦。

---

## 16. 调度器

统一管理所有定时任务：

| 任务 | 触发 | 说明 |
|------|------|------|
| 开盘初始化 | 9:25 | 重置计数器、加载持仓 |
| 午休暂停 | 11:30 | 暂停信号生成 |
| 午休恢复 | 13:00 | 恢复 |
| 收盘处理 | 15:00(A股)/16:10(港股通) | 撤日单、持仓快照 |
| 日终任务 | 15:30 | 报告、归档、策略再训练 |
| 定时调仓 | 周一 9:30 / 月初 | Portfolio rebalance |

---

## 17. 错误处理与容错

| 场景 | 处理 |
|------|------|
| akshare API 失败 | 3 次重试 (1s/3s/5s 退避) → 降级本地缓存 → 告警 |
| DuckDB 写入失败 | 内存缓冲队列 → 异步重试 → 告警 (不阻塞行情) |
| 单策略抛异常 | try/except 包裹 → 该策略自动暂停 → 告警 → 其他策略继续 |
| DuckDB 损坏 | 启动 CHECKPOINT + 备份 → 引导 `fisher db repair` |
| 行情全不可用 | 状态标记 DEGRADED → 暂停信号 → 监控面板红色警告 |

---

## 18. 日志系统

```yaml
logging:
  level: INFO
  dir: logs/
  rotation: daily
  retention: 90d
  structured: true          # JSON 行格式
  modules:                  # 按模块独立级别
    strategy: DEBUG
    risk: INFO
    market: WARNING
```

终端彩色格式化 + JSON 文件双输出。关键事件 (信号/订单/成交/风控) 结构化记录。

---

## 19. 配置体系

```
configs/
├── system.yaml       # 运行模式、事件总线后端、Redis地址、日志
├── market.yaml       # 行情源、刷新频率、频率限制
├── strategy.yaml     # 策略管线、冲突模式、组合方法
├── risk.yaml         # 预交易规则、实时监控阈值
├── fees.yaml         # 各品种费用
├── alert.yaml        # 告警路由、节流
├── benchmark.yaml    # 基准配置
└── broker.yaml       # 券商连接 (模拟/实盘, 预留)
```

配置优先级：`环境变量 > 配置文件 > 默认值`。敏感信息用 `${ENV_VAR}` 引用。

---

## 20. 项目目录结构

```
FisherQuant/
├── fisher/
│   ├── __init__.py
│   ├── event/                 # 事件总线 (双模)
│   │   ├── __init__.py
│   │   ├── bus.py             # EventBus 抽象 + asyncio 实现
│   │   └── types.py           # 所有 Event 类型定义
│   ├── market/                # 行情网关
│   │   ├── __init__.py
│   │   ├── gateway.py         # MarketGateway 统一接口
│   │   ├── akshare.py         # akshare 适配器
│   │   └── rules.py           # ExchangeRules (A股/港股通/ETF/转债)
│   ├── store/                 # 数据存储
│   │   ├── __init__.py
│   │   ├── engine.py          # DuckDB 连接管理
│   │   ├── schema.py          # 建表 + 版本化迁移
│   │   └── repository.py      # 数据查询接口
│   ├── factor/                # 因子引擎
│   │   ├── __init__.py
│   │   ├── engine.py          # 因子计算 + 缓存
│   │   ├── registry.py        # 因子注册/发现
│   │   ├── base.py            # Factor 基类
│   │   ├── price.py           # 量价因子
│   │   ├── fundamental.py     # 基本面因子
│   │   └── technical.py       # 技术指标因子
│   ├── strategy/              # 策略引擎
│   │   ├── __init__.py
│   │   ├── engine.py          # 策略生命周期管理
│   │   ├── base.py            # Strategy 基类 (含状态序列化)
│   │   ├── pipeline.py        # YAML 管线解析
│   │   └── registry.py        # 策略自动注册/热加载
│   ├── portfolio/             # 组合优化器
│   │   ├── __init__.py
│   │   ├── builder.py         # 信号合并 + 权重计算 + 订单生成
│   │   └── methods.py         # 等权/风险平价/凯利
│   ├── paper/                 # 模拟交易引擎
│   │   ├── __init__.py
│   │   ├── engine.py          # PaperEngine (BrokerAdapter 实现)
│   │   ├── fill.py            # 成交模拟器
│   │   └── fees.py            # 费用计算器
│   ├── oms/                   # 订单管理系统
│   │   ├── __init__.py
│   │   ├── engine.py          # 订单状态机 + 条件单队列
│   │   └── orders.py          # Order 数据模型
│   ├── broker/                # 券商网关
│   │   ├── __init__.py
│   │   ├── adapter.py         # BrokerAdapter 抽象接口
│   │   └── registry.py        # 券商注册
│   ├── position/              # 持仓服务
│   │   ├── __init__.py
│   │   └── service.py         # 持仓管理 + 成本核算 + 快照
│   ├── risk/                  # 风控引擎
│   │   ├── __init__.py
│   │   ├── engine.py          # 风控编排
│   │   ├── pre_trade.py       # 预交易规则集
│   │   ├── realtime.py        # 实时监控指标
│   │   └── barra.py           # Barra 归因 (预留)
│   ├── backtest/              # 回测引擎
│   │   ├── __init__.py
│   │   ├── engine.py          # 回测编排
│   │   └── time_player.py     # 时间轴回放器
│   ├── analytics/             # 绩效分析
│   │   ├── __init__.py
│   │   ├── performance.py     # 绩效指标计算
│   │   ├── attribution.py     # Brinson/Barra 归因
│   │   └── report.py          # 报告生成 (JSON/HTML/PDF)
│   ├── alert/                 # 告警通知
│   │   ├── __init__.py
│   │   ├── service.py         # 路由/节流/聚合
│   │   └── channel.py         # AlertChannel 抽象
│   ├── monitor/               # Web 监控面板
│   │   ├── __init__.py
│   │   ├── app.py             # FastAPI 应用工厂
│   │   ├── auth.py            # JWT 认证
│   │   ├── ws.py              # WebSocket 端点
│   │   ├── routes/            # REST 路由
│   │   └── templates/         # Jinja2 + HTMX 页面
│   ├── scheduler/             # 调度器
│   │   ├── __init__.py
│   │   └── engine.py          # 定时任务管理 (APScheduler)
│   ├── logging/               # 日志
│   │   ├── __init__.py
│   │   └── setup.py           # 日志初始化 (结构化 + 模块级)
│   └── config/                # 配置
│       ├── __init__.py
│       └── loader.py          # YAML + 环境变量 + pydantic 校验
├── strategies/
│   ├── builtin/               # 内置策略 (CTA/因子/事件/ML)
│   ├── custom/                # 用户自定义 .py 策略文件
│   └── pipelines/             # YAML 管线策略
├── configs/                   # 全局 YAML 配置文件
├── tests/
│   ├── unit/                  # 每模块单元测试
│   ├── integration/           # 端到端链路测试
│   ├── validation/            # 已知结果回测验证
│   └── conftest.py            # 共享 fixture
├── data/                      # 本地数据缓存 (.gitignore)
├── logs/                      # 日志输出 (.gitignore)
├── pyproject.toml
└── README.md
```

---

## 21. 测试策略

| 层次 | 内容 | 说明 |
|------|------|------|
| unit | 每模块独立测试，mock 外部依赖 | 覆盖所有模块 |
| integration | Signal→Order→Position、Order→Paper→Position | 端到端局部链路 |
| validation | 双均线策略 × 固定数据集，对比已知净值曲线 | 回归测试，数据纳入 git |

- 所有异步测试使用 `pytest-asyncio`
- CI 门槛：单元 + 集成测试通过，回归测试净值差异 < 0.1%

---

## 22. 系统启动流程

```
1. 加载 configs/system.yaml → 确定 run_mode (backtest | paper | live)
2. 初始化 Logging (结构化日志)
3. 初始化 Event Bus (asyncio/Redis)
4. 初始化 Data Store (DuckDB 建表/迁移/校验)
5. 初始化 Scheduler → 注册市场事件钩子
6. run_mode 分支:
   ├── backtest: 加载历史数据 → BacktestEngine + PaperEngine + Analytics
   ├── paper:    Market Gateway → PaperEngine + Risk + OMS + Alert + Monitor
   └── live:     Market Gateway → Broker Gateway + Risk + OMS + Alert + Monitor (预留)
7. 启动 FastAPI (Monitor)
8. 注册事件订阅 → 开始事件循环
```

### 命令行入口

```
fisher run          # 启动 (按 system.yaml)
fisher backtest     # 回测
fisher server       # 仅 Web 面板
fisher factor list  # 列出可用因子
fisher db init      # 初始化数据库
fisher db repair    # 修复损坏的 DuckDB
```

---

## 23. 实现阶段

| 阶段 | 模块 | 里程碑 |
|------|------|--------|
| **Phase 1** | Event, Config, Logging, Store | 基础设施就绪，可读写数据 |
| **Phase 2** | Market Gateway (akshare), Factor Engine | 能拉行情、计算因子 |
| **Phase 3** | Strategy Engine, Portfolio Builder | 策略能产生信号 |
| **Phase 4** | Paper Engine, OMS, Position, Risk | 模拟交易闭环 |
| **Phase 5** | Backtest, Analytics | 回测 + 绩效报告 |
| **Phase 6** | Monitor, Alert, Scheduler, Auth | Web 监控 + 告警 |
| **Phase 7** | Broker Gateway (实盘适配) | 预留接口，后续开发 |
