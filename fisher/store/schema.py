import logging

from .engine import DuckDBEngine

SCHEMA_VERSION = 6

# 标的搜索 V1.2（PRD FR-4.x）：只读标的字典表，替代旧 symbol_cache。
# - ticker 为标准化主键（600519.SH / 00700.HK，港股零填充 5 位，见 R-01）
# - pinyin_full / pinyin_abbr 由刷新服务离线生成（R-14），搜索链路只读
# - updated_at 用于展示"字典更新时间"统计条（FR-3.x）
_SYMBOL_DICT_DDL = """
    CREATE TABLE IF NOT EXISTS symbol_dict (
        ticker VARCHAR NOT NULL,
        code VARCHAR NOT NULL,
        name VARCHAR NOT NULL,
        market VARCHAR NOT NULL,
        pinyin_full VARCHAR DEFAULT '',
        pinyin_abbr VARCHAR DEFAULT '',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ticker)
    )
"""

# 自动加载 V1.3（PRD FR-2.x）：标的级状态账本，DB as Source of Truth 的续传定位键。
# - ticker 为主键（替代旧版基于位置索引的游标）
# - session_id 标识一次加载会话（开始/重新加载生成新会话；继续复用旧会话）
# - plan ∈ {FULL, GAP, SKIP}，status ∈ {pending, loading, done, failed}
# - gap_start 为缺口起点（GAP 补 `MAX(trade_date)+1 ~ 今天`）；attempts/last_error 支撑失败重试
_SYMBOL_LOAD_STATE_DDL = """
    CREATE TABLE IF NOT EXISTS symbol_load_state (
        ticker VARCHAR NOT NULL,
        session_id VARCHAR NOT NULL,
        plan VARCHAR NOT NULL,
        status VARCHAR NOT NULL,
        gap_start DATE,
        attempts INTEGER DEFAULT 0,
        last_error VARCHAR,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ticker)
    )
"""

# --- v5 新增 DDL 常量（缓存数据类型扩展 V1.4，PRD §7）---
# cache_catalog：联动中枢，逐标的 × 5 类数据资产覆盖度 + 时间边界 + 自动加载开关。
_CACHE_CATALOG_DDL = """
    CREATE TABLE IF NOT EXISTS cache_catalog (
        ticker            VARCHAR PRIMARY KEY,
        market            VARCHAR,
        name              VARCHAR,
        has_daily         BOOLEAN DEFAULT FALSE,
        has_minute        BOOLEAN DEFAULT FALSE,
        has_realtime      BOOLEAN DEFAULT FALSE,
        has_adj           BOOLEAN DEFAULT FALSE,
        has_financials    BOOLEAN DEFAULT FALSE,
        auto_load_enabled BOOLEAN DEFAULT FALSE,
        daily_start       DATE,
        daily_end         DATE,
        minute_start      TIMESTAMP,
        minute_end        TIMESTAMP,
        minute_periods    VARCHAR,
        realtime_ts       TIMESTAMP,
        adj_type          VARCHAR,
        fin_report_end    DATE,
        last_update       TIMESTAMP,
        updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""

_ADJ_FACTORS_DDL = """
    CREATE TABLE IF NOT EXISTS adj_factors (
        ticker     VARCHAR NOT NULL,
        trade_date DATE NOT NULL,
        adj_type   VARCHAR NOT NULL,
        adj_factor DOUBLE NOT NULL,
        PRIMARY KEY (ticker, trade_date, adj_type)
    )
"""

_FINANCIALS_DDL = """
    CREATE TABLE IF NOT EXISTS financials (
        ticker      VARCHAR NOT NULL,
        report_date DATE NOT NULL,
        report_type VARCHAR,
        indicator   VARCHAR NOT NULL,
        value       DOUBLE,
        unit        VARCHAR,
        PRIMARY KEY (ticker, report_date, indicator)
    )
"""

# 此处用 IF NOT EXISTS 创建新主键 (ticker, ts) 的 snapshots。
# 对全新库直接建新表；对存量 v4 库旧 snapshots（id BIGINT PK）已存在故 IF NOT EXISTS 跳过，
# 真正重建发生在 _MIGRATIONS[5] 的 DROP+CREATE（带空表断言保护，见验收 17）。
_SNAPSHOTS_DDL = """
    CREATE TABLE IF NOT EXISTS snapshots (
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
    )
