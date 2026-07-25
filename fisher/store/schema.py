from .engine import DuckDBEngine

SCHEMA_VERSION = 1

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
        ticker VARCHAR NOT NULL,
        ts TIMESTAMP NOT NULL,
        last_price DOUBLE,
        open DOUBLE,
        high DOUBLE,
        low DOUBLE,
        volume BIGINT,
        amount DOUBLE,
        pre_close DOUBLE,
        market VARCHAR DEFAULT 'a_share',
        PRIMARY KEY (ticker, ts)
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


def migrate(engine: DuckDBEngine) -> None:
    row = engine.query_df("SELECT MAX(version) AS v FROM schema_version")
    current = row["v"][0] or 0
    if current < SCHEMA_VERSION:
        init_schema(engine)
