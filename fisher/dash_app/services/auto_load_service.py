import logging
import akshare as ak
from datetime import datetime
from ...store.engine import DuckDBManager
from ...market.rate_limiter import RateLimiter
from .models import resolve_ticker, AUTO_LOAD_CFG

logger = logging.getLogger(__name__)


class AutoLoadService:
    def __init__(self, db: DuckDBManager, limiter: RateLimiter, scheduler=None):
        self._db = db
        self._limiter = limiter
        self._scheduler = scheduler
        self._ensure_status_table()

    def _ensure_status_table(self):
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS auto_load_status (
                key VARCHAR PRIMARY KEY, value VARCHAR NOT NULL
            )""")

    def check_and_start(self) -> dict:
        row = self._db.query_df("SELECT value FROM auto_load_status WHERE key='phase'")
        phase = row["value"].to_list()[0] if len(row) > 0 else "fresh"

        if phase == "fresh":
            count = self._db.query_df("SELECT COUNT(*) as c FROM bars_daily")
            if count["c"][0] == 0:
                self.set_status("phase", "initial_load")
                return self.initial_load()
            return {"phase": "idle", "message": "data_exists"}

        if phase == "initial_load":
            return self.initial_load()

        return {"phase": "idle"}

    def initial_load(self) -> dict:
        current = int(self._get("current", 0))
        total = int(self._get("total", 0))

        if total == 0:
            codes = self._load_index_codes()
            if not codes:
                return {"phase": "error", "message": "无法获取成分股列表"}
            total = len(codes)
            self.set_status("total", str(total))

        codes = self._load_index_codes()
        for i in range(current, min(current + 5, len(codes))):
            try:
                code = codes[i]
                ticker_code = code.replace(".SH", "").replace(".SZ", "").replace(".HK", "")
                is_hk = ".HK" in code
                market = "hk_connect" if is_hk else "a_share"
                ticker = code if is_hk else resolve_ticker(ticker_code, "a_share")

                df = ak.stock_zh_a_hist(symbol=ticker_code, period="daily",
                                        start_date=AUTO_LOAD_CFG["initial_start"],
                                        end_date=datetime.now().strftime("%Y-%m-%d"), adjust="qfq")
                if df is not None and not df.empty:
                    for _, r in df.iterrows():
                        self._db.execute("INSERT OR REPLACE INTO bars_daily VALUES (?,?,?,?,?,?,?,?,?,?)",
                                         [ticker, str(r["日期"])[:10], float(r["开盘"]),
                                          float(r["最高"]), float(r["最低"]), float(r["收盘"]),
                                          int(r["成交量"]), float(r["成交额"]), market, 1.0])
                    logger.info("Loaded %s (%d rows)", ticker, len(df))
                else:
                    logger.warning("No data for %s", ticker)
                current += 1
                self.set_status("current", str(current))
            except Exception as e:
                current += 1
                self.set_status("current", str(current))
                logger.warning("Skipped %s: %s", codes[i], e)

        if current >= total:
            self.set_status("phase", "idle")
            return {"phase": "complete", "total": total}
        return {"phase": "initial_load", "current": current, "total": total}

    def incremental_update(self) -> dict:
        tickers = self._db.query_df("SELECT DISTINCT ticker FROM bars_daily")["ticker"].to_list()
        processed = 0
        for t in tickers[:AUTO_LOAD_CFG["incremental_batch_size"]]:
            try:
                code = t.replace(".SH", "").replace(".SZ", "").replace(".HK", "")
                last = self._db.query_df("SELECT MAX(trade_date) as d FROM bars_daily WHERE ticker=?", [t])
                last_date = last["d"][0] if len(last) > 0 and last["d"][0] is not None \
                    else AUTO_LOAD_CFG["initial_start"]
                df = ak.stock_zh_a_hist(symbol=code, period="daily",
                                        start_date=str(last_date),
                                        end_date=datetime.now().strftime("%Y-%m-%d"),
                                        adjust="qfq")
                if df is not None and len(df) > 1:
                    for _, r in df.iloc[1:].iterrows():
                        self._db.execute("INSERT OR REPLACE INTO bars_daily VALUES (?,?,?,?,?,?,?,?,?,?)",
                                         [t, str(r["日期"])[:10], float(r["开盘"]), float(r["最高"]),
                                          float(r["最低"]), float(r["收盘"]), int(r["成交量"]),
                                          float(r["成交额"]), "a_share", 1.0])
                processed += 1
            except Exception as e:
                logger.warning("Incremental update failed %s: %s", t, e)
        self.set_status("last_run", datetime.now().isoformat())
        return {"phase": "incremental", "processed": processed}

    def get_progress(self) -> dict:
        return {"phase": self._get("phase", "idle"), "current": int(self._get("current", 0)),
                "total": int(self._get("total", 0)), "last_run": self._get("last_run", "")}

    def set_status(self, key: str, value: str):
        self._db.execute("INSERT OR REPLACE INTO auto_load_status VALUES (?,?)", [key, value])

    def get_status(self, key: str, default="0") -> str:
        row = self._db.query_df("SELECT value FROM auto_load_status WHERE key=?", [key])
        return row["value"].to_list()[0] if len(row) > 0 else str(default)

    def _get(self, key: str, default="0") -> str:
        row = self._db.query_df("SELECT value FROM auto_load_status WHERE key=?", [key])
        return row["value"].to_list()[0] if len(row) > 0 else str(default)

    def _set(self, key: str, value: str):
        self.set_status(key, value)

    def _load_index_codes(self) -> list[str]:
        codes = []
        try:
            df = ak.index_stock_cons(symbol="000300")
            col = df.columns[0]  # First column is always the stock code
            codes += [f"{r[col]}.SH" if r[col].startswith(("6", "5", "9"))
                      else f"{r[col]}.SZ" for _, r in df.iterrows()]
        except Exception as e:
            logger.warning("CSI300 fetch failed: %s", e)
        try:
            hk_df = ak.stock_hk_spot()
            code_col = hk_df.columns[1]  # Second column is stock code in HK spot data
            # Filter to major HK stocks (HSI constituents approximate by top volume)
            for _, r in hk_df.head(80).iterrows():
                raw_code = str(r[code_col]).zfill(5)
                codes.append(f"{raw_code}.HK")
        except Exception as e:
            logger.warning("HK stock list fetch failed: %s", e)
        return codes
