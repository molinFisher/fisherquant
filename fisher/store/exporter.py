import csv
import io
import polars as pl
from ..store.engine import DuckDBManager


class DataExporter:
    def __init__(self, db: DuckDBManager | None = None):
        self.db = db or DuckDBManager()

    def export_csv_stream(self, table: str, columns: list[str] | None = None,
                          where: str = "", params: list | None = None) -> io.StringIO:
        cols = ", ".join(columns) if columns else "*"
        sql = f"SELECT {cols} FROM {table}"
        if where:
            sql += f" WHERE {where}"
        output = io.StringIO()
        writer = csv.writer(output)
        df = self.db.query_df(sql, params)
        writer.writerow(df.columns)
        for row in df.iter_rows():
            writer.writerow(row)
        output.seek(0)
        return output

    def export_parquet(self, table: str, output_path: str, where: str = "",
                       params: list | None = None):
        sql = f"SELECT * FROM {table}"
        if where:
            sql += f" WHERE {where}"
        df = self.db.query_df(sql, params)
        df.write_parquet(output_path)
        return output_path

    def export_streaming(self, table: str, format: str, where: str = "",
                         params: list | None = None, chunk_size: int = 10000):
        cols_df = self.db.query_df(f"SELECT * FROM {table} LIMIT 1")
        columns = cols_df.columns
        sql = f"SELECT * FROM {table}"
        if where:
            sql += f" WHERE {where}"
        offset = 0
        while True:
            batch_sql = f"{sql} LIMIT {chunk_size} OFFSET {offset}"
            batch = self.db.query_df(batch_sql, params)
            if len(batch) == 0:
                break
            yield batch
            offset += chunk_size
