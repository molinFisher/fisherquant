import tempfile
from pathlib import Path
from fisher.store.engine import DuckDBEngine
from fisher.store.schema import init_schema, migrate, SCHEMA_VERSION


class TestInitSchema:
    def test_creates_all_tables(self):
        with tempfile.TemporaryDirectory() as d:
            engine = DuckDBEngine(str(Path(d) / "test.db"))
            init_schema(engine)

            tables = engine.query_df(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
            )
            table_names = set(tables["table_name"].to_list())
            expected = {
                "schema_version", "bars_daily", "bars_minute",
                "snapshots", "orders", "positions",
                "corporate_actions", "position_snapshots",
            }
            assert expected.issubset(table_names)

    def test_sets_schema_version(self):
        with tempfile.TemporaryDirectory() as d:
            engine = DuckDBEngine(str(Path(d) / "test.db"))
            init_schema(engine)

            row = engine.query_df("SELECT version FROM schema_version")
            assert row["version"][0] == SCHEMA_VERSION

    def test_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            engine = DuckDBEngine(str(Path(d) / "test.db"))
            init_schema(engine)
            init_schema(engine)

            row = engine.query_df("SELECT COUNT(*) AS c FROM schema_version")
            assert row["c"][0] == 1


class TestBarsDailyTable:
    def test_insert_and_query_bars_daily(self):
        with tempfile.TemporaryDirectory() as d:
            engine = DuckDBEngine(str(Path(d) / "test.db"))
            init_schema(engine)

            engine.execute("""
                INSERT INTO bars_daily (ticker, trade_date, open, high, low, close, volume, amount, market)
                VALUES ('000001.SZ', '2025-01-02', 10.0, 11.0, 9.8, 10.5, 1000000, 10500000, 'a_share')
            """)

            result = engine.query_df(
                "SELECT ticker, close, volume FROM bars_daily WHERE ticker='000001.SZ'"
            )
            assert len(result) == 1
            assert result["close"][0] == 10.5


class TestOrdersTable:
    def test_insert_and_query_order(self):
        with tempfile.TemporaryDirectory() as d:
            engine = DuckDBEngine(str(Path(d) / "test.db"))
            init_schema(engine)

            engine.execute("""
                INSERT INTO orders (order_id, ticker, side, quantity, price, status, market, asset_type)
                VALUES ('oid-1', '000001.SZ', 'buy', 100, 10.5, 'pending', 'a_share', 'stock')
            """)

            result = engine.query_df("SELECT status FROM orders WHERE order_id='oid-1'")
            assert result["status"][0] == "pending"


class TestMigration:
    def test_migration_to_v2_adds_turnover_column(self):
        with tempfile.TemporaryDirectory() as d:
            engine = DuckDBEngine(str(Path(d) / "test.db"))
            init_schema(engine)
            engine.execute("DELETE FROM schema_version")
            engine.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                [1],
            )
            migrate(engine)
            row = engine.query_df("SELECT MAX(version) AS v FROM schema_version")
            assert row["v"][0] >= 2
            cols = engine.query_df(
                "SELECT column_name FROM information_schema.columns WHERE table_name='bars_daily'"
            )
            col_names = set(cols["column_name"].to_list())
            assert "turnover" in col_names


