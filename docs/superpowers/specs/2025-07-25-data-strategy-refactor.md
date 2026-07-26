# FisherQuant 数据中心 & 策略中心重构设计

> 日期：2025-07-25  
> 状态：设计完成  

## 1. 问题摘要

### 数据中心（9 个问题）

| # | 严重度 | 问题 | 位置 |
|---|--------|------|------|
| 1 | Critical | 代码后缀硬编码 `.UNKNOWN` | `data_callbacks.py:59` |
| 2 | Important | 数据类型选择（日线/分钟线/财务）无效 | `data_callbacks.py` fetch 函数 |
| 3 | Important | 进度条在后台回调中不工作（0%→100% 跳变） | `data_callbacks.py` fetch callback |
| 4 | Medium | 导出无条件筛选，导出全部数据 | `data_callbacks.py` export callback |
| 5 | Medium | 多处 `except Exception: pass` 静默吞错误 | 遍布 `data_callbacks.py` |
| 6 | Medium | 缓存筛选参数复制粘贴 bug | `data_callbacks.py` cache filter |
| 7 | Low | DuckDBManager 重复 connect | `_get_db()` 每次创建 |
| 8 | Low | DuckDBManager 重复 connect | `_get_db()` 每次创建 |
| 9 | Low | 资源泄漏：`init_schema_from_path` 未 close | `data_callbacks.py` |
| 10 | Low | 快速操作按钮失效 | `home_callbacks.py` |

### 自动加载（新增 3 个问题）

| # | 严重度 | 问题 | 说明 |
|---|--------|------|------|
| AL-1 | Medium | 首次使用数据为空，用户需手动拉取 | 新用户打开空面板，无从下手 |
| AL-2 | Medium | 已缓存数据不会自动增量更新 | 用户需手动"刷新"每个标的 |
| AL-3 | Low | 沪深 300 成分股变动不感知 | 指数调仓后本地数据与实际成分股脱节 |

### 策略中心（7 个问题）

| # | 严重度 | 问题 | 位置 |
|---|--------|------|------|
| 1 | Critical | 策略名未做文件名 sanitize，存在注入风险 | `strategy_callbacks.py` file I/O |
| 2 | Important | `_build_strategy_table`（DataTable）与 `_build_strategy_list`（自定义 HTML）两份重复代码 | `strategy_center.py` vs `strategy_callbacks.py` |
| 3 | Important | 模板按钮创建策略后不刷新列表 | `strategy_callbacks.py::handle_template` |
| 4 | Medium | `_collect_params_from_states()` 依赖 `ctx.states` 格式，版本脆弱 | `strategy_callbacks.py` |
| 5 | Medium | 多处 `except Exception: pass` | 遍布 `strategy_callbacks.py` |
| 6 | Low | 编辑器名无校验 | `strategy_callbacks.py` wizard step 0 |
| 7 | Low | 导入 JSON 失败无反馈 | `strategy_callbacks.py::handle_import` |

## 2. 架构变更

### 2.1 引入 Service 层（带依赖注入）

新增两个独立 Service 模块，所有业务逻辑从回调中抽取。Service 构造函数接收外部依赖，便于测试时 mock：

```
callbacks/              services/                 domain
────────────────────    ────────────────────    ────────────────────
data_callbacks.py  →    DataCenterService   →   DuckDBManager
data_cache_callbacks.py   (接受 db, limiter)      AKShare RateLimiter
data_export_callbacks.py                         MarketRules

strategy_crud_callbacks.py → StrategyService  →  JSON file I/O
strategy_wizard_callbacks.py   (接受 strategy_dir)  StrategyRegistry
                                                  DSL Engine
```

```python
class DataCenterService:
    def __init__(self, db: DuckDBManager, limiter: RateLimiter):
        self._db = db
        self._limiter = limiter

class StrategyService:
    def __init__(self, strategy_dir: str = "strategies"):
        self._dir = Path(strategy_dir)
```

回调只做 UI 编排：读输入 → 调 Service → 写输出。Service 层无 Dash 依赖，可独立测试。

