import logging
import time
import random
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

from ...market.rate_limiter import get_global_limiter, RateLimitError, is_rate_limit_error


def _is_network_error(exc: Exception) -> bool:
    """粗略判断是否为网络层异常（超时 / 连接失败），与限流、无数据区分。"""
    msg = type(exc).__name__ + " " + str(exc)
    return any(k in msg for k in ("Timeout", "Connect", "Connection",
                                  "RemoteDisconnected", "ConnectionError",
                                  "Socket", "timed out", "NameResolution"))


def _retry_fetch(fn, attempts: int = 3, delay: float = 1.5, limiter=None):
    """akshare 东财系接口偶发瞬断，轻量重试；**每次请求前经限流器节流**，
    从源头消除"多标的请求突发→被数据源限流"。

    - 限流特征异常（429 / Max retries / 请求过于频繁 等）会触发限流器
      ``cool_down`` 自愈降速，并以 :class:`RateLimitError` 抛出，供上层归类为
      ``reason="rate_limited"``。
    - 普通异常按原退避重试；最终失败抛出最后一次异常（限流异常保留为 RateLimitError）。
    """
    if limiter is None:
        limiter = get_global_limiter()
    last_exc = None
    for i in range(attempts):
        limiter.acquire()  # 节流：未到速率窗口则在此阻塞
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if is_rate_limit_error(e):
                # 限流：降速自愈，并把异常升级为结构化限流错误
                limiter.cool_down(seconds=20.0 + 5.0 * i)
                last_exc = RateLimitError(str(e))
                logger.warning("Upstream rate-limited (attempt %d/%d): %s",
                               i + 1, attempts, e)
                if i < attempts - 1:
                    # 退避更长，给数据源喘息；cool_down 已叠加冷却
                    time.sleep(delay * (2 ** i) + random.uniform(0, 0.5))
            elif i < attempts - 1:
                time.sleep(delay)
    raise last_exc


