import logging
import akshare as ak
from ...store.engine import DuckDBManager
from ...market.rate_limiter import RateLimiter
from .models import resolve_ticker

logger = logging.getLogger(__name__)


class DataCenterService:
    def __init__(self, db: DuckDBManager, limiter: RateLimiter):
        self._db = db
        self._limiter = limiter

    def search_symbols(self, query: str) -> list[dict]:
        if not query or len(query) < 2:
            return []
        try:
            cached = self._db.query_df(
                "SELECT code, name FROM symbol_cache WHERE code LIKE ? OR name LIKE ? LIMIT 20",
                [f"%{query}%", f"%{query}%"],
            )
            if len(cached) > 0:
                return [
                    {"label": f"{r['code']} - {r['name']}", "value": r["code"]}
                    for r in cached.to_dicts()
                ]
        except Exception:
            pass

        try:
            df = ak.stock_info_a_code_name()
            self._db.execute("CREATE TABLE IF NOT EXISTS symbol_cache (code VARCHAR PRIMARY KEY, name VARCHAR)")
            for _, r in df.iterrows():
                self._db.execute("INSERT OR REPLACE INTO symbol_cache VALUES (?,?)",
                                 [r["code"], r["name"]])
            filtered = df[df["code"].str.contains(query) | df["name"].str.contains(query, na=False)]
            return [
                {"label": f"{r['code']} - {r['name']}", "value": r["code"]}
                for _, r in filtered.head(20).iterrows()
            ]
        except Exception as e:
            logger.error("Search failed: %s", e)
            return []

    def fetch_bars(self, symbols: list[str], start: str, end: str,
                   data_type: str = "daily", period: str = "") -> dict:
        results = {}
        for sym in symbols:
            try:
                code = sym.replace(".SH", "").replace(".SZ", "").replace(".HK", "")
                if data_type == "daily":
                    df = ak.stock_zh_a_hist(symbol=code, period="daily",
                                            start_date=start, end_date=end, adjust="qfq")
                    if df is not None and not df.empty:
                        ticker = resolve_ticker(code, "a_share")
                        rows = []
                        for _, r in df.iterrows():
                            rows.append([ticker, str(r["日期"])[:10], float(r["开盘"]),
                                         float(r["最高"]), float(r["最低"]), float(r["收盘"]),
                                         int(r["成交量"]), float(r["成交额"]), "a_share"])
                        self._db.execute("DELETE FROM bars_daily WHERE ticker=?", [ticker])
                        self._db.execute_many(
                            "INSERT INTO bars_daily VALUES (?,?,?,?,?,?,?,?,?)", rows)
                        results[sym] = {"status": "ok", "count": len(rows)}
                elif data_type == "financials":
                    fin = ak.stock_financial_abstract(symbol=code)
                    results[sym] = {"status": "ok", "financials": True} \
                        if fin is not None else {"status": "no_data"}
            except Exception as e:
                results[sym] = {"status": "failed", "error": str(e)[:80]}
        return results

    def get_cache_stats(self) -> dict:
        try:
            df_total = self._db.query_df("SELECT COUNT(DISTINCT ticker) as c FROM bars_daily")
            total = df_total["c"][0] if len(df_total) > 0 else 0

            df_a = self._db.query_df(
                "SELECT COUNT(DISTINCT ticker) as c FROM bars_daily WHERE market='a_share'")
            a_share = df_a["c"][0] if len(df_a) > 0 else 0

            df_hk = self._db.query_df(
                "SELECT COUNT(DISTINCT ticker) as c FROM bars_daily WHERE market='hk_connect'")
            hk = df_hk["c"][0] if len(df_hk) > 0 else 0

            df_rec = self._db.query_df("SELECT COUNT(*) as c FROM bars_daily")
            records = df_rec["c"][0] if len(df_rec) > 0 else 0

            df_last = self._db.query_df("SELECT MAX(trade_date) as d FROM bars_daily")
            last_update = str(df_last["d"][0]) if len(df_last) > 0 and df_last["d"][0] is not None else ""

            return {"total": total, "a_share": a_share, "hk": hk,
                    "records": records, "last_update": last_update}
        except Exception as e:
            logger.error("get_cache_stats failed: %s", e)
            return {"total": 0, "a_share": 0, "hk": 0, "records": 0, "last_update": ""}

    def get_cached_table(self, market_filter: str = "all", text_filter: str = "") -> list[dict]:
        try:
            parts = [
                "SELECT ticker, market, COUNT(*) as records,",
                "MIN(trade_date) as start_date, MAX(trade_date) as end_date",
                "FROM bars_daily",
            ]
            params = []
            clauses = []
            if market_filter != "all":
                clauses.append("market=?")
                params.append(market_filter)
            if text_filter and text_filter.strip():
                clauses.append("(ticker LIKE ?)")
                params.append(f"%{text_filter.strip()}%")
            if clauses:
                parts.append("WHERE " + " AND ".join(clauses))
            parts.append("GROUP BY ticker, market ORDER BY ticker")
            df = self._db.query_df(" ".join(parts), params)
            return df.to_dicts() if len(df) > 0 else []
        except Exception as e:
            logger.error("get_cached_table failed: %s", e)
            return []

    def delete_symbols(self, tickers: list[str]) -> int:
        count = 0
        for t in tickers:
            try:
                self._db.execute("DELETE FROM bars_daily WHERE ticker=?", [t])
                self._db.execute("DELETE FROM bars_minute WHERE ticker=?", [t])
                count += 1
            except Exception as e:
                logger.error("Failed to delete %s: %s", t, e)
        return count

    def estimate_export(self, symbols: list[str], start: str, end: str) -> dict:
        try:
            parts = ["SELECT COUNT(*) as c FROM bars_daily"]
            params = []
            clauses = []
            if symbols:
                placeholders = ",".join(["?"] * len(symbols))
                clauses.append(f"ticker IN ({placeholders})")
                params.extend(symbols)
            if start:
                clauses.append("trade_date >= ?")
                params.append(start)
            if end:
                clauses.append("trade_date <= ?")
                params.append(end)
            if clauses:
                parts.append("WHERE " + " AND ".join(clauses))
            df = self._db.query_df(" ".join(parts), params)
            n = df["c"][0] if len(df) > 0 else 0
            return {"records": n, "estimated_size_kb": round(n * 0.15, 1)}
        except Exception as e:
            logger.error("estimate_export failed: %s", e)
            return {"records": 0, "estimated_size_kb": 0}