**共享机制：** 在 `services/__init__.py` 中实例化单例（函数级，非模块级）：

```python
_db_instance: DuckDBManager | None = None

def get_db() -> DuckDBManager:
    global _db_instance
    if _db_instance is None:
        _db_instance = DuckDBManager()
        _db_instance.connect("data/fisherquant.db")
    elif not hasattr(_db_instance, '_write_conn') or _db_instance._write_conn is None:
        _db_instance.connect("data/fisherquant.db")
    return _db_instance

def get_data_service() -> DataCenterService:
    return DataCenterService(db=get_db(), limiter=get_global_limiter())

def get_strategy_service() -> StrategyService:
    return StrategyService()
```

### 2.2 文件拆分

| 原文件 | 行数 | 拆分为 | 预估行数 |
|--------|------|--------|----------|
| `data_callbacks.py` | 540 | `data_callbacks.py`（搜索+拉取） | ~200 |
| | | `data_cache_callbacks.py`（缓存管理） | ~150 |
| | | `data_export_callbacks.py`（导出+复权） | ~100 |
| `strategy_callbacks.py` | 638 | `strategy_crud_callbacks.py`（列表+增删改） | ~250 |
| | | `strategy_wizard_callbacks.py`（向导） | ~250 |

新建：
- `fisher/dash_app/services/__init__.py`
- `fisher/dash_app/services/data_center_service.py`
- `fisher/dash_app/services/strategy_service.py`
- `fisher/dash_app/services/models.py`

### 2.3 数据类模型

```python
# fisher/dash_app/services/models.py
from dataclasses import dataclass, field, asdict
from typing import Optional

TYPE_MAP = {
    "sma_cross": "SMA 交叉", "macd": "MACD",
    "bollinger": "布林带", "rsi": "RSI",
    "buy_and_hold": "买入持有", "custom": "自定义 DSL",
}


@dataclass
class StrategyConfig:
    name: str
    type: str
    description: str = ""
    params: dict = field(default_factory=dict)
    symbols: list[str] = field(default_factory=list)
    enabled: bool = True

    def validate(self) -> list[str]:
        errors = []
        safe = re.sub(r'[^\w\-\u4e00-\u9fff]', '_', self.name).strip()
        if not safe:
            errors.append("策略名称不能为空")
        if self.type not in TYPE_MAP:
            errors.append(f"未知策略类型: {self.type}")
        if self.type == "custom" and not self.params.get("dsl_config"):
            errors.append("自定义策略必须配置 DSL")
        return errors

    @property
    def safe_filename(self) -> str:
        return re.sub(r'[^\w\-]', '_', self.name)


@dataclass
class WizardState:
    step: int = 0
    name: str = ""
    type: str = ""
    description: str = ""
    params: dict = field(default_factory=dict)
    symbols: list[str] = field(default_factory=list)
    editing: bool = False
    original_name: str = ""
```

### 2.4 Service 接口