class TestSchemaV5CacheCatalog:
    def test_init_schema_creates_v5_assets(self):
        with tempfile.TemporaryDirectory() as d:
            engine = DuckDBEngine(str(Path(d) / "test.db"))
            init_schema(engine)
            row = engine.query_df("SELECT MAX(version) AS v FROM schema_version")
            assert row["v"][0] == SCHEMA_VERSION

            tables = engine.query_df(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
            )
            names = set(tables["table_name"].to_list())
            assert {"cache_catalog", "adj_factors", "financials"} <= names
            assert "v_cache_summary" in names

    def test_bars_minute_has_period_column(self):
        with tempfile.TemporaryDirectory() as d:
            engine = DuckDBEngine(str(Path(d) / "test.db"))
            init_schema(engine)
            cols = engine.query_df(
                "SELECT column_name FROM information_schema.columns WHERE table_name='bars_minute'"
            )
            assert "period" in set(cols["column_name"].to_list())

    def test_snapshots_new_pk_and_change_pct(self):
        with tempfile.TemporaryDirectory() as d:
            engine = DuckDBEngine(str(Path(d) / "test.db"))
            init_schema(engine)
            cols = engine.query_df(
                "SELECT column_name FROM information_schema.columns WHERE table_name='snapshots'"
            )
            col_names = set(cols["column_name"].to_list())
            assert "change_pct" in col_names
            assert "id" not in col_names
            # 新主键为 (ticker, ts)，可幂等 upsert
            engine.execute(
                "INSERT INTO snapshots (ticker, ts, last_price, change_pct) VALUES ('600519.SH', '2025-01-02 09:31:00', 1500.0, 1.2)"
            )
            engine.execute(
                "INSERT OR REPLACE INTO snapshots (ticker, ts, last_price, change_pct) VALUES ('600519.SH', '2025-01-02 09:31:00', 1510.0, 1.8)"
            )
            n = engine.query_df("SELECT COUNT(*) AS c FROM snapshots")["c"][0]
            assert n == 1

    def test_migrate_v4_rebuilds_snapshots_pk(self):
        with tempfile.TemporaryDirectory() as d:
            engine = DuckDBEngine(str(Path(d) / "test.db"))
            # 模拟 v4 库：旧 snapshots 主键为 id
            engine.execute(
                "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
            engine.execute("INSERT INTO schema_version (version) VALUES (4)")
            engine.execute(
                "CREATE TABLE snapshots (id BIGINT PRIMARY KEY, ticker VARCHAR, ts TIMESTAMP, last_price DOUBLE)"
            )
            migrate(engine)
            row = engine.query_df("SELECT MAX(version) AS v FROM schema_version")
            assert row["v"][0] == SCHEMA_VERSION
            cols = engine.query_df(
                "SELECT column_name FROM information_schema.columns WHERE table_name='snapshots'"
            )
            col_names = set(cols["column_name"].to_list())
            assert "change_pct" in col_names and "id" not in col_names

    def test_migrate_refuses_nonempty_snapshots(self):
        with tempfile.TemporaryDirectory() as d:
            engine = DuckDBEngine(str(Path(d) / "test.db"))
            engine.execute(
                "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
            engine.execute("INSERT INTO schema_version (version) VALUES (4)")
            engine.execute(
                "CREATE TABLE snapshots (id BIGINT PRIMARY KEY, ticker VARCHAR, ts TIMESTAMP, last_price DOUBLE)"
            )
            engine.execute(
                "INSERT INTO snapshots (id, ticker, ts) VALUES (1, '600519.SH', now())"
            )
            import pytest

            with pytest.raises(RuntimeError):
                migrate(engine)


class TestSchemaV6MultiPeriodMinute:
    def test_bars_minute_pk_includes_period(self):
        """v6 多周期分钟线：bars_minute 主键为 (ticker,period,bar_time)，
        同 bar_time 不同 period 可并存（FR-2.1 / 风险#4）。"""
        with tempfile.TemporaryDirectory() as d:
            engine = DuckDBEngine(str(Path(d) / "test.db"))
            init_schema(engine)
            pk = engine.query_df(
                "SELECT constraint_text FROM duckdb_constraints() "
                "WHERE table_name='bars_minute' AND constraint_type='PRIMARY KEY'"
            )["constraint_text"][0]
            assert "period" in pk and "ticker" in pk and "bar_time" in pk

            ts = "2025-01-02 09:35:00"
            engine.execute(
                "INSERT INTO bars_minute "
                "(ticker, period, bar_time, open, high, low, close, volume, amount, market) "
                "VALUES ('600519.SH','5',?,1.0,1.0,1.0,1.0,1,1.0,'a_share')", [ts])
            engine.execute(
                "INSERT INTO bars_minute "
                "(ticker, period, bar_time, open, high, low, close, volume, amount, market) "
                "VALUES ('600519.SH','1',?,2.0,2.0,2.0,2.0,2,2.0,'a_share')", [ts])
            n = engine.query_df(
                "SELECT COUNT(*) c FROM bars_minute WHERE ticker='600519.SH'")["c"][0]
            assert n == 2  # 不同周期共存，不再键冲突

    def test_migrate_v5_rebuilds_bars_minute_pk(self):
        """v5 存量库升级：bars_minute 主键 (ticker,bar_time) -> (ticker,period,bar_time)，
        存量数据保留且 period 回填 '5'，v_cache_summary 视图仍可查，可幂等重放。"""
        with tempfile.TemporaryDirectory() as d:
            engine = DuckDBEngine(str(Path(d) / "test.db"))
            init_schema(engine)  # 先按当前 schema 建库（新主键 + version 6）
            # 模拟 v5 旧库：把 bars_minute 降级为旧主键，版本写回 5
            engine.execute("DROP TABLE bars_minute")
            engine.execute(
                "CREATE TABLE bars_minute ("
                "ticker VARCHAR NOT NULL, bar_time TIMESTAMP NOT NULL, open DOUBLE, "
                "high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT, amount DOUBLE, "
                "market VARCHAR DEFAULT 'a_share', period VARCHAR DEFAULT '5', "
                "PRIMARY KEY (ticker, bar_time))")
            engine.execute(
                "INSERT INTO bars_minute VALUES "
                "('600519.SH','2024-01-02 09:35:00',1.0,1.0,1.0,1.0,1,1.0,'a_share','5')")
            engine.execute("DELETE FROM schema_version")
            engine.execute("INSERT INTO schema_version (version) VALUES (5)")
            engine.close()

            e2 = DuckDBEngine(str(Path(d) / "test.db"))
            migrate(e2)
            assert e2.query_df("SELECT MAX(version) v FROM schema_version")["v"][0] == 6
            pk = e2.query_df(
                "SELECT constraint_text FROM duckdb_constraints() "
                "WHERE table_name='bars_minute' AND constraint_type='PRIMARY KEY'"
            )["constraint_text"][0]
            assert "period" in pk
            # 存量行保留且 period 回填 '5'
            assert e2.query_df(
                "SELECT COUNT(*) c FROM bars_minute WHERE ticker='600519.SH'")["c"][0] == 1
            assert e2.query_df(
                "SELECT period FROM bars_minute WHERE ticker='600519.SH'")["period"][0] == "5"
            # 视图仍可查
            assert e2.query_df("SELECT * FROM v_cache_summary").shape[1] > 0
            # 多周期并存
            e2.execute(
                "INSERT INTO bars_minute "
                "(ticker, period, bar_time, open, high, low, close, volume, amount, market) "
                "VALUES ('600519.SH','1','2024-01-02 09:35:00',2.0,2.0,2.0,2.0,2,2.0,'a_share')")
            assert e2.query_df(
                "SELECT COUNT(*) c FROM bars_minute WHERE ticker='600519.SH'")["c"][0] == 2
            # 幂等重放不报错、版本不变
            migrate(e2)
            assert e2.query_df("SELECT MAX(version) v FROM schema_version")["v"][0] == 6

    def test_cache_catalog_has_minute_periods_column(self):
        """Task #25：cache_catalog 含 minute_periods 列（记录已缓存分钟周期）。"""
        with tempfile.TemporaryDirectory() as d:
            engine = DuckDBEngine(str(Path(d) / "test.db"))
            init_schema(engine)
            cols = engine.query_df(
                "SELECT column_name FROM duckdb_columns() "
                "WHERE table_name='cache_catalog'")["column_name"].to_list()
            assert "minute_periods" in cols