"""

# 目录聚合视图：供缓存目录页按类型统计条数（FR-8.2）与看板健康度共用。
_CACHE_SUMMARY_VIEW_DDL = """
    CREATE OR REPLACE VIEW v_cache_summary AS
    SELECT
        c.ticker,
        COALESCE(s.name, c.name) AS name,
        c.market, c.auto_load_enabled,
        c.has_daily, c.has_minute, c.has_realtime, c.has_adj, c.has_financials,
        c.daily_start, c.daily_end, c.realtime_ts, c.minute_periods,
        (SELECT COUNT(*) FROM bars_daily d WHERE d.ticker = c.ticker)  AS daily_rows,
        (SELECT COUNT(*) FROM bars_minute m WHERE m.ticker = c.ticker) AS minute_rows,
        (SELECT COUNT(*) FROM snapshots  s WHERE s.ticker = c.ticker)  AS realtime_rows,
        (SELECT COUNT(*) FROM adj_factors a WHERE a.ticker = c.ticker) AS adj_rows,
        (SELECT COUNT(*) FROM financials f WHERE f.ticker = c.ticker)  AS fin_rows
    FROM cache_catalog c
    LEFT JOIN symbol_dict s ON s.ticker = c.ticker
"""


_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY,
        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bars_daily (
        ticker VARCHAR NOT NULL,
        trade_date DATE NOT NULL,
        open DOUBLE NOT NULL,
        high DOUBLE NOT NULL,
        low DOUBLE NOT NULL,
        close DOUBLE NOT NULL,
        volume BIGINT NOT NULL,
        amount DOUBLE NOT NULL,
        market VARCHAR DEFAULT 'a_share',
        adj_factor DOUBLE DEFAULT 1.0,
        PRIMARY KEY (ticker, trade_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bars_minute (
        ticker VARCHAR NOT NULL,
        period VARCHAR NOT NULL DEFAULT '5',
        bar_time TIMESTAMP NOT NULL,
        open DOUBLE NOT NULL,
        high DOUBLE NOT NULL,
        low DOUBLE NOT NULL,
        close DOUBLE NOT NULL,
        volume BIGINT NOT NULL,
        amount DOUBLE NOT NULL,
        market VARCHAR DEFAULT 'a_share',
        PRIMARY KEY (ticker, period, bar_time)
    )
    """,
    _CACHE_CATALOG_DDL,
    "ALTER TABLE cache_catalog ADD COLUMN IF NOT EXISTS minute_periods VARCHAR",
    _ADJ_FACTORS_DDL,
    _FINANCIALS_DDL,
    _SNAPSHOTS_DDL,
    "ALTER TABLE bars_minute ADD COLUMN IF NOT EXISTS period VARCHAR DEFAULT '5'",
    """
    CREATE TABLE IF NOT EXISTS orders (
        order_id VARCHAR PRIMARY KEY,
        ticker VARCHAR NOT NULL,
        side VARCHAR NOT NULL,
        quantity INTEGER NOT NULL,
        price DOUBLE,
        filled_qty INTEGER DEFAULT 0,
        filled_price DOUBLE,
        commission DOUBLE DEFAULT 0.0,
        status VARCHAR DEFAULT 'new',
        order_type VARCHAR DEFAULT 'limit',
        market VARCHAR DEFAULT 'a_share',
        asset_type VARCHAR DEFAULT 'stock',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS positions (
        ticker VARCHAR NOT NULL,
        market VARCHAR DEFAULT 'a_share',
        asset_type VARCHAR DEFAULT 'stock',
        quantity INTEGER DEFAULT 0,
        avg_cost DOUBLE DEFAULT 0.0,
        market_value DOUBLE DEFAULT 0.0,
        unrealized_pnl DOUBLE DEFAULT 0.0,
        frozen INTEGER DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (ticker)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS position_snapshots (
        date DATE NOT NULL,
        ticker VARCHAR NOT NULL,
        market VARCHAR DEFAULT 'a_share',
        quantity INTEGER NOT NULL,
        avg_cost DOUBLE NOT NULL,
        close_price DOUBLE NOT NULL,
        market_value DOUBLE NOT NULL,
        PRIMARY KEY (date, ticker)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS corporate_actions (
        ticker VARCHAR NOT NULL,
        event_date DATE NOT NULL,
        event_type VARCHAR NOT NULL,
        cash_per_share DOUBLE DEFAULT 0.0,
        bonus_ratio DOUBLE DEFAULT 0.0,
        split_ratio DOUBLE DEFAULT 1.0,
        PRIMARY KEY (ticker, event_date, event_type)
    )
    """,
    _SYMBOL_DICT_DDL,
    _SYMBOL_LOAD_STATE_DDL,
    # 视图引用 symbol_dict，必须在其之后创建（symbol_dict 见上）
    _CACHE_SUMMARY_VIEW_DDL,
]


