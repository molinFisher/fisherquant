from .engine import DuckDBEngine

SCHEMA_VERSION = 4

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
        bar_time TIMESTAMP NOT NULL,
        open DOUBLE NOT NULL,
        high DOUBLE NOT NULL,
        low DOUBLE NOT NULL,
        close DOUBLE NOT NULL,
        volume BIGINT NOT NULL,
        amount DOUBLE NOT NULL,
        market VARCHAR DEFAULT 'a_share',
        PRIMARY KEY (ticker, bar_time)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS snapshots (
        id BIGINT PRIMARY KEY,
        ticker VARCHAR NOT NULL,
        ts TIMESTAMP NOT NULL,
        last_price DOUBLE,
        open DOUBLE,
        high DOUBLE,
        low DOUBLE,
        volume BIGINT,
        amount DOUBLE,
        pre_close DOUBLE,
        market VARCHAR DEFAULT 'a_share'
    )
    """,
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
}


def migrate(engine: DuckDBEngine) -> None:
    row = engine.query_df("SELECT MAX(version) AS v FROM schema_version")
    current = row["v"][0] or 0
    if current < SCHEMA_VERSION:
        init_schema(engine)

    current_after_init = engine.query_df("SELECT MAX(version) AS v FROM schema_version")
    current = current_after_init["v"][0] or 0

    for version in sorted(_MIGRATIONS.keys()):
        if version <= current:
            continue
        for ddl in _MIGRATIONS[version]:
            engine.execute(ddl)
        engine.execute(
            "INSERT INTO schema_version (version) VALUES (?)",
            [version],
        )
        current = version
