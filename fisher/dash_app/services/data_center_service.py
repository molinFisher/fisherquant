import logging
import time
import akshare as ak
from ...store.engine import DuckDBManager
from ...market.rate_limiter import RateLimiter
from .models import resolve_ticker
from .symbol_search import (
    normalize_query,
    escape_like,
    code_variants,
    to_pinyin,
    rank_results,
    MAX_RESULTS,
)

logger = logging.getLogger(__name__)


class DataCenterService:
    def __init__(self, db: DuckDBManager, limiter: RateLimiter):
        self._db = db
        self._limiter = limiter
        self._legacy_search: bool | None = None

    # ------------------------------------------------------------------ #
    # R-50 回滚开关：读取 configs/system.yaml 的 search.legacy（缓存一次）
    # ------------------------------------------------------------------ #
    def _use_legacy_search(self) -> bool:
        if self._legacy_search is None:
            try:
                from ...config.loader import ConfigLoader
                cfg, _ = ConfigLoader.safe_load("configs")
                self._legacy_search = bool(cfg.system.search.legacy)
            except Exception as e:
                logger.debug("读取 search.legacy 失败，默认走新链路: %s", e)
                self._legacy_search = False
        return self._legacy_search

    # ------------------------------------------------------------------ #
    # R-11 / R-12：标的字典全量刷新 + 单事务原子替换（后台调度调用）
    # ------------------------------------------------------------------ #
    def refresh_symbol_dict(self) -> dict:
        """全量刷新 symbol_dict：拉取 A 股 + 港股清单，离线生成拼音，
        按市场分事务原子替换（各自 DELETE + 批量 INSERT）；某一市场拉取失败时
        不影响另一市场已写入的数据，避免「港股失败 → 整个字典被 A 股覆盖清空」。

        返回统计 dict：{a_share, hk_connect, total, elapsed_ms, replaced}。
        """
        t0 = time.time()
        a_rows: list[list] = []
        hk_rows: list[list] = []
        a_count = 0
        hk_count = 0

        # A 股清单：stock_info_a_code_name() -> columns ['code','name']
        try:
            self._limiter.acquire()
            df_a = ak.stock_info_a_code_name()
            for code, name in df_a[["code", "name"]].itertuples(index=False, name=None):
                code = str(code).strip()
                name = str(name).strip()
                if not code or not name:
                    continue
                ticker = resolve_ticker(code, "a_share")
                py_full, py_abbr = to_pinyin(name)
                a_rows.append([ticker, code, name, "a_share", py_full, py_abbr])
                a_count += 1
        except Exception as e:
            logger.error("refresh_symbol_dict: A股清单拉取失败: %s", e)

        # 港股清单：stock_hk_spot() -> ['日期时间','代码','中文名称','英文名称',...]
        # 与自动加载宇宙（stock_hk_spot().head(80)）同源，保证缓存的港股都能查到名称。
        # 旧实现用 stock_hk_ggt_components_em()（港股通成分），该接口易失败，
        # 失败后整表被 A 股覆盖导致港股名称全部丢失（见 issue 港股无名称）。
        try:
            self._limiter.acquire()
            df_hk = ak.stock_hk_spot()
            code_col = "代码"
            name_col = "中文名称" if "中文名称" in df_hk.columns else \
                next((c for c in df_hk.columns if "名称" in str(c)), None)
            if name_col is not None:
                for code, name in df_hk[[code_col, name_col]].itertuples(index=False, name=None):
                    code = str(code).strip().zfill(5)
                    name = str(name).strip()
                    if not code or not name:
                        continue
                    ticker = resolve_ticker(code, "hk_connect")
                    py_full, py_abbr = to_pinyin(name)
                    hk_rows.append([ticker, code, name, "hk_connect", py_full, py_abbr])
                    hk_count += 1
        except Exception as e:
            logger.error("refresh_symbol_dict: 港股清单拉取失败: %s", e)

        if not a_rows and not hk_rows:
            logger.warning("refresh_symbol_dict: 未获取到任何标的，保留旧字典不替换")
            return {"a_share": 0, "hk_connect": 0, "total": 0,
                    "elapsed_ms": int((time.time() - t0) * 1000), "replaced": False}

        replaced = False

        # 按市场分事务原子替换：某市场无数据（拉取失败）则跳过其 DELETE，保留旧数据。
        def _replace_market(market: str, rows: list[list]):
            nonlocal replaced
            if not rows:
                return
            # 去重：重复 ticker 会导致 INSERT 主键冲突；按 ticker 去重，保留首次出现。
            _seen: set[str] = set()
            _deduped: list[list] = []
            for _r in rows:
                if _r[0] not in _seen:
                    _seen.add(_r[0])
                    _deduped.append(_r)
            try:
                with self._db.transaction() as conn:
                    conn.execute("DELETE FROM symbol_dict WHERE market = ?", [market])
                    conn.executemany(
                        "INSERT INTO symbol_dict "
                        "(ticker, code, name, market, pinyin_full, pinyin_abbr) "
                        "VALUES (?,?,?,?,?,?)",
                        _deduped,
                    )
                replaced = True
            except Exception as e:
                logger.error("refresh_symbol_dict: %s 原子替换失败，已回滚，旧数据保留: %s",
                             market, e)

        _replace_market("a_share", a_rows)
        _replace_market("hk_connect", hk_rows)

        total = a_count + hk_count
        elapsed = int((time.time() - t0) * 1000)
        logger.info(
            "symbol_dict 刷新完成 a_share=%d hk_connect=%d total=%d elapsed_ms=%d replaced=%s",
            a_count, hk_count, total, elapsed, replaced,
        )
        return {"a_share": a_count, "hk_connect": hk_count, "total": total,
                "elapsed_ms": elapsed, "replaced": replaced}

    def backfill_hk_names(self) -> int:
        """回填已缓存港股的名称：扫描 bars_daily 中缺失 symbol_dict 名称的港股标的，
        从 stock_hk_spot 取名称并 upsert。用于修复「已缓存数据但港股无名称」的存量问题，
        与刷新调度解耦，幂等可重复调用。返回成功补全的标的数量。
        """
        try:
            missing = self._db.query_df(
                "SELECT DISTINCT b.ticker FROM bars_daily b "
                "LEFT JOIN symbol_dict s ON s.ticker = b.ticker "
                "WHERE b.market = 'hk_connect' AND s.ticker IS NULL"
            )
            tickers = [r["ticker"] for r in missing.iter_rows(named=True)]
            if not tickers:
                return 0
            self._limiter.acquire()
            df_hk = ak.stock_hk_spot()
            code_col = "代码"
            name_col = "中文名称" if "中文名称" in df_hk.columns else \
                next((c for c in df_hk.columns if "名称" in str(c)), None)
            if name_col is None:
                return 0
            name_map: dict[str, str] = {}
            for code, name in df_hk[[code_col, name_col]].itertuples(index=False, name=None):
                code = str(code).strip().zfill(5)
                name = str(name).strip()
                if code and name:
                    name_map[f"{code}.HK"] = name
            rows: list[list] = []
            for t in tickers:
                nm = name_map.get(t)
                if not nm:
                    continue
                py_full, py_abbr = to_pinyin(nm)
                rows.append([t, t.replace(".HK", ""), nm, "hk_connect", py_full, py_abbr])
            if rows:
                self._db.execute_many(
                    "INSERT OR REPLACE INTO symbol_dict "
                    "(ticker, code, name, market, pinyin_full, pinyin_abbr) "
                    "VALUES (?,?,?,?,?,?)",
                    rows,
                )
            logger.info("backfill_hk_names: 补全 %d 个港股名称", len(rows))
            return len(rows)
        except Exception as e:
            logger.error("backfill_hk_names failed: %s", e)
            return 0

    # ------------------------------------------------------------------ #
    # R-02 冷启动状态判定：字典为空 => 初始化中（供 UI 展示"初始化中"而非"未找到"）
    # ------------------------------------------------------------------ #
    def symbol_dict_ready(self) -> bool:
        """标的字典是否已就绪（存在至少一条记录）。

        用于区分冷启动初始化中（字典为空）与正常无匹配两种空结果状态。
        查询失败（表未建等）按未就绪处理。
        """
        try:
            df = self._db.query_df("SELECT COUNT(*) AS c FROM symbol_dict")
            return len(df) > 0 and int(df["c"][0]) > 0
        except Exception as e:
            logger.debug("symbol_dict_ready 查询失败，按未就绪处理: %s", e)
            return False

    # ------------------------------------------------------------------ #
    # R-20~R-24：标的搜索（只读 symbol_dict，三路匹配 + 排序截断）
    # ------------------------------------------------------------------ #
    def search_symbols(self, query: str) -> list[dict]:
        """标的搜索主入口（PRD FR-1.x）。

        新链路只读 symbol_dict，不触发任何实时 akshare 调用；R-50 legacy=true
        时回退旧的 symbol_cache + 实时搜索。返回结构化 dict 列表（含 code/name/
        market/pinyin_abbr），供下拉展示与选中卡片回填使用。
        """
        if self._use_legacy_search():
            return self._search_symbols_legacy(query)

        nq = normalize_query(query)          # R-20 归一化
        if len(nq) < 2:
            return []
        variants = code_variants(nq)         # R-21/R-01 零填充变体
        esc = escape_like(nq)                # R-22 LIKE 通配符转义
        like = f"%{esc}%"

        try:
            df = self._db.query_df(
                "SELECT ticker, code, name, market, pinyin_full, pinyin_abbr "
                "FROM symbol_dict WHERE "
                "UPPER(code) LIKE ? ESCAPE '\\' "
                "OR UPPER(name) LIKE ? ESCAPE '\\' "
                "OR UPPER(pinyin_full) LIKE ? ESCAPE '\\' "
                "OR UPPER(pinyin_abbr) LIKE ? ESCAPE '\\' "
                "LIMIT 200",
                [like, like, like, like],
            )
        except Exception as e:
            logger.error("search_symbols 查询失败 q=%r: %s", nq, e)
            return []

        rows = df.to_dicts() if len(df) > 0 else []
        if not rows:
            logger.info("search q=%r matched=0 returned=0", nq)  # R-40 埋点
            return []

        ranked = rank_results(rows, nq, variants, MAX_RESULTS)  # R-23 排序截断
        out = []
        for r in ranked:
            market_tag = "A股" if r.get("market") == "a_share" else "港股"
            abbr = (r.get("pinyin_abbr") or "").strip()
            label = f"[{market_tag}] {r['code']}  {r['name']}"
            if abbr:
                label += f"  ·{abbr}"
            out.append({
                "label": label,
                "value": r["ticker"],
                "code": r["code"],
                "name": r["name"],
                "market": r["market"],
                "pinyin_abbr": abbr,
            })
        logger.info("search q=%r matched=%d returned=%d", nq, len(rows), len(out))  # R-40
        return out

    # ------------------------------------------------------------------ #
    # R-50：旧搜索链路（保留以便回滚），仅当 search.legacy=true 时启用
    # ------------------------------------------------------------------ #
    def _search_symbols_legacy(self, query: str) -> list[dict]:
        if not query or len(query) < 2:
            return []
        results = []

        # 1. Search A-share cache
        try:
            cached = self._db.query_df(
                "SELECT code, name FROM symbol_cache WHERE code LIKE ? OR name LIKE ? LIMIT 20",
                [f"%{query}%", f"%{query}%"],
            )
            if len(cached) > 0:
                results.extend([
                    {"label": f"{r['code']} - {r['name']}", "value": f"{r['code']}"}
                    for r in cached.to_dicts()
                ])
        except Exception as e:
            logger.debug("A-share cache lookup failed: %s", e)

        # 2. Fetch A-share list and cache it (runs once)
        if not results:
            try:
                df = ak.stock_info_a_code_name()
                self._db.execute("CREATE TABLE IF NOT EXISTS symbol_cache (code VARCHAR PRIMARY KEY, name VARCHAR)")
                for _, r in df.iterrows():
                    self._db.execute("INSERT OR REPLACE INTO symbol_cache VALUES (?,?)",
                                     [r["code"], r["name"]])
                filtered = df[df["code"].str.contains(query) | df["name"].str.contains(query, na=False)]
                results.extend([
                    {"label": f"{r['code']} - {r['name']}", "value": f"{r['code']}"}
                    for _, r in filtered.head(20).iterrows()
                ])
            except Exception as e:
                logger.error("A-share search failed: %s", e)

        # 3. Search HK stocks
        try:
            hk_df = ak.stock_hk_spot()
            if "名称" in hk_df.columns and "代码" in hk_df.columns:
                hk_filtered = hk_df[
                    hk_df["代码"].astype(str).str.contains(query) |
                    hk_df["名称"].str.contains(query, na=False)
                ]
                for _, r in hk_filtered.head(10).iterrows():
                    hk_code = f"{int(r['代码']):05d}.HK"
                    label = f"{hk_code} - {r['名称']}"
                    # Avoid duplicates
                    if not any(label == x["label"] for x in results):
                        results.append({"label": label, "value": hk_code})
        except Exception as e:
            logger.debug("HK search failed: %s", e)

        return results[:20]

    def fetch_bars(self, symbols: list[str], start: str, end: str,
                   data_type: str = "daily", period: str = "") -> dict:
        import json
        results = {}
        for sym in symbols:
            try:
                code = sym.replace(".SH", "").replace(".SZ", "").replace(".HK", "")
                if data_type == "daily":
                    df = ak.stock_zh_a_hist(symbol=code, period="daily",
                                            start_date=start, end_date=end, adjust="")
                    if df is not None and not df.empty:
                        ticker = resolve_ticker(code, "a_share")
                        rows = []
                        for _, r in df.iterrows():
                            rows.append([ticker, str(r["日期"])[:10], float(r["开盘"]),
                                         float(r["最高"]), float(r["最低"]), float(r["收盘"]),
                                         int(r["成交量"]), float(r["成交额"]), "a_share", 1.0])
                        self._db.execute("DELETE FROM bars_daily WHERE ticker=?", [ticker])
                        self._db.execute_many(
                            "INSERT INTO bars_daily VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
                        results[sym] = {"status": "ok", "count": len(rows)}
                elif data_type == "minute":
                    df = ak.stock_zh_a_hist_min_em(symbol=code, period=period or "1",
                                                   start_date=start.replace("-", ""),
                                                   end_date=end.replace("-", ""))
                    if df is not None and not df.empty:
                        ticker = resolve_ticker(code, "a_share")
                        rows = []
                        for _, r in df.iterrows():
                            rows.append([ticker, str(r["时间"]), float(r["开盘"]),
                                         float(r["最高"]), float(r["最低"]), float(r["收盘"]),
                                         int(r["成交量"]), float(r["成交额"])])
                        self._db.execute("DELETE FROM bars_minute WHERE ticker=?", [ticker])
                        self._db.execute_many(
                            "INSERT INTO bars_minute VALUES (?,?,?,?,?,?,?,?)", rows)
                        results[sym] = {"status": "ok", "count": len(rows)}
                elif data_type == "financials":
                    df = ak.stock_financial_abstract(symbol=code)
                    if df is not None and not df.empty:
                        self._db.execute("CREATE TABLE IF NOT EXISTS financials "
                                         "(ticker VARCHAR, report_date VARCHAR, data JSON)")
                        self._db.execute("DELETE FROM financials WHERE ticker=?", [code])
                        for _, r in df.iterrows():
                            self._db.execute("INSERT INTO financials VALUES (?,?,?)",
                                             [code, str(r.iloc[0])[:10],
                                              json.dumps(r.to_dict(), ensure_ascii=False)])
                        results[sym] = {"status": "ok", "financials": True}
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
        # R-33：LEFT JOIN symbol_dict 带出名称列，过滤支持代码或名称。
        try:
            parts = [
                "SELECT b.ticker AS ticker, COALESCE(NULLIF(s.name, ''), '—') AS name,",
                "b.market AS market, COUNT(*) AS records,",
                "MIN(b.trade_date) AS start_date, MAX(b.trade_date) AS end_date",
                "FROM bars_daily b",
                "LEFT JOIN symbol_dict s ON s.ticker = b.ticker",
            ]
            params = []
            clauses = []
            if market_filter != "all":
                clauses.append("b.market = ?")
                params.append(market_filter)
            if text_filter and text_filter.strip():
                esc = escape_like(text_filter.strip())
                clauses.append("(b.ticker LIKE ? ESCAPE '\\' OR s.name LIKE ? ESCAPE '\\')")
                params.extend([f"%{esc}%", f"%{esc}%"])
            if clauses:
                parts.append("WHERE " + " AND ".join(clauses))
            parts.append("GROUP BY b.ticker, s.name, b.market ORDER BY b.ticker")
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
