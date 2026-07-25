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
