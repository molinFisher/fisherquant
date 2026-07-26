import csv
import io
import os
from datetime import date

import polars as pl
import pytest

from fisher.store.engine import DuckDBManager
from fisher.store.exporter import DataExporter


@pytest.fixture
def exporter_db(tmp_path):
    DuckDBManager._instance = None
    db = DuckDBManager(str(tmp_path / "exporter.db"), read_pool_size=1)
    db.execute(
        "CREATE TABLE prices ("
        "ticker VARCHAR, trade_date DATE, close DOUBLE, volume BIGINT)"
    )
    rows = [
        ("A", date(2024, 1, 1), 100.0, 1000),
        ("A", date(2024, 1, 2), 101.0, 1100),
        ("B", date(2024, 1, 1), 200.0, 500),
        ("B", date(2024, 1, 2), 201.0, 550),
    ]
    db.execute_many("INSERT INTO prices VALUES (?, ?, ?, ?)", rows)
    yield db
    DuckDBManager._instance = None


def test_export_csv_stream_returns_stringio(exporter_db):
    exporter = DataExporter(exporter_db)
    stream = exporter.export_csv_stream("prices")
    assert isinstance(stream, io.StringIO)


def test_export_csv_stream_content_and_rowcount(exporter_db):
    exporter = DataExporter(exporter_db)
    stream = exporter.export_csv_stream("prices")
    reader = list(csv.reader(io.StringIO(stream.getvalue())))
    header, data_rows = reader[0], reader[1:]

    assert header == ["ticker", "trade_date", "close", "volume"]
    assert len(data_rows) == 4
    # A concrete cell value must round-trip.
    assert data_rows[0] == ["A", "2024-01-01", "100.0", "1000"]


def test_export_csv_stream_column_selection(exporter_db):
    exporter = DataExporter(exporter_db)
    stream = exporter.export_csv_stream("prices", columns=["ticker", "close"])
    reader = list(csv.reader(io.StringIO(stream.getvalue())))
    header, data_rows = reader[0], reader[1:]

    assert header == ["ticker", "close"]
    assert all(len(r) == 2 for r in data_rows)
    assert data_rows[0] == ["A", "100.0"]


def test_export_csv_stream_where_filter(exporter_db):
    exporter = DataExporter(exporter_db)
    stream = exporter.export_csv_stream("prices", where="ticker = ?", params=["B"])
    reader = list(csv.reader(io.StringIO(stream.getvalue())))
    data_rows = reader[1:]

    assert len(data_rows) == 2
    assert all(r[0] == "B" for r in data_rows)


def test_export_parquet_writes_and_reads_back(exporter_db, tmp_path):
    exporter = DataExporter(exporter_db)
    out = tmp_path / "prices.parquet"
    returned = exporter.export_parquet("prices", str(out))

    assert returned == str(out)
    assert os.path.exists(out)

    df = pl.read_parquet(out)
    assert df.shape == (4, 4)
    assert df.columns == ["ticker", "trade_date", "close", "volume"]
    # Read-back values match source (ticker A on first date).
    first = df.sort(["ticker", "trade_date"]).row(0)
    assert first[0] == "A"
    assert float(first[2]) == 100.0


def test_export_streaming_chunking_and_total(exporter_db):
    # Add more rows so chunking is exercised.
    extra = [
        (f"T{i}", date(2024, 2, i % 28 + 1), float(10 + i), 100 + i)
        for i in range(1, 22)  # 21 extra rows -> 25 total
    ]
    exporter_db.execute_many("INSERT INTO prices VALUES (?, ?, ?, ?)", extra)

    exporter = DataExporter(exporter_db)
    batches = list(exporter.export_streaming("prices", format="parquet", chunk_size=10))

    total = sum(len(b) for b in batches)
    assert total == 25
    assert all(len(b) <= 10 for b in batches)
    # Last batch holds the remainder.
    assert len(batches[-1]) == 5
    # Every batch carries the full schema.
    assert batches[0].columns == ["ticker", "trade_date", "close", "volume"]


def test_export_streaming_with_where(exporter_db):
    exporter = DataExporter(exporter_db)
    batches = list(
        exporter.export_streaming("prices", format="csv", where="ticker = ?", params=["A"])
    )
    total = sum(len(b) for b in batches)
    assert total == 2
