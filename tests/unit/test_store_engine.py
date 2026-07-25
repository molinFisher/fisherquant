import tempfile
from pathlib import Path
import polars as pl
from fisher.store.engine import DuckDBEngine


class TestDuckDBEngine:
    def test_execute_creates_table(self):
        with tempfile.TemporaryDirectory() as d:
            db_path = str(Path(d) / "test.db")
            engine = DuckDBEngine(db_path)
            engine.execute("CREATE TABLE test (id INTEGER, name VARCHAR)")
            result = engine.query_df("SELECT * FROM test")
            assert len(result) == 0
            assert list(result.columns) == ["id", "name"]

    def test_insert_and_query(self):
        with tempfile.TemporaryDirectory() as d:
            db_path = str(Path(d) / "test.db")
            engine = DuckDBEngine(db_path)
            engine.execute("CREATE TABLE test (id INTEGER, value DOUBLE)")
            engine.execute("INSERT INTO test VALUES (1, 10.5), (2, 20.0)")
            result = engine.query_df("SELECT * FROM test ORDER BY id")
            assert len(result) == 2
            assert result["value"].to_list() == [10.5, 20.0]

    def test_execute_many(self):
        with tempfile.TemporaryDirectory() as d:
            db_path = str(Path(d) / "test.db")
            engine = DuckDBEngine(db_path)
            engine.execute("CREATE TABLE test (id INTEGER, value DOUBLE)")
            engine.execute_many(
                "INSERT INTO test VALUES (?, ?)",
                [[1, 10.0], [2, 20.0], [3, 30.0]],
            )
            result = engine.query_df("SELECT COUNT(*) AS cnt FROM test")
            assert result["cnt"][0] == 3

    def test_query_df_returns_polars(self):
        with tempfile.TemporaryDirectory() as d:
            db_path = str(Path(d) / "test.db")
            engine = DuckDBEngine(db_path)
            engine.execute("CREATE TABLE test (id INTEGER)")
            engine.execute("INSERT INTO test VALUES (1)")
            df = engine.query_df("SELECT * FROM test")
            assert isinstance(df, pl.DataFrame)
            assert df["id"].dtype == pl.Int32

    def test_persistence_across_connections(self):
        with tempfile.TemporaryDirectory() as d:
            db_path = str(Path(d) / "test.db")
            engine1 = DuckDBEngine(db_path)
            engine1.execute("CREATE TABLE test (x INTEGER)")
            engine1.execute("INSERT INTO test VALUES (42)")
            engine1.close()

            engine2 = DuckDBEngine(db_path)
            result = engine2.query_df("SELECT x FROM test")
            assert result["x"][0] == 42
            engine2.close()

    def test_connection_property(self):
        with tempfile.TemporaryDirectory() as d:
            engine = DuckDBEngine(str(Path(d) / "test.db"))
            engine.execute("CREATE TABLE test (id INTEGER)")
            conn = engine.connection
            conn.execute("INSERT INTO test VALUES (99)")
            result = engine.query_df("SELECT id FROM test")
            assert result["id"][0] == 99