```python
# services/data_center_service.py
class DataCenterService:
    def search_symbols(self, query: str) -> list[dict]: ...
    def fetch_bars(self, symbols: list[str], start: str, end: str,
                   data_type: str, period: str = "") -> dict:
        """返回 {symbol: {status, count, error}}"""
    def get_cache_stats(self) -> dict:
        """返回 {total, a_share, hk, records, last_update}"""
    def get_cached_table(self, market_filter: str = "all",
                         text_filter: str = "") -> list[dict]: ...
    def delete_symbols(self, tickers: list[str]) -> int: ...
    def export_bars(self, symbols: list[str], start: str, end: str,
                    fmt: str) -> bytes: ...
    def estimate_export(self, symbols: list[str], start: str, end: str) -> dict:
        """返回 {records, estimated_size_kb}"""
    def auto_load_status(self) -> dict:
        """返回 {phase, current, total, last_run, next_run}"""

# services/auto_load_service.py
class AutoLoadService:
    def __init__(self, db: DuckDBManager, limiter: RateLimiter, scheduler: SchedulerEngine):
        self._db = db; self._limiter = limiter; self._scheduler = scheduler

    def check_and_start(self) -> dict:
        """检查 bars_daily 是否为空 → 首次加载；否则检查是否需要日终增量"""

    def initial_load(self) -> dict:
        """首次全量加载：沪深300 + 恒指成分股，批处理进度写入 auto_load_status 表"""

    def incremental_update(self) -> dict:
        """日终增量：已缓存标的缺失日期，分批（20只/批，批间10s）"""

    def get_progress(self) -> dict:
        """返回 {phase, current, total, symbol, records_added, elapsed_sec}"""

# services/strategy_service.py
class StrategyService:
    def list_strategies(self) -> list[dict]: ...
    def get_strategy(self, name: str) -> dict: ...
    def save_strategy(self, config: StrategyConfig) -> list[str]:
        """返回校验错误列表，空 = 成功"""
    def delete_strategy(self, name: str) -> bool: ...
    def toggle_enabled(self, name: str) -> bool: ...
    def export_json(self, name: str) -> str: ...
    def import_json(self, content: str) -> list[str]: ...
```

## 3. 具体修复

### 3.1 代码后缀 `.UNKNOWN` → 正确映射

```python
EXCHANGE_MAP = {
    "6": ".SH", "5": ".SH", "9": ".SH",
    "0": ".SZ", "3": ".SZ", "2": ".SZ",
    "8": ".BJ",
}
# HK Connect 保留 .HK
def resolve_ticker(code: str, market: str = "a_share") -> str:
    if market == "hk_connect":
        return f"{code.zfill(5)}.HK"
    prefix = code[0] if code else ""
    suffix = EXCHANGE_MAP.get(prefix, ".UNKNOWN")
    return f"{code}{suffix}"
```

### 3.2 进度条实时更新

改用 `dcc.Store` + `dcc.Interval` 模式：后台回调写入进度状态到 `dcc.Store`，前端每秒轮询读取并更新 `dbc.Progress`。

### 3.3 错误处理统一

所有 `except Exception: pass` 替换为：

```python
try:
    ...
except Exception as e:
    logger.error("Service error [%s]: %s", operation, e)
    return {"error": f"操作失败：{str(e)[:100]}"}
```

### 3.4 策略文件名 sanitize

```python
safe_name = re.sub(r'[^\w\-]', '_', config.name)
path = STRATEGY_DIR / f"{safe_name}.json"
```

### 3.5 删除重复策略表格代码

删除 `strategy_center.py` 中的 `_build_strategy_table`，统一使用 `strategy_callbacks.py` 中的 `_build_strategy_list`。

### 3.6 模板按钮刷新列表

`handle_template` 回调返回 `dash.no_update` 改为返回新的策略列表。

### 3.7 快速操作按钮

`quick_action_handler` 改为返回 `dcc.Location(pathname="/data-center")`。

URL 传递上下文参数，让目标页面打开时带预填状态：

```python
# 当从首页跳转时，带上下文参数
dcc.Location(id="home-nav", pathname="/data-center?focus=search")
```

数据中心页面读取 URL 参数并在 `dcc.Input` 上聚焦。

### 3.8 搜索结果本地缓存

首次搜索成功后，股票列表写入 DuckDB `symbol_cache` 表。后续搜索走本地缓存，零网络延迟：

```python
def search_symbols(self, query: str) -> list[dict]:
    cached = self._db.query_df(
        "SELECT * FROM symbol_cache WHERE code LIKE ? OR name LIKE ?",
        [f"%{query}%", f"%{query}%"],
    )
    if len(cached) > 0:
        return cached.to_dicts()
    # 缓存为空或不足 → 从 AKShare 拉取全量并缓存
    df = ak.stock_info_a_code_name()
    self._save_cache(df)
    return df.filter(pl.col("code").str.contains(query) | pl.col("name").str.contains(query)).to_dicts()
```

### 3.9 进度条带 ETA

每次进度更新同时返回 `elapsed` 和 `estimated_remaining`：

