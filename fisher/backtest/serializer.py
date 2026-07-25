import json
import polars as pl
from pathlib import Path
from datetime import datetime
from ..store.engine import DuckDBManager
import logging

logger = logging.getLogger(__name__)

RESULTS_DIR = "data/backtest_results"


class BacktestSerializer:
    def __init__(self, db: DuckDBManager | None = None):
        self.db = db or DuckDBManager()

    def save(self, result_id: str, nav_history: list, trades: list | None = None,
             benchmark: list | None = None, metadata: dict | None = None) -> str:
        dir_path = Path(RESULTS_DIR) / result_id
        dir_path.mkdir(parents=True, exist_ok=True)

        df = pl.DataFrame({"date": range(len(nav_history)), "equity": nav_history})
        df.write_parquet(dir_path / "equity_curve.parquet")

        if benchmark:
            bdf = pl.DataFrame({"date": range(len(benchmark)), "benchmark": benchmark})
            bdf.write_parquet(dir_path / "benchmark_curve.parquet")

        if trades:
            tdf = pl.DataFrame(trades)
            tdf.write_parquet(dir_path / "trades.parquet")

        meta = {
            "id": result_id,
            "saved_at": datetime.now().isoformat(),
            "nav_points": len(nav_history),
            **(metadata or {}),
        }
        with open(dir_path / "metadata.json", "w") as f:
            json.dump(meta, f, indent=2)

        try:
            self.db.execute(
                """INSERT OR REPLACE INTO backtest_history
                   (id, saved_at, strategy, total_return, sharpe, max_dd)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [result_id, meta["saved_at"],
                 metadata.get("strategy", ""),
                 metadata.get("total_return", 0),
                 metadata.get("sharpe", 0),
                 metadata.get("max_drawdown", 0)],
            )
        except Exception as e:
            logger.warning("Failed to write backtest history: %s", e)

        return str(dir_path)

    def load(self, result_id: str) -> dict:
        dir_path = Path(RESULTS_DIR) / result_id
        result = {"id": result_id}
        eq_path = dir_path / "equity_curve.parquet"
        if eq_path.exists():
            result["equity"] = pl.read_parquet(eq_path)["equity"].to_list()
        bench_path = dir_path / "benchmark_curve.parquet"
        if bench_path.exists():
            result["benchmark"] = pl.read_parquet(bench_path)["benchmark"].to_list()
        trades_path = dir_path / "trades.parquet"
        if trades_path.exists():
            result["trades"] = pl.read_parquet(trades_path).to_dicts()
        meta_path = dir_path / "metadata.json"
        if meta_path.exists():
            with open(meta_path) as f:
                result["metadata"] = json.load(f)
        return result

    def list_history(self, limit: int = 200) -> list[dict]:
        try:
            df = self.db.query_df(
                "SELECT * FROM backtest_history ORDER BY saved_at DESC LIMIT ?",
                [limit],
            )
            return df.to_dicts()
        except Exception:
            return []

    def cleanup(self, keep: int = 200):
        count_df = self.db.query_df("SELECT COUNT(*) as c FROM backtest_history")
        total = count_df["c"][0] if len(count_df) > 0 else 0
        if total > keep:
            self.db.execute(
                "DELETE FROM backtest_history WHERE id IN (SELECT id FROM backtest_history ORDER BY saved_at ASC LIMIT ?)",
                [total - keep],
            )
