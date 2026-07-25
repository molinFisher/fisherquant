# FisherQuant 综合测试与自愈系统

> 日期：2025-07-25
> 状态：设计完成，待审批

---

## 1. 概述

构建一个自动化测试与自愈系统，下载真实市场数据，端到端运行 FisherQuant 全部模块，自动发现 bug 并尝试修复。

## 2. 执行流程（5 阶段）

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ 数据采集  │ → │ 单元测试  │ → │ 回测验证  │ → │ 监控验证  │ → │ 自动修复  │
│          │    │          │    │          │    │          │    │          │
│ akshare  │    │ pytest   │    │ 端到端   │    │ FastAPI  │    │ 3轮迭代  │
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
                                                                      │
                                                              ┌───────┘
                                                              ▼
                                                        ┌──────────┐
                                                        │ 测试报告  │
                                                        │          │
                                                        │ HTML+JSON│
                                                        └──────────┘
```

## 3. 阶段 1：数据采集

**目标：** 下载 A 股 + 港股通真实历史数据，存入系统 DuckDB。

**A 股范围：** 沪深 300 成分股（通过 akshare 获取成分股列表），取前 20 只
**港股通范围：** 腾讯(00700.HK)、美团(03690.HK)、小米(01810.HK)、阿里(09988.HK)、比亚迪(01211.HK)
**时间范围：** 2024-01-01 至 2024-12-31
**频率：** 日线

**数据校验：**
- 每只股票至少 200 个交易日数据
- close 价格 > 0
- volume > 0 的交易日在 50% 以上

## 4. 阶段 2：单元测试

**命令：** `pytest tests/ -v --tb=short --timeout=30 2>&1`

**分类处理：**
| 结果 | 处理 |
|------|------|
| PASS | 记录通过数 |
| SKIP | 记录跳过原因（akshare/网络依赖） |
| FAIL/ERROR | 收集 traceback，送入修复引擎 |

## 5. 阶段 3：回测验证

**测试场景 1：双均线策略回测（A 股）**
- 标的：平安银行(000001.SZ)、贵州茅台(600519.SH)、宁德时代(300750.SZ)
- 策略：MomentumStrategy(fast=10, slow=30)
- 起始资金：1,000,000
- 手续费：按 A 股费率
- 输出：净值曲线 JSON + 绩效 HTML 报告

**测试场景 2：双均线策略回测（港股通）**
- 标的：腾讯(00700.HK)、美团(03690.HK)
- 策略：MomentumStrategy(fast=5, slow=20)
- 起始资金：1,000,000 HKD
- 手续费：按港股通费率
- **含汇率换算**：HKD → CNY 参考汇率

**回测结果验证：**
- 回测引擎不抛异常
- 净值序列长度 > 0
- 绩效报告中 sharpe_ratio 为数值（非 NaN/Inf）
- 至少产生 1 笔成交

## 6. 阶段 4：监控面板验证

- 启动 `fisher server` 或程序化启动 FastAPI
- HTTP GET `/dashboard` → 200
- HTTP GET `/login` → 200
- WebSocket 连接 `/ws/overview` → 握手成功
- 5 秒后关闭服务

## 7. 阶段 5：自动修复引擎

**输入：** 阶段 2-4 收集的所有错误列表

**修复流程（每轮）：**
1. 解析 traceback → 提取 (文件路径, 行号, 异常类型, 异常消息)
2. 按异常类型匹配修复策略
3. 生成 diff → apply → 重跑相关测试
4. 最多 3 轮迭代

**修复策略（完整的 15 种）：**

| # | 异常类型 | 修复策略 |
|---|---------|---------|
| 1 | ModuleNotFoundError | pip install 缺失包；或修正 import 路径 |
| 2 | ImportError | 补全 import 语句；或创建/注册缺失模块 |
| 3 | AttributeError（X object has no attribute Y）| 检查对象类型，补属性和方法定义 |
| 4 | TypeError（参数数量不匹配）| 对齐函数签名和调用参数 |
| 5 | TypeError（类型错误）| 添加类型转换（str→float 等）|
| 6 | NameError | 补定义/import |
| 7 | ValueError | 分析输入值范围，补校验和边界处理 |
| 8 | KeyError | 补字典默认值或 get() |
| 9 | IndexError | 补长度检查 |
| 10 | FileNotFoundError | 创建目录和默认文件 |
| 11 | AssertionError | 对比 actual vs expected，修正逻辑或放宽断言 |
| 12 | ValidationError（pydantic）| 补默认值或调整 schema |
| 13 | ConnectionError / TimeoutError | 补重试逻辑或降级 |
| 14 | ZeroDivisionError | 补分母零检查 |
| 15 | NotImplementedError | 补基础实现 |

**修复后验证：**
- 每轮修复后重跑失败的测试
- 固定回归为 PASS → 修复成功
- 修复引入新失败 → 回滚该修复，标记 failed
- 3 轮后仍有失败 → 标记 unresolved

## 8. 测试报告

**输出格式：**

```
reports/
├── test_report_YYYY-MM-DD.json     # 结构化数据
├── test_report_YYYY-MM-DD.html     # 可视化报告
└── backtest/                        # 回测图表
    ├── equity_curve.png
    ├── performance.html
    └── positions.csv
```

**报告内容：**
- 总通过/失败/跳过/修复数
- 每个失败详情（文件:行号，异常，修复状态）
- 回测绩效摘要
- 耗时统计

## 9. 入口脚本

```python
# fisher_temp/test_runner.py
def main():
    results = {
        "phase_1": download_data(),
        "phase_2": run_unit_tests(),
        "phase_3": run_backtests(),
        "phase_4": verify_monitor(),
        "phase_5": auto_fix_engine(results),
    }
    generate_report(results)
```

运行：`python fisher_temp/test_runner.py`

---

## 10. 自我审查

- [x] 无 TBD/TODO
- [x] 各阶段输入输出明确
- [x] 修复策略覆盖 15 种异常类型
- [x] A 股 + 港股通双场景覆盖
- [x] 范围适中（单一 spec，不分解）