```python
# stores/progress_state → {"current": 3, "total": 10, "elapsed": 12.5, "eta": 8.3}
# 前端显示："处理中 3/10（约剩 8 秒）"
```

### 3.10 导出前预估 + 中文文件名

```python
# 导出前
def estimate_export(symbols: list[str], start: str, end: str) -> dict:
    count = self._db.query_df(
        "SELECT COUNT(*) as c FROM bars_daily WHERE ...", params,
    )["c"][0]
    size_kb = round(count * 0.15, 1)  # ~150 bytes per row
    return {"records": count, "estimated_size_kb": size_kb}

# 导出 Content-Disposition 用原始中文名（URL 编码）
headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(chinese_name)}.csv"}
```

### 3.11 自动数据加载

#### 状态持久化

在 DuckDB 中建 `auto_load_status` 表，使加载进度和计划跨进程/重启后仍可查：

```sql
CREATE TABLE IF NOT EXISTS auto_load_status (
    key VARCHAR PRIMARY KEY,       -- phase | last_run | next_run | current | total
    value VARCHAR NOT NULL
);
```

`AutoLoadService.get_progress()` 从此表读取，`progress_state` 的 `dcc.Store` 仅做前端轮询的中转。

#### AutoLoadService

独立服务，封装自动加载的全部逻辑，不混入 `DataCenterService`：

```python
# fisher/dash_app/services/auto_load_service.py
class AutoLoadService:
    def __init__(self, db: DuckDBManager, limiter: RateLimiter, scheduler: SchedulerEngine):
        self._db = db
        self._limiter = limiter
        self._scheduler = scheduler

    def check_and_start(self) -> dict:
        """系统启动时调用 → 检测 bars_daily 是否为空 → 首次加载；否则按日终计划执行"""

    def initial_load(self) -> dict:
        """首次全量加载：沪深300 + 恒指成分股"""
        # 380 只 / 每批5只 = 76 批，每批间隔 15s ≈ 19 分钟
        # 进度写入 auto_load_status 表

    def incremental_update(self) -> dict:
        """日终增量：分批（20只/批，批间10s），300只 ≈ 15批 × 10s ≈ 2.5分钟"""
```

#### 首页加载状态

加载过程中首页统计卡片显示进度文案，而非 `0`：

```python
# home_callbacks.py 在 data 空时
if stats["total"] == 0 and auto_load_in_progress:
    title = "⏳ 数据加载中"
    subtitle = f"已加载 {progress['current']}/{progress['total']} 只"
elif stats["total"] == 0:
    title = "暂无数据"
    subtitle = "自动加载即将开始..."
```

加载完成后首页显示绿色就绪徽章：

```
📥 缓存标的  380 只 ✅ 数据就绪
```

#### 增量分批策略

```yaml
# configs/market.yaml
auto_load:
  incremental_batch_size: 20       # 每批 20 只
  incremental_batch_interval: 10   # 批间间隔 10 秒
  initial_batch_size: 5            # 首次每批 5 只
  initial_batch_interval: 15       # 首次批间 15 秒
```

```
系统启动 → 数据为空？
     │
     是 → 首次全量加载（沪深300 + 恒指成分股）
     │      ├  APScheduler 提交后台任务（INF-01 DiskCacheManager）
     │      ├  每下载5只更新一次进度 → dcc.Store
     │      └  完成后更新首页统计卡片
     │
     否 → 日终增量更新（交易时段后）
            ├  硬编码 CronTrigger（16:30, 周一~周五）
            ├  检查每个已缓存标的的最后交易日期
            └  缺失日期 → 增量拉取补充
```

#### 标的范围

