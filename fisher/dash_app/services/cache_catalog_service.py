"""缓存目录中枢服务（PRD FR-1 / §7）。

`cache_catalog` 是「缓存数据类型扩展 + 行情看板联动」的联动中枢：
- 逐标的记录 5 类数据资产覆盖度（has_*）与时间边界；
- 缓存目录页用它做类型筛选与按类型条数聚合；
- 行情看板用它渲染覆盖度徽标、健康度汇总与「去缓存」入口；
- 自动加载用它把「加载宇宙」收敛为 `auto_load_enabled=TRUE` 的显式集合。

设计要点（评审修订 D-2 / D-6）：
- 所有覆盖度写入经由 `record_coverage(conn, ...)`，由调用方在已开启的
  `DuckDBManager.transaction()` 内调用，与数据写库共享同一事务，保证
  「数据写了、目录也更新 / 数据回滚、目录也回滚」（FR-1.2 / FR-1.6，验收 13）。
- 所有 catalog 写只走 `DuckDBManager` 单写连接（write_connection），禁止独立
  新建 `duckdb.connect` 写连接（FR-1.7），避免重现 V1.3 前锁冲突回归。
- 边界字段采用 LEAST/GREATEST(COALESCE(...)) 合并，重复获取同区间不会缩窄
  已覆盖范围的边界（验收 12 幂等边界不漂移）。
"""

import logging
from typing import Optional

from ...store.engine import DuckDBManager
from .symbol_search import escape_like

logger = logging.getLogger(__name__)

# 五类数据资产（与 cache_catalog 的 has_* 列、FR-1.1 严格对应）
DATA_TYPES = ("daily", "minute", "realtime", "adj", "financials")

# data_type -> (起始边界列, 结束边界列)；（realtime / adj / financials 无区间，走单列）
_RANGE_FIELDS = {
    "daily": ("daily_start", "daily_end"),
    "minute": ("minute_start", "minute_end"),
}
_SINGLE_FIELDS = {
    "realtime": "realtime_ts",
    "financials": "fin_report_end",
}


