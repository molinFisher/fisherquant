import tempfile
from pathlib import Path
import polars as pl
from fisher.store.engine import DuckDBManager


class TestDuckDBManager:
    def setup_method(self):
        DuckDBManager._instance = None

    def test_singleton(self):
        m1 = DuckDBManager(":memory:")
        m2 = DuckDBManager(":memory:")
        assert m1 is m2

    def test_write_and_read(self):
        m = DuckDBManager()
        with tempfile.TemporaryDirectory() as d:
            p = str(Path(d) / "test.db")
            m.connect(p)
            m.execute("CREATE TABLE t (id INT)")
            m.execute("INSERT INTO t VALUES (1), (2)")
            df = m.query_df("SELECT * FROM t ORDER BY id")
            assert df["id"].to_list() == [1, 2]

    def test_execute_many(self):
        m = DuckDBManager()
        with tempfile.TemporaryDirectory() as d:
            p = str(Path(d) / "test.db")
            m.connect(p)
            m.execute("CREATE TABLE t (id INT, value DOUBLE)")
            m.execute_many(
                "INSERT INTO t VALUES (?, ?)",
                [[1, 10.0], [2, 20.0], [3, 30.0]],
            )
            df = m.query_df("SELECT COUNT(*) AS cnt FROM t")
            assert df["cnt"][0] == 3

    def test_query_df_returns_polars(self):
        m = DuckDBManager()
        with tempfile.TemporaryDirectory() as d:
            p = str(Path(d) / "test.db")
            m.connect(p)
            m.execute("CREATE TABLE t (id INT)")
            m.execute("INSERT INTO t VALUES (42)")
            df = m.query_df("SELECT * FROM t")
            assert isinstance(df, pl.DataFrame)
            assert df["id"][0] == 42

    def test_transaction_rollback(self):
        m = DuckDBManager()
        with tempfile.TemporaryDirectory() as d:
            p = str(Path(d) / "test.db")
            m.connect(p)
            m.execute("CREATE TABLE t (id INT)")
            try:
                with m.transaction():
                    m.execute("INSERT INTO t VALUES (1)")
                    raise RuntimeError("boom")
            except RuntimeError:
                pass
            df = m.query_df("SELECT COUNT(*) as c FROM t")
            assert df["c"][0] == 0

    def test_transaction_commit(self):
        m = DuckDBManager()
        with tempfile.TemporaryDirectory() as d:
            p = str(Path(d) / "test.db")
            m.connect(p)
            m.execute("CREATE TABLE t (id INT)")
            with m.transaction():
                m.execute("INSERT INTO t VALUES (42)")
            df = m.query_df("SELECT id FROM t")
            assert df["id"][0] == 42

    def test_write_connection_property(self):
        m = DuckDBManager()
        with tempfile.TemporaryDirectory() as d:
            p = str(Path(d) / "test.db")
            m.connect(p)
            conn = m.write_connection
            conn.execute("CREATE TABLE t (id INT)")
            conn.execute("INSERT INTO t VALUES (99)")
            df = m.query_df("SELECT id FROM t")
            assert df["id"][0] == 99

    def test_write_connection_raises_when_not_connected(self):
        m = DuckDBManager()
        DuckDBManager._instance = None
        m = DuckDBManager()
        try:
            m.write_connection
            assert False, "should have raised"
        except RuntimeError:
            pass

    def test_close_cleans_up(self):
        m = DuckDBManager()
        with tempfile.TemporaryDirectory() as d:
            p = str(Path(d) / "test.db")
            m.connect(p)
            m.execute("CREATE TABLE t (id INT)")
            m.execute("INSERT INTO t VALUES (1)")
            m.close()
            assert DuckDBManager._instance is None

    def test_read_pool_reuse(self):
        m = DuckDBManager()
        with tempfile.TemporaryDirectory() as d:
            p = str(Path(d) / "test.db")
            m.connect(p, read_pool_size=2)
            m.execute("CREATE TABLE t (id INT)")
            m.execute("INSERT INTO t VALUES (1), (2), (3)")
            df1 = m.query_df("SELECT * FROM t WHERE id=1")
            df2 = m.query_df("SELECT * FROM t WHERE id=2")
            df3 = m.query_df("SELECT * FROM t WHERE id=3")
            assert df1["id"][0] == 1
            assert df2["id"][0] == 2
            assert df3["id"][0] == 3

    def test_connect_replaces_old_pool(self):
        m = DuckDBManager()
        with tempfile.TemporaryDirectory() as d1:
            p1 = str(Path(d1) / "test1.db")
            m.connect(p1, read_pool_size=1)
            m.execute("CREATE TABLE t1 (id INT)")
            m.execute("INSERT INTO t1 VALUES (100)")
            df1 = m.query_df("SELECT * FROM t1")
            assert df1["id"][0] == 100

        with tempfile.TemporaryDirectory() as d2:
            p2 = str(Path(d2) / "test2.db")
            m.connect(p2, read_pool_size=1)
            m.execute("CREATE TABLE t2 (id INT)")
            m.execute("INSERT INTO t2 VALUES (200)")
            df2 = m.query_df("SELECT * FROM t2")
            assert df2["id"][0] == 200