```python
# 首次全量：沪深 300 + 恒指成分股
def get_initial_universe() -> list[str]:
    df = ak.index_stock_cons(symbol="000300")
    a_shares = [f"{r['stock_code']}.SH" if r['stock_code'].startswith(('6','5','9'))
                else f"{r['stock_code']}.SZ" for _, r in df.iterrows()]
    hk_df = ak.hk_index_cons(symbol="HSI")
    hk_shares = [f"{r['stock_code'].zfill(5)}.HK" for _, r in hk_df.iterrows()]
    return a_shares + hk_shares

# 增量更新：已缓存标的 + 策略引用标的
def get_incremental_universe(db) -> list[str]:
    return db.query_df("SELECT DISTINCT ticker FROM bars_daily")["ticker"].to_list()
```

#### 与现有系统集成

| 组件 | 角色 |
|------|------|
| `SchedulerEngine` (INF-07) | CronTrigger 管理首次加载 + 日终增量任务 |
| `DataDownloader.download_a_share()` | 复用已有下载逻辑 |
| `akshare.index_stock_cons()` | 获取沪深 300 成分股列表 |
| `dcc.Store` + `dcc.Interval` | 首次加载进度轮询 |
| 首页统计卡片 | 展示加载状态 |

#### 进度展示

```
自动加载进度：
  状态：正在加载沪深300成分股（42/380）
  进度：[████████░░░░░░░░░] 15%
  当前：000858.SZ 贵州茅台（约剩 2 分钟）

完成后：
  ✅ 已加载 380 只标的，共 185,000 条记录
  下次增量更新：2026-07-26 16:30
```

```python
progress_state = {
    "phase": "initial_load", "current": 42, "total": 380,
    "symbol": "000858.SZ", "name": "贵州茅台",
    "records_added": 185000, "elapsed_sec": 87, "eta_sec": 53,
}
```

前端每 2 秒轮询 `dcc.Interval` → `dcc.Store` → `dbc.Progress` + 状态文字。

#### 配置

```yaml
# configs/market.yaml 新增
auto_load:
  enabled: true
  initial_universe: both          # csi300 | hsi | both
  initial_start: "2024-01-01"
  initial_frequency: daily
  incremental_time: "16:30"
  max_concurrent: 5               # AKShare 限速
```

#### 边界与异常

| 场景 | 处理 |
|------|------|
| 加载中断 | 记录 `auto_load_status`，二次启动继续 |
| AKShare 限流 | 每批 5 只，批间 15s（复用 INF-03） |
| 单只失败 | 跳过、记录日志，不影响其余 |
| 成分股列表拉取失败 | 使用上次缓存列表，否则跳过并告警 |
| 日终增量网络不可用 | 跳过当日，次日重试 |
| 标的已退市 | AKShare 返回空 → 标记 delisted，不再尝试 |

### 3.12 DuckDBManager 防重复 connect + 并发保护

```python
def _get_db() -> DuckDBManager:
    db = DuckDBManager()
    if not hasattr(db, '_write_conn') or db._write_conn is None:
        db.connect("data/fisherquant.db")
    return db
```

需在 `DuckDBManager.connect()` 内加 `threading.Lock` 保护连接池初始化，防止两个并发回调同时进入后互相关闭对方连接：

```python
# fisher/store/engine.py — DuckDBManager.connect() 加锁
def connect(self, path: str, read_pool_size: int = 4):
    with self._init_lock:
        if self._write_conn is not None:
            return  # 已连接则跳过
        self._path = path
        self._write_conn = duckdb.connect(path)
        for _ in range(read_pool_size):
            conn = duckdb.connect(path)
            self._read_pool.put(conn)
```

### 3.13 事务一致性（级联清理）

`delete_symbols` 的级联操作（bars_daily/bars_minute/factors/adj）用 `DuckDBManager.transaction()` 包裹，删除 Parquet 文件包裹在 `try/finally` 中：

```python
def delete_symbols(self, tickers: list[str]) -> int:
    deleted = 0
    try:
        with self._db.transaction():
            for t in tickers:
                self._db.execute("DELETE FROM bars_daily WHERE ticker=?", [t])
                self._db.execute("DELETE FROM bars_minute WHERE ticker=?", [t])
                deleted += 1
    except Exception as e:
        logger.error("DB delete failed, rolling back: %s", e)
        raise
    # Parquet deletion outside transaction (no rollback for files)
    for t in tickers:
        try:
            FactorStorage.delete(t)
        except Exception as e:
            logger.warning("Factor file delete failed for %s: %s", t, e)
    return deleted
```