class CacheCatalogService:
    def __init__(self, db: DuckDBManager):
        self._db = db

    # ------------------------------------------------------------------ #
    # 写入：同事务覆盖度记录（FR-1.2 / FR-1.6）
    # ------------------------------------------------------------------ #
    def record_coverage(
        self,
        conn,
        ticker: str,
        market: str,
        name: Optional[str] = None,
        *,
        data_type: Optional[str] = None,
        start=None,
        end=None,
        realtime_ts=None,
        adj_type: Optional[str] = None,
        fin_report_end=None,
    ) -> None:
        """在调用方已开启的事务 `conn` 内 upsert 该标的的覆盖度。

        参数：
          conn        由 `with self._db.transaction() as conn:` 提供，禁止独立连接。
          ticker      标准代码（600519.SH / 00700.HK）。
          market      a_share / hk_connect。
          name       标的名称（优先取自 symbol_dict）；为空时按 ticker 兜底。
          data_type   daily/minute/realtime/adj/financials；为 None 时仅确保行存在。
          start/end   日线/分钟线的起止边界（DATE / TIMESTAMP）。
          realtime_ts 最近一次实时快照时间。
          adj_type    复权口径 qfq / hfq / none。
          fin_report_end 财务最新报告期（DATE）。

        行为：INSERT OR IGNORE 确保目录行存在；随后按 data_type 增量更新 has_* 与
        边界（边界用 LEAST/GREATEST 合并，避免重复获取缩窄范围）。
        """
        # 名称兜底：优先用传入 name，缺失时读 symbol_dict
        if not name:
            try:
                row = conn.execute(
                    "SELECT name FROM symbol_dict WHERE ticker=?", [ticker]
                ).fetchone()
                if row and row[0]:
                    name = row[0]
            except Exception:
                pass
        name = name or ticker

        # 确保目录行存在（market/name 给默认值，后续 UPDATE 再补权威值）
        conn.execute(
            "INSERT OR IGNORE INTO cache_catalog (ticker, market, name) VALUES (?,?,?)",
            [ticker, market, name],
        )

        sets: list[str] = ["last_update=CURRENT_TIMESTAMP", "market=?", "name=?"]
        params: list = [market, name]

        if data_type in DATA_TYPES:
            sets.append(f"has_{data_type}=TRUE")
            if data_type in _RANGE_FIELDS:
                sf, ef = _RANGE_FIELDS[data_type]
                if start is not None:
                    sets.append(f"{sf}=LEAST(COALESCE({sf}, ?), ?)")
                    params.extend([start, start])
                if end is not None:
                    sets.append(f"{ef}=GREATEST(COALESCE({ef}, ?), ?)")
                    params.extend([end, end])
            elif data_type in _SINGLE_FIELDS:
                col = _SINGLE_FIELDS[data_type]
                val = realtime_ts if data_type == "realtime" else fin_report_end
                if val is not None:
                    sets.append(f"{col}=GREATEST(COALESCE({col}, ?), ?)")
                    params.extend([val, val])
            elif data_type == "adj":
                if adj_type is not None:
                    sets.append("adj_type=?")
                    params.append(adj_type)

        conn.execute(
            "UPDATE cache_catalog SET " + ", ".join(sets) + " WHERE ticker=?",
            params + [ticker],
        )

    # data_type -> 删除该类时需一并置 NULL 的边界/口径列（FR-1.5）
    _CLEAR_NULL_COLS = {
        "daily": ("daily_start", "daily_end"),
        "minute": ("minute_start", "minute_end"),
        "realtime": ("realtime_ts",),
        "adj": ("adj_type",),
        "financials": ("fin_report_end",),
    }

    def clear_coverage(self, conn, ticker: str, data_type: str) -> None:
        """在事务内清除某类的覆盖标记 + 边界置 NULL（删除该类数据时联动，FR-1.5 / 验收 11）。"""
        if data_type not in DATA_TYPES:
            return
        null_sets = "".join(
            f", {col}=NULL" for col in self._CLEAR_NULL_COLS.get(data_type, ())
        )
        conn.execute(
            f"UPDATE cache_catalog SET has_{data_type}=FALSE{null_sets}, "
            "last_update=CURRENT_TIMESTAMP WHERE ticker=?",
            [ticker],
        )

    # ------------------------------------------------------------------ #
    # 读取：目录筛选与看板消费（FR-1.3 / FR-1.4 / FR-8.2）
    # ------------------------------------------------------------------ #
    def get_cache_catalog(
        self,
        market: Optional[str] = None,
        data_type: Optional[str] = None,
        text: Optional[str] = None,
    ) -> list[dict]:
        """按条件查询目录（FR-1.3）。

        market: a_share / hk_connect / None(=all)
        data_type: daily/minute/realtime/adj/financials 过滤 has_<type>=TRUE
        text: 代码或名称模糊匹配
        """
        parts = [
            "SELECT ticker, name, market,",
            "has_daily, has_minute, has_realtime, has_adj, has_financials,",
            "auto_load_enabled, daily_start, daily_end, minute_start, minute_end,",
            "realtime_ts, adj_type, fin_report_end, last_update",
            "FROM cache_catalog",
        ]
        clauses: list[str] = []
        params: list = []
        if market and market != "all":
            clauses.append("market = ?")
            params.append(market)
        if data_type and data_type in DATA_TYPES:
            clauses.append(f"has_{data_type} = TRUE")
        if text and text.strip():
            esc = escape_like(text.strip())
            clauses.append("(ticker LIKE ? ESCAPE '\\' OR name LIKE ? ESCAPE '\\')")
            params.extend([f"%{esc}%", f"%{esc}%"])
        if clauses:
            parts.append("WHERE " + " AND ".join(clauses))
        parts.append("ORDER BY ticker")
        try:
            df = self._db.query_df(" ".join(parts), params)
            return df.to_dicts() if len(df) > 0 else []
        except Exception as e:
            logger.error("get_cache_catalog 查询失败: %s", e)
            return []

    def get_cache_summary(
        self,
        market: Optional[str] = None,
        data_types: Optional[list[str]] = None,
        text: Optional[str] = None,
    ) -> list[dict]:
        """缓存目录页数据源（FR-8.1/FR-8.2）：v_cache_summary 按类型聚合条数。

        data_types 为多选（AND 语义）：勾选 ["daily","minute"] 表示筛选
        「同时具备日线与分钟线」的标的；空/None 不过滤。
        返回字段含 has_* 布尔、daily/minute 边界与 *_rows 各类型条数。
        """
        parts = ["SELECT * FROM v_cache_summary"]
        clauses: list[str] = []
        params: list = []
        if market and market != "all":
            clauses.append("market = ?")
            params.append(market)
        for dt in data_types or []:
            if dt in DATA_TYPES:
                clauses.append(f"has_{dt} = TRUE")
        if text and text.strip():
            esc = escape_like(text.strip())
            clauses.append("(ticker LIKE ? ESCAPE '\\' OR name LIKE ? ESCAPE '\\')")
            params.extend([f"%{esc}%", f"%{esc}%"])
        if clauses:
            parts.append("WHERE " + " AND ".join(clauses))
        parts.append("ORDER BY ticker")
        try:
            df = self._db.query_df(" ".join(parts), params)
            return df.to_dicts() if len(df) > 0 else []
        except Exception as e:
            logger.error("get_cache_summary 查询失败: %s", e)
            return []

    def get_coverage_for_tickers(self, tickers: list[str]) -> dict[str, dict]:
        """批量取覆盖度，供行情看板渲染紧凑徽标（FR-4.1，单查询 IN 批量）。"""
        if not tickers:
            return {}
        placeholders = ",".join(["?"] * len(tickers))
        try:
            df = self._db.query_df(
                "SELECT ticker, has_daily, has_minute, has_realtime, has_adj, has_financials, "
                "auto_load_enabled, realtime_ts "
                f"FROM cache_catalog WHERE ticker IN ({placeholders})",
                tickers,
            )
            return {r["ticker"]: r for r in df.to_dicts()} if len(df) > 0 else {}
        except Exception as e:
            logger.error("get_coverage_for_tickers 查询失败: %s", e)
            return {}

    def get_tickers_with_data(self) -> set[str]:
        """返回 has_daily OR has_minute = TRUE 的标的集合（FR-5.1 / FR-5.3 看板可加 + pruning）。"""
        try:
            df = self._db.query_df(
                "SELECT ticker FROM cache_catalog WHERE has_daily OR has_minute"
            )
            return {r["ticker"] for r in df.to_dicts()} if len(df) > 0 else set()
        except Exception as e:
            logger.error("get_tickers_with_data 查询失败: %s", e)
            return set()

    def has_any_data(self, ticker: str) -> bool:
        """该标的是否在 cache_catalog 有任何覆盖（联动 C 入自选前置条件，FR-3.3）。"""
        try:
            df = self._db.query_df(
                "SELECT 1 FROM cache_catalog "
                "WHERE ticker=? AND (has_daily OR has_minute OR has_realtime OR has_adj OR has_financials)",
                [ticker],
            )
            return len(df) > 0
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # 自动加载开关（FR-3.1 / FR-7.5）
    # ------------------------------------------------------------------ #
    def set_auto_load_enabled(self, ticker: str, enabled: bool = True) -> None:
        """置/清 auto_load_enabled（自身短事务，FR-7.5）。"""
        try:
            with self._db.transaction() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO cache_catalog (ticker, market, name) "
                    "VALUES (?, 'a_share', ?)",
                    [ticker, ticker],
                )
                conn.execute(
                    "UPDATE cache_catalog SET auto_load_enabled=? WHERE ticker=?",
                    [bool(enabled), ticker],
                )
        except Exception as e:
            logger.error("set_auto_load_enabled %s=%s 失败: %s", ticker, enabled, e)

    def get_auto_load_universe(self) -> list[str]:
        """自动加载宇宙 = auto_load_enabled = TRUE 的标的（FR-7.1 / FR-7.5）。"""
        try:
            df = self._db.query_df(
                "SELECT ticker FROM cache_catalog WHERE auto_load_enabled = TRUE"
            )
            return [r["ticker"] for r in df.to_dicts()] if len(df) > 0 else []
        except Exception as e:
            logger.error("get_auto_load_universe 查询失败: %s", e)
            return []