def init_schema(engine: DuckDBEngine) -> None:
    for ddl in _TABLES:
        engine.execute(ddl)

    existing = engine.query_df("SELECT COUNT(*) AS c FROM schema_version")
    if existing["c"][0] == 0:
        engine.execute(
            "INSERT INTO schema_version (version) VALUES (?)",
            [SCHEMA_VERSION],
        )

    _backfill_cache_catalog(engine)


def _backfill_cache_catalog(engine: DuckDBEngine) -> None:
    """v5 存量回填：老库升级后 cache_catalog 为空，但 bars_daily/bars_minute 已有数据。

    仅在「catalog 为空且 bars_daily 非空」时执行一次（幂等、启动路径零成本）；
    名称优先取 symbol_dict，缺失时以 ticker 兜底（与 record_coverage 口径一致）。
    """
    try:
        cat = engine.query_df("SELECT COUNT(*) AS c FROM cache_catalog")["c"][0]
        bars = engine.query_df("SELECT COUNT(*) AS c FROM bars_daily")["c"][0]
        if int(cat or 0) > 0 or int(bars or 0) == 0:
            return
        engine.execute(
            """
            INSERT OR IGNORE INTO cache_catalog
                (ticker, market, name, has_daily, daily_start, daily_end)
            SELECT d.ticker,
                   COALESCE(MAX(d.market), 'a_share'),
                   COALESCE(MAX(s.name), d.ticker),
                   TRUE, MIN(d.trade_date), MAX(d.trade_date)
            FROM bars_daily d
            LEFT JOIN symbol_dict s ON s.ticker = d.ticker
            GROUP BY d.ticker
            """
        )
        engine.execute(
            """
            UPDATE cache_catalog SET has_minute = TRUE,
                   minute_start = agg.mn, minute_end = agg.mx
            FROM (SELECT ticker, MIN(bar_time) AS mn, MAX(bar_time) AS mx
                  FROM bars_minute GROUP BY ticker) agg
            WHERE cache_catalog.ticker = agg.ticker
            """
        )
    except Exception:  # 回填失败不阻塞启动（目录可由后续写路径自愈）
        logging.getLogger(__name__).warning("cache_catalog 存量回填失败", exc_info=True)


_MIGRATIONS: dict[int, list[str]] = {
    2: [
        "ALTER TABLE bars_daily ADD COLUMN IF NOT EXISTS turnover DOUBLE DEFAULT 0.0",
        "ALTER TABLE bars_minute ADD COLUMN IF NOT EXISTS turnover DOUBLE DEFAULT 0.0",
    ],
    # V1.2 标的搜索：新增 symbol_dict（R-10）。旧 symbol_cache 保留不删，
    # 供 legacy 回滚开关（R-50）使用；待 V1.2 稳定后再由后续版本清理。
    3: [
        _SYMBOL_DICT_DDL,
    ],
    # V1.3 自动加载：新增 symbol_load_state 账本表（R-01）。
    # 注意：生产启动路径只调用 init_schema()（见 services/__init__.py:get_db），
    # 不会调用本 migrate()，故该表已同时加入 _TABLES 以保证新建库即时建表；
    # 本条目保留用于显式迁移工具 / 历史库升级。
    4: [
        _SYMBOL_LOAD_STATE_DDL,
    ],
    # V1.4 缓存数据类型扩展：重建 snapshots 主键为 (ticker, ts)（空表断言见 migrate 守卫）；
    # cache_catalog/adj_factors/financials 视图与 period 列已由 init_schema 的 _TABLES 兜底建好，
    # 此处幂等重建以保证存量库与全新库最终一致。
    5: [
        "DROP TABLE IF EXISTS snapshots",
        _SNAPSHOTS_DDL,
        _CACHE_CATALOG_DDL,
        _ADJ_FACTORS_DDL,
        _FINANCIALS_DDL,
        _CACHE_SUMMARY_VIEW_DDL,
        "ALTER TABLE bars_minute ADD COLUMN IF NOT EXISTS period VARCHAR DEFAULT '5'",
    ],
    # v6：bars_minute 多周期主键扩展（见 migrate 中 _migrate_bars_minute_pk 事务重建）
    6: [],
}