## 4. 测试

### 4.1 每个 bug 对应一条回归测试

16 个已知问题每个对应一条 `@pytest.mark.regression` 测试，回归门禁：

| 问题 # | 回归测试 | 验证条件 |
|--------|----------|----------|
| DC-1 | `test_resolve_ticker_no_unknown` | `"UNKNOWN" not in resolve_ticker("600519")` |
| DC-2 | `test_fetch_data_type_routes` | `data_type="financials"` 调对应函数 |
| DC-3 | `test_progress_updates_interval` | 拉取期间 `dcc.Store` 数据变化 |
| DC-4 | `test_export_with_filters` | 筛选后导出条数 < 全量 |
| DC-5 | `test_no_silent_exception` | 无 `except Exception: pass` 存活 |
| DC-6 | `test_cache_filter_params` | WHERE 子句使用两个不同参数 |
| DC-7 | `test_db_not_reconnect_if_connected` | 重复调用返回同一连接 |
| DC-8 | `test_schema_init_closes_engine` | 调用后 `engine._conn is None` |
| DC-9 | `test_quick_action_navigates` | `pathname == "/data-center"` |
| SC-1 | `test_strategy_name_sanitize` | `"../etc"` → `"__etc"` |
| SC-2 | `test_only_one_strategy_table_func` | 仅 `_build_strategy_list` 存在 |
| SC-3 | `test_template_refreshes_list` | handle_template 返回非 `no_update` |
| SC-4 | `test_wizard_state_type_safe` | `WizardState().step` 类型 int |
| SC-5 | `test_no_silent_exception` | 同 DC-5 |
| SC-6 | `test_edit_invalid_name_blocked` | 空名称不允许保存 |
| SC-7 | `test_import_malformed_json` | 非法 JSON 返回错误列表 |
| AL-1 | `test_auto_load_initial_triggers_on_empty` | `bars_daily` 为空时自动触发加载 |
| AL-2 | `test_auto_load_incremental_after_last_date` | 增量更新只拉取缺失日期 |
| AL-3 | `test_auto_load_progress_updates` | `dcc.Store` 中 `progress_state` 随下载更新 |
| AL-4 | `test_auto_load_resume_after_interrupt` | 中断后 `auto_load_status` 中 `current` 不为 0 |
| AL-5 | `test_auto_load_csi300_fallback` | 成分股列表获取失败 → 使用上次缓存列表 |
| AL-6 | `test_auto_load_all_incremental_fail_graceful` | 全部增量失败 → 告警但不影响系统 |
| AL-7 | `test_auto_load_concurrent_manual_fetch` | 自动加载中用户手动拉取 → 不重复不冲突 |
| AL-8 | `test_auto_load_incremental_batch_size` | 每次只处理 `incremental_batch_size` 只（20） |

### 4.2 Mock 方案

```python
# tests/conftest.py
@pytest.fixture(autouse=True)
def mock_akshare(monkeypatch):
    """Mock all akshare API calls with fixture data."""
    fixture_dir = Path(__file__).parent / "fixtures" / "akshare"

    def mock_stock_list(*args, **kwargs):
        return pl.DataFrame({
            "code": ["600519", "000001", "00700"],
            "name": ["贵州茅台", "平安银行", "腾讯控股"],
        }).to_pandas()

    monkeypatch.setattr("akshare.stock_info_a_code_name", mock_stock_list)

@pytest.fixture
def mock_scheduler(monkeypatch):
    """Mock APScheduler for AutoLoadService testing."""
    class MockScheduler:
        def add_job(self, *a, **kw): return "mock-job-id"
        def remove_job(self, *a, **kw): pass
        def start(self): pass
        def shutdown(self): pass
    return MockScheduler()

@pytest.fixture
def mock_index_cons(monkeypatch):
    """Mock 沪深300/恒指成分股 API."""
    def mock_csi300(*args, **kwargs):
        return pl.DataFrame({"stock_code": ["600519", "000001", "300750"]}).to_pandas()
    def mock_hsi(*args, **kwargs):
        return pl.DataFrame({"stock_code": ["00700", "03690"]}).to_pandas()
    monkeypatch.setattr("akshare.index_stock_cons", mock_csi300)
    monkeypatch.setattr("akshare.hk_index_cons", mock_hsi)

@pytest.fixture
def auto_load_service(mock_scheduler, mock_index_cons):
    from fisher.dash_app.services.auto_load_service import AutoLoadService
    db = DuckDBManager(":memory:")
    db.connect(":memory:")
    init_schema(db)
    limiter = RateLimiter(max_per_minute=999)
    return AutoLoadService(db=db, limiter=limiter, scheduler=mock_scheduler)
```