class DataCenterService:
    def __init__(self, db: DuckDBManager, limiter: RateLimiter):
        self._db = db
        self._limiter = limiter
        self._legacy_search: bool | None = None
        from .cache_catalog_service import CacheCatalogService
        self._catalog = CacheCatalogService(db)

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

    @staticmethod
    def _bounds(rows, idx):
        """取第 idx 列（日期/时间）的 min/max，用于 catalog 边界。"""
        vals = [r[idx] for r in rows]
        return min(vals), max(vals)

    @staticmethod
    def _report_type(report_date: str) -> str:
        """由报告期 YYYY-MM-DD 推断报告类型（用于 financials.report_type）。"""
        md = (report_date or "")[:10]
        if len(md) >= 10:
            mm = md[5:7]
            if mm == "03":
                return "一季报"
            if mm == "06":
                return "中报"
            if mm == "09":
                return "三季报"
            if mm == "12":
                return "年报"
        return "unknown"

    @staticmethod
    def _convert_financials(ticker: str, df) -> tuple[list[list], str | None]:
        """将 stock_financial_abstract 的宽表归一化为 v5 financials 行
        (ticker, report_date, report_type, indicator, value, unit)。
        返回 (rows, 最新报告期)；解析不到则返回 ([], None)。
        """
        import math
        try:
            cols = list(df.columns)
        except Exception:
            return [], None
        date_col = None
        for c in cols:
            if "期" in str(c) or "日期" in str(c):
                date_col = c
                break
        if date_col is None and cols:
            date_col = cols[0]
        if date_col is None:
            return [], None
        indicator_cols = [c for c in cols if c != date_col]
        rows: list[list] = []
        fin_end: str | None = None
        for _, r in df.iterrows():
            try:
                rd = str(r[date_col])[:10]
            except Exception:
                continue
            if not rd or len(rd) < 10:
                continue
            rt = DataCenterService._report_type(rd)
            if fin_end is None or rd > fin_end:
                fin_end = rd
            for ic in indicator_cols:
                val = r[ic]
                if val is None:
                    continue
                try:
                    if isinstance(val, float) and math.isnan(val):
                        continue
                    v = float(val)
                except (ValueError, TypeError):
                    continue
                rows.append([ticker, rd, rt, str(ic), v, None])
        return rows, fin_end

    def fetch_bars(self, symbols: list[str], start: str, end: str,
                   data_type: str = "daily", period: str = "",
                   conservative: bool = False) -> dict:
        results = {}
        # akshare 东财系接口只接受 YYYYMMDD；日期选择器给出 ISO（带横线），统一转换
        start_compact = (start or "").replace("-", "")
        end_compact = (end or "").replace("-", "")
        # FR-7：循环前**批量**查一次覆盖度，避免逐标的重复查询
        coverage = {}
        try:
            coverage = self._catalog.get_coverage_for_tickers(list(symbols))
        except Exception:
            coverage = {}
        # FR-5：保守模式 → 临时降速（finally 恢复默认速率）
        if conservative:
            self._limiter.set_rate(max(5, int(self._limiter._default_max // 2)))
        try:
            for sym in symbols:
                try:
                    is_hk = sym.upper().endswith(".HK")
                    code = sym.replace(".SH", "").replace(".SZ", "").replace(".HK", "")
                    market = "hk_connect" if is_hk else "a_share"
                    if data_type == "minute":
                        # FR-7：已完全覆盖则跳过，不发起请求（降低限流面）
                        cov = coverage.get(sym)
                        if (cov and cov.get("has_minute")
                                and period in (cov.get("minute_periods") or "")
                                and cov.get("minute_start") and cov.get("minute_end")
                                and (start or "") >= str(cov.get("minute_start"))[:10]
                                and (end or "") <= str(cov.get("minute_end"))[:10]):
                            results[sym] = {"status": "skipped", "reason": "cached",
                                            "error": "已缓存，区间已覆盖，跳过"}
                            continue
                    if data_type == "daily":
                        if is_hk:
                            # 港股：stock_hk_daily 返回全量历史，按区间过滤
                            df = _retry_fetch(lambda: ak.stock_hk_daily(symbol=code),
                                             limiter=self._limiter)
                            if df is None or df.empty:
                                results[sym] = {"status": "failed", "reason": "no_data",
                                               "error": "该区间无数据"}
                                continue
                            rows = []
                            for _, r in df.iterrows():
                                d = r["date"]
                                ds = (d.strftime("%Y-%m-%d") if hasattr(d, "strftime")
                                      else str(d)[:10])
                                if (start and ds < start) or (end and ds > end):
                                    continue
                                rows.append([sym, ds, float(r["open"]), float(r["high"]),
                                             float(r["low"]), float(r["close"]),
                                             int(r.get("volume", 0) or 0), 0.0,
                                             "hk_connect", 1.0])
                            if not rows:
                                results[sym] = {"status": "failed", "reason": "no_data",
                                               "error": "该区间无数据"}
                                continue
                            s, e = self._bounds(rows, 1)
                            # 同一事务：删旧 + 写新 + 更新 catalog 覆盖度（FR-1.2 / FR-1.6）
                            with self._db.transaction() as conn:
                                conn.execute("DELETE FROM bars_daily WHERE ticker=?", [sym])
                                conn.executemany(
                                    "INSERT INTO bars_daily VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
                                self._catalog.record_coverage(
                                    conn, sym, market, data_type="daily", start=s, end=e)
                            results[sym] = {"status": "ok", "count": len(rows)}
                            continue
                        df = _retry_fetch(lambda: ak.stock_zh_a_hist(
                            symbol=code, period="daily",
                            start_date=start_compact, end_date=end_compact, adjust=""),
                            limiter=self._limiter)
                        if df is not None and not df.empty:
                            ticker = resolve_ticker(code, "a_share")
                            rows = []
                            for _, r in df.iterrows():
                                rows.append([ticker, str(r["日期"])[:10], float(r["开盘"]),
                                             float(r["最高"]), float(r["最低"]), float(r["收盘"]),
                                             int(r["成交量"]), float(r["成交额"]), "a_share", 1.0])
                            s, e = self._bounds(rows, 1)
                            with self._db.transaction() as conn:
                                conn.execute("DELETE FROM bars_daily WHERE ticker=?", [ticker])
                                conn.executemany(
                                    "INSERT INTO bars_daily VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
                                self._catalog.record_coverage(
                                    conn, ticker, "a_share", data_type="daily", start=s, end=e)
                            results[sym] = {"status": "ok", "count": len(rows)}
                        else:
                            results[sym] = {"status": "failed", "reason": "no_data",
                                            "error": "该区间无数据"}
                    elif data_type == "minute":
                        if is_hk:
                            results[sym] = {"status": "failed", "reason": "unsupported",
                                            "error": "分钟线暂仅支持 A 股"}
                            continue
                        effective_period = period or "5"  # 取数口径与落库口径必须一致（多周期）
                        df = _retry_fetch(lambda: ak.stock_zh_a_hist_min_em(
                            symbol=code, period=effective_period,
                            start_date=start_compact, end_date=end_compact),
                            limiter=self._limiter)
                        if df is not None and not df.empty:
                            ticker = resolve_ticker(code, "a_share")
                            rows = []
                            for _, r in df.iterrows():
                                rows.append([ticker, str(r["时间"]), float(r["开盘"]),
                                             float(r["最高"]), float(r["最低"]), float(r["收盘"]),
                                             int(r["成交量"]), float(r["成交额"]),
                                             "a_share", effective_period])
                            s, e = self._bounds(rows, 1)
                            # 多周期分钟线：DELETE 仅命中该 period，避免不同周期互相覆盖（PK 含 period）
                            with self._db.transaction() as conn:
                                conn.execute(
                                    "DELETE FROM bars_minute WHERE ticker=? AND period=?",
                                    [ticker, effective_period])
                                conn.executemany(
                                    "INSERT INTO bars_minute "
                                    "(ticker, bar_time, open, high, low, close, volume, amount, market, period) "
                                    "VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
                                self._catalog.record_coverage(
                                    conn, ticker, "a_share", data_type="minute", start=s,
                                    end=e, period=effective_period)
                            results[sym] = {"status": "ok", "count": len(rows)}
                        else:
                            results[sym] = {"status": "failed", "reason": "no_data",
                                            "error": "该区间无数据"}
                    elif data_type == "financials":
                        # v5 financials 表：(ticker, report_date, report_type, indicator, value, unit)
                        df = _retry_fetch(lambda: ak.stock_financial_abstract(symbol=code),
                                     limiter=self._limiter)
                        if df is not None and not df.empty:
                            rows, fin_end = self._convert_financials(sym, df)
                            if not rows:
                                results[sym] = {"status": "failed", "reason": "no_data",
                                               "error": "无财务数据"}
                                continue
                            with self._db.transaction() as conn:
                                conn.execute("DELETE FROM financials WHERE ticker=?", [sym])
                                conn.executemany(
                                    "INSERT INTO financials "
                                    "(ticker, report_date, report_type, indicator, value, unit) "
                                    "VALUES (?,?,?,?,?,?)", rows)
                                self._catalog.record_coverage(
                                    conn, sym, market, data_type="financials",
                                    fin_report_end=fin_end)
                            results[sym] = {"status": "ok", "financials": True}
                        else:
                            results[sym] = {"status": "failed", "reason": "no_data",
                                            "error": "无财务数据"}
                    elif data_type == "adj":
                        # FR-2.4（Task #21）：复权因子入库。A 股仅——由 stock_zh_a_daily
                        # 的 qfq_factor / hfq_factor 因子序列回填 adj_factors（PK ticker,trade_date,adj_type）。
                        # 港股无复权因子口径，直接失败（与财务同策略）。
                        if is_hk:
                            results[sym] = {"status": "failed", "reason": "unsupported",
                                            "error": "复权因子仅支持 A 股"}
                            continue
                        ticker = resolve_ticker(code, "a_share")
                        exch = "sh" if code.startswith(("6", "5", "9")) else "sz"
                        adj_rows = []
                        adj_fetched = False
                        for adj_type, factor_col in (("qfq", "qfq_factor"),
                                                     ("hfq", "hfq_factor")):
                            try:
                                df = _retry_fetch(lambda: ak.stock_zh_a_daily(
                                    symbol=f"{exch}{code}", start_date=start_compact,
                                    end_date=end_compact, adjust=f"{adj_type}_factor"),
                                    limiter=self._limiter)
                            except Exception:
                                df = None
                            if df is None or (hasattr(df, "empty") and df.empty):
                                continue
                            adj_fetched = True
                            for _, r in df.iterrows():
                                d = r["date"]
                                ds = (d.strftime("%Y-%m-%d") if hasattr(d, "strftime")
                                      else str(d)[:10])
                                if (start and ds < start) or (end and ds > end):
                                    continue
                                adj_rows.append([ticker, ds, adj_type,
                                                 float(r[factor_col])])
                        if not adj_fetched or not adj_rows:
                            results[sym] = {"status": "failed",
                                            "reason": "no_data",
                                            "error": "该区间无复权因子数据"}
                            continue
                        with self._db.transaction() as conn:
                            conn.executemany(
                                "INSERT OR REPLACE INTO adj_factors "
                                "(ticker, trade_date, adj_type, adj_factor) "
                                "VALUES (?,?,?,?)", adj_rows)
                            # qfq 作为默认展示口径写入 adj_type；两种因子均入库于 adj_factors
                            self._catalog.record_coverage(
                                conn, ticker, "a_share", data_type="adj", adj_type="qfq")
                        results[sym] = {"status": "ok", "adj": True,
                                        "count": len(adj_rows)}
                except Exception as ex:
                    if isinstance(ex, RateLimitError):
                        results[sym] = {"status": "failed", "reason": "rate_limited",
                                        "error": "数据源限流，已自动降速，建议稍后重试或减少标的数"}
                    elif _is_network_error(ex):
                        results[sym] = {"status": "failed", "reason": "network",
                                        "error": "网络异常，请检查连接后重试"}
                    else:
                        results[sym] = {"status": "failed", "reason": "no_data",
                                        "error": str(ex)[:80]}
        finally:
            if conservative:
                self._limiter.reset_rate()
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

    def get_adj_factor_series(self, ticker: str, adj_type: str = "qfq") -> list[tuple]:
        """FR-2.4 / Task #22 复用：读取某标的复权因子序列。

        返回 [(trade_date:str, adj_factor:float), ...] 按日期升序；无数据返回空列表。
        口径 adj_type ∈ {qfq, hfq}。
        """
        try:
            df = self._db.query_df(
                "SELECT trade_date, adj_factor FROM adj_factors "
                "WHERE ticker=? AND adj_type=? ORDER BY trade_date",
                [ticker, adj_type])
            return [(str(r["trade_date"])[:10], float(r["adj_factor"]))
                    for r in df.to_dicts()]
        except Exception as e:
            logger.error("get_adj_factor_series failed ticker=%s: %s", ticker, e)
            return []

    def has_adj_factor(self, ticker: str, adj_type: str = "qfq") -> bool:
        """FR-2.4：判断某标的是否已缓存指定口径的复权因子。"""
        try:
            df = self._db.query_df(
                "SELECT 1 FROM adj_factors WHERE ticker=? AND adj_type=? LIMIT 1",
                [ticker, adj_type])
            return len(df) > 0
        except Exception:
            return False

    def get_minute_bars(self, ticker: str, period: str = "5", limit: int = 240) -> list[dict]:
        """FR-2.2 / Task #25 多周期：按 (ticker, period) 读取分钟线（窗口内，默认近 240 根）。

        返回 [{bar_time, open, high, low, close, volume}, ...] 按时间升序；无数据返回空列表。
        period 精确命中 bars_minute 复合主键的 period 维度，不同周期互不串扰。
        """
        try:
            df = self._db.query_df(
                "SELECT bar_time, open, high, low, close, volume FROM bars_minute "
                "WHERE ticker=? AND period=? ORDER BY bar_time DESC LIMIT ?",
                [ticker, period or "5", int(limit)])
            rows = df.to_dicts() if len(df) > 0 else []
            rows.reverse()  # 升序，供 K 线从左到右
            return rows
        except Exception as e:
            logger.error("get_minute_bars failed ticker=%s period=%s: %s",
                         ticker, period, e)
            return []

    # data_type -> 物理表删除语句（按类型删除，FR-1.5）
    _TYPE_DELETE_SQL = {
        "daily": ["DELETE FROM bars_daily WHERE ticker=?"],
        "minute": ["DELETE FROM bars_minute WHERE ticker=?"],
        "realtime": ["DELETE FROM snapshots WHERE ticker=?"],
        "adj": ["DELETE FROM adj_factors WHERE ticker=?"],
        "financials": ["DELETE FROM financials WHERE ticker=?"],
    }

    def delete_symbols(self, tickers: list[str]) -> int:
        """整行删除：清除全部 5 类物理数据 + cache_catalog 目录行（同事务，验收 11）。"""
        count = 0
        for t in tickers:
            try:
                with self._db.transaction() as conn:
                    for sqls in self._TYPE_DELETE_SQL.values():
                        for sql in sqls:
                            conn.execute(sql, [t])
                    conn.execute("DELETE FROM cache_catalog WHERE ticker=?", [t])
                count += 1
            except Exception as e:
                logger.error("Failed to delete %s: %s", t, e)
        return count

    def delete_symbols_by_type(self, tickers: list[str], data_type: str) -> int:
        """按类型删除：仅删该类物理数据，同事务将 has_<type> 置 FALSE、边界置 NULL；
        其他类型数据与覆盖标记不受影响（FR-1.5 / 验收 11）。"""
        sqls = self._TYPE_DELETE_SQL.get(data_type)
        if not sqls:
            logger.error("delete_symbols_by_type: 未知数据类型 %s", data_type)
            return 0
        count = 0
        for t in tickers:
            try:
                with self._db.transaction() as conn:
                    for sql in sqls:
                        conn.execute(sql, [t])
                    self._catalog.clear_coverage(conn, t, data_type)
                count += 1
            except Exception as e:
                logger.error("Failed to delete %s type=%s: %s", t, data_type, e)
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