def _bars_minute_pk_has_period(engine: DuckDBEngine) -> bool:
    """检测 bars_minute 主键是否已含 period（v6 迁移是否已应用）。"""
    try:
        rows = engine.query_df(
            "SELECT constraint_text FROM duckdb_constraints() "
            "WHERE table_name='bars_minute' AND constraint_type='PRIMARY KEY'")
        if len(rows) == 0:
            return False
        return "period" in str(rows["constraint_text"][0])
    except Exception:
        return False


def _migrate_bars_minute_pk(conn) -> None:
    """v6：bars_minute 主键 (ticker,bar_time) -> (ticker,period,bar_time)。

    DuckDB 不支持 ALTER PRIMARY KEY，故在事务内重建新表（存量 period 统一回填 '5'）、
    DROP 旧表、RENAME 新表；v_cache_summary 视图按名解析，DROP+RENAME 后自动恢复。
    在整个事务内完成，失败回滚，可幂等重放（优先由 _bars_minute_pk_has_period 跳过）。
    """
    conn.execute(
        """
        CREATE OR REPLACE TABLE bars_minute_new (
            ticker VARCHAR NOT NULL,
            period VARCHAR NOT NULL DEFAULT '5',
            bar_time TIMESTAMP NOT NULL,
            open DOUBLE NOT NULL,
            high DOUBLE NOT NULL,
            low DOUBLE NOT NULL,
            close DOUBLE NOT NULL,
            volume BIGINT NOT NULL,
            amount DOUBLE NOT NULL,
            market VARCHAR DEFAULT 'a_share',
            PRIMARY KEY (ticker, period, bar_time)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO bars_minute_new
            (ticker, period, bar_time, open, high, low, close, volume, amount, market)
        SELECT ticker, COALESCE(period, '5'), bar_time, open, high, low, close,
               volume, amount, market
        FROM bars_minute
        """
    )
    conn.execute("DROP TABLE bars_minute")
    conn.execute("ALTER TABLE bars_minute_new RENAME TO bars_minute")


def migrate(engine: DuckDBEngine) -> None:
    row = engine.query_df("SELECT MAX(version) AS v FROM schema_version")
    current = row["v"][0] or 0
    # v5 迁移将重建 snapshots 主键，须先断言存量快照为空，避免误删真实数据（验收 17）
    if current < 5:
        try:
            cnt = engine.query_df("SELECT COUNT(*) AS c FROM snapshots")["c"][0]
        except Exception:
            cnt = 0
        if cnt and int(cnt) > 0:
            raise RuntimeError(
                f"snapshots 存量 {int(cnt)} 行非空，拒绝 v5 主键重建迁移；"
                "请先导出/清理快照后再升级。"
            )
    if current < SCHEMA_VERSION:
        init_schema(engine)

    current_after_init = engine.query_df("SELECT MAX(version) AS v FROM schema_version")
    current = current_after_init["v"][0] or 0

    for version in sorted(_MIGRATIONS.keys()):
        if version <= current:
            continue
        # v6：bars_minute 主键扩展为复合键，需重建表；DuckDB 不支持 ALTER PRIMARY KEY
        if version == 6:
            if _bars_minute_pk_has_period(engine):
                engine.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", [version])
            else:
                with engine.transaction() as conn:
                    _migrate_bars_minute_pk(conn)
                engine.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", [version])
            current = version
            continue
        for ddl in _MIGRATIONS[version]:
            engine.execute(ddl)
        engine.execute(
            "INSERT INTO schema_version (version) VALUES (?)",
            [version],
        )
        current = version