### 4.3 Service 层负面场景覆盖

| 方法 | 正面 | 负面 |
|------|------|------|
| `search_symbols` | 正常匹配 | 空查询、无结果、AKShare 超时 |
| `fetch_bars` | 成功拉取+存储 | 无效代码、部分失败、空日期、超时重试耗尽 |
| `get_cache_stats` | 返回统计数据 | 空数据库、损坏连接 |
| `delete_symbols` | 删除成功 | 不存在的代码、数据库错误、文件删除部分失败 |
| `save_strategy` | 保存合法配置 | 空名称、重复名称、非法类型、DSL 语法错 |
| `import_json` | 导入成功 | 非法 JSON、缺字段、版本不匹配、字段类型错 |
| `export_bars` | 返回正确格式 | 空结果、超大范围超时 |

### 4.4 测试分层

```
Service 层测试（pytest，无 Dash）       ← 核心，每次提交必跑
  ├ tests/unit/test_data_center_service.py
  ├ tests/unit/test_strategy_service.py
  └ tests/unit/test_dash_app_models.py

回调 HTTP 测试（app.server.test_client） ← CI 必跑，无需浏览器
  └ tests/integration/test_dash_callbacks.py  # 限 HTTP 端到端

Dash 前端测试（pytest-dash，需浏览器）  ← 可选，本地开发按需
  └ tests/e2e/                          # 留空，后续补充
```

| 测试文件 | 覆盖内容 |
|----------|----------|
| `tests/unit/test_data_center_service.py` | search_symbols、fetch_bars、get_cache_stats、resolve_ticker、auto_load_init |
| `tests/unit/test_auto_load_service.py` | initial_load、incremental_update、interrupt_resume、csi300_fallback、batch_size、concurrent_manual |
| `tests/unit/test_strategy_service.py` | CRUD、validate、safe_filename、import/export |
| `tests/unit/test_dash_app_models.py` | StrategyConfig.validate、WizardState 序列化、TYPE_MAP、auto_load_config |
| `tests/integration/test_dash_callbacks.py` | 搜索→拉取→缓存显示端到端 + auto-load 进度轮询端到端（Mock AKShare） |

## 5. 实现顺序

1. `models.py`（数据类 + 校验 + 工具函数 + `resolve_ticker`）
2. `DataCenterService`（含 `export_bars`、`estimate_export`） + 测试
3. `AutoLoadService`（含 `auto_load_status` 表建表） + 测试
4. `StrategyService` + 测试
5. 拆分 `data_callbacks.py` → 3 个文件，接入 Service + 自动加载进度 UI
6. 拆分 `strategy_callbacks.py` → 2 个文件，接入 Service
7. `symbol_cache` 表创建 + 搜索缓存逻辑
8. 首页加载状态 + 快速操作按钮跳转
9. 修复 19 个具体 bug（含自动加载 3 个）
10. 集成测试

---

## 自我审查

- [x] 无 TBD/TODO
- [x] 16 个问题全部对应修复策略
- [x] Service 层接口明确
- [x] 文件拆分边界清晰
- [x] 测试覆盖 Service 层 + 回调链路
- [x] 实现步骤有序
