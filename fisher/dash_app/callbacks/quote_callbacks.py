import datetime
import logging

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, no_update, html, dash_table, ctx
from urllib.parse import parse_qs, urlencode

from fisher.store.engine import DuckDBManager
from ..services.cache_catalog_service import CacheCatalogService
from ..services import get_data_service

logger = logging.getLogger(__name__)


QB_WATCHLIST_FILE = "data/watchlist.json"

# 覆盖度徽标顺序（U-1）：日/分/实/复
_BADGE_ORDER = [
    ("日", "has_daily"),
    ("分", "has_minute"),
    ("实", "has_realtime"),
    ("复", "has_adj"),
    ("财", "has_financials"),
]

_BADGE_NAMES = {
    "日": "日线", "分": "分钟线", "实": "实时快照",
    "复": "复权因子", "财": "财务数据",
}


# --------------------------------------------------------------------------- #
# DB / 目录辅助
# --------------------------------------------------------------------------- #
def _get_db():
    """获取数据库连接，自动初始化 schema（防止空库无表导致的查询失败）。"""
    db = DuckDBManager()
    if not db._initialized:
        try:
            db.connect("./data/fisherquant.db", read_pool_size=4)
            from ..store.schema import init_schema
            init_schema(db)
        except Exception:
            pass
    return db


def _catalog() -> CacheCatalogService:
    return CacheCatalogService(_get_db())


def _get_cached_symbols():
    """IC-3：下拉仅出已缓存标的（has_daily OR has_minute），避免加入死标。

    无缓存数据时返回空列表（看板「添加」不可用，符合 FR-5.2 防死标）。
    """
    try:
        cat = _catalog()
        tickers = cat.get_tickers_with_data()
        if tickers:
            db = _get_db()
            rows = db.query_df(
                "SELECT ticker, name FROM symbol_dict WHERE ticker IN ({})".format(
                    ",".join("?" for _ in tickers)), list(tickers))
            names = {r["ticker"]: r["name"] for r in rows.to_dicts()}
            return [{"label": f"{t} {names.get(t, '')}".strip(), "value": t}
                    for t in sorted(tickers)]
        return []
    except Exception:
        return []


def _is_dead_symbol(sym: str) -> bool:
    """FR-5.2/FR-5.3：若目录可读取且非空，则不在已缓存宇宙内的标的视为死标。

    目录读取失败或为空（如测试 / 未初始化）时 fail-open 返回 False，不拦截添加。
    """
    try:
        cached = _catalog().get_tickers_with_data()
    except Exception:
        return False
    if not cached:
        return False
    return sym not in cached


def _load_watchlist():
    import json
    from pathlib import Path
    try:
        return json.loads(Path(QB_WATCHLIST_FILE).read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_watchlist(items):
    import json
    from pathlib import Path
    Path(QB_WATCHLIST_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(QB_WATCHLIST_FILE).write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")


def _prune_watchlist(wl=None):
    """FR-5.3 / T-4：清理 watchlist 中的死标（不在 cache_catalog 任何覆盖类型内）。

    wl 为待裁剪列表；None 时从 watchlist.json 加载。返回 (kept, removed)。
    fail-open：目录不可读或为空时不裁剪（kept==wl，removed==[]），避免误删全新用户自选；
    单标查询异常时保守保留该标。有变更由调用方负责回写文件。
    """
    if wl is None:
        wl = _load_watchlist() or []
    if not wl:
        return wl, []
    try:
        cat = _catalog()
        kept, removed = [], []
        for s in wl:
            try:
                alive = bool(cat.has_any_data(s))
            except Exception:
                alive = True  # 单标查询异常 → 保留
            (kept if alive else removed).append(s)
    except Exception:
        return wl, []  # 目录不可读 → 不裁剪
    return kept, removed


# --------------------------------------------------------------------------- #
# 行情数据：快照优先 + 日线降级（FR-6 / 验收 15）
# --------------------------------------------------------------------------- #
def _safe_coverage(tickers) -> dict:
    try:
        return _catalog().get_coverage_for_tickers(list(tickers))
    except Exception:
        return {}


def _safe_snapshots(tickers) -> dict:
    try:
        db = _get_db()
        ph = ",".join("?" for _ in tickers)
        df = db.query_df(
            "SELECT ticker, last_price, pre_close, change_pct, volume, ts "
            f"FROM snapshots WHERE ticker IN ({ph})", list(tickers))
        return {r["ticker"]: r for r in df.to_dicts()} if len(df) > 0 else {}
    except Exception:
        return {}


def _coverage_badges(cov_row) -> str:
    """U-1：紧凑 icon-only 徽标组（✓绿 ✗灰），hover 出类型名。Task #24 扩展第 5 类「财」。"""
    if not cov_row:
        return ""
    spans = []
    for label, flag in _BADGE_ORDER:
        has = bool(cov_row.get(flag))
        color = "#28a745" if has else "#c8ccd0"
        name = _BADGE_NAMES.get(label, label)
        spans.append(
            f'<span title="{name}" style="color:{color};font-weight:600;'
            f'margin-right:3px">{label}{"✓" if has else "✗"}</span>')
    return "".join(spans)


def _fmt_volume(v) -> str:
    try:
        return f"{float(v):,.0f}"
    except Exception:
        return "-"


def _adj_factor(db, sym, trade_date, mode):
    """FR-2.4 / Task #22：读取某标的指定日期的复权因子。

    mode ∈ {qfq, hfq}；无数据 / 异常返回 None（fail-open，降级为不复权，避免静默错误）。
    """
    if mode not in ("qfq", "hfq"):
        return None
    try:
        df = db.query_df(
            "SELECT adj_factor FROM adj_factors "
            "WHERE ticker=? AND adj_type=? AND trade_date=?",
            [sym, mode, trade_date])
        return float(df["adj_factor"][0]) if len(df) > 0 else None
    except Exception:
        return None


def _quote_row(sym, snap, cov, adj_mode="none", name_map=None):
    """构建单行行情数据：快照优先，无快照降级日线（FR-6.1/6.2）。

    adj_mode ∈ {none, qfq, hfq}：仅日线降级路径按复权口径换算最新价与涨跌幅
    （FR-2.4 / Task #22 口径一致性）；实时快照为实际成交价，不受复权影响。
    name_map 为 ticker→中文名映射（FR-3），无映射时降级显示代码片段。
    """
    cnt = sym.split(".")[0]
    display_name = (name_map or {}).get(sym) or cnt
    daily_fallback = False
    if snap and snap.get("last_price") is not None:
        last = float(snap["last_price"])
        pct = float(snap["change_pct"]) if snap.get("change_pct") is not None else 0.0
        vol = snap.get("volume")
        change_raw = pct
    else:
        # 降级：bars_daily 末两日涨跌口径（FR-6.2）；按复权口径换算（FR-2.4 / Task #22）
        daily_fallback = True
        db = _get_db()
        df = db.query_df(
            "SELECT close, volume, trade_date FROM bars_daily WHERE ticker=? "
            "ORDER BY trade_date DESC LIMIT 2", [sym])
        n = len(df)
        if n >= 2:
            close_t = float(df["close"][0]); date_t = str(df["trade_date"][0])[:10]
            close_p = float(df["close"][1]); date_p = str(df["trade_date"][1])[:10]
            vol = df["volume"][0]
            if adj_mode in ("qfq", "hfq"):
                f_t = _adj_factor(db, sym, date_t, adj_mode)
                f_p = _adj_factor(db, sym, date_p, adj_mode)
                if adj_mode == "qfq" and f_t:
                    # 前复权：以最新日因子为基准归一，最新日≈不复权价
                    last = close_t
                    prev = close_p * f_p / f_t if f_p is not None else close_p
                elif adj_mode == "hfq" and f_t is not None and f_p is not None:
                    last = close_t * f_t
                    prev = close_p * f_p
                else:
                    last, prev = close_t, close_p
            else:
                last, prev = close_t, close_p
            pct = (last - prev) / prev * 100 if prev and prev > 0 else 0.0
            change_raw = pct
        elif n == 1:
            last = float(df["close"][0])
            vol = df["volume"][0]
            pct = 0.0
            change_raw = 0.0
        else:
            raise ValueError("no bars")

    realtime_status = (
        '<span style="color:#28a745;font-weight:600" title="实时快照">实时✓</span>'
        if not daily_fallback else
        '<span style="color:#f0ad4e;font-weight:600" title="无实时快照，降级日频">实时✗(日频)</span>'
    )
    return {
        "code": sym,
        "name": display_name,
        "last_price": f"{last:.2f}" if last is not None else "-",
        "change_pct": f"{pct:+.2f}%" if pct is not None else "-",
        "volume": _fmt_volume(vol) if vol is not None else "-",
        "volume_raw": vol,
        "change_raw": change_raw,
        "coverage": _coverage_badges(cov),
        "realtime_status": realtime_status,
        "daily_fallback": daily_fallback,
        "goto_cache": _goto_cache_link(sym),
    }


def _empty_row(sym, cov, name_map=None):
    cnt = sym.split(".")[0]
    display_name = (name_map or {}).get(sym) or cnt
    return {
        "code": sym, "name": display_name, "last_price": "-",
        "change_pct": "-", "volume": "-", "volume_raw": None,
        "change_raw": 0.0, "coverage": _coverage_badges(cov),
        "realtime_status": '<span style="color:#c8ccd0" title="无数据">—</span>',
        "daily_fallback": True,
        "goto_cache": _goto_cache_link(sym),
    }


def _goto_cache_link(sym, data_type="daily"):
    """行情看板行内「去补齐」链接（FR-2）：落到获取数据页并携带 focus，
    由数据中心 consume_cache_intent 消费预填待缓存池（不再带无效的 tab=tab-cached）。"""
    return f"[去补齐](/data-center?focus={sym}&data_type={data_type})"


def _fetch_quote_data(symbols, adj_mode="none"):
    """FR-6 行情源切换 + FR-4.1 覆盖度徽标：快照优先，缺则降级日线。
    adj_mode 透传复权口径（FR-2.4 / Task #22）。
    FR-3：从 symbol_dict 加载中文名称映射。"""
    cov = _safe_coverage(symbols)
    snap = _safe_snapshots(symbols)
    # FR-3：生成 ticker→中文名映射
    name_map = {}
    try:
        db = _get_db()
        ph = ",".join("?" for _ in symbols)
        df = db.query_df(
            "SELECT ticker, name FROM symbol_dict WHERE ticker IN ({})".format(ph),
            list(symbols))
        for r in df.to_dicts():
            name_map[r["ticker"]] = r["name"]
    except Exception:
        pass
    data = []
    for sym in symbols:
        try:
            data.append(_quote_row(sym, snap.get(sym), cov.get(sym), adj_mode, name_map))
        except Exception:
            data.append(_empty_row(sym, cov.get(sym), name_map))
    return data


# --------------------------------------------------------------------------- #
# 表格渲染
# --------------------------------------------------------------------------- #
def _build_quote_table(data, highlight=None):
    columns = [
        {"name": "代码", "id": "code"},
        {"name": "名称", "id": "name"},
        {"name": "最新价", "id": "last_price"},
        {"name": "涨跌幅", "id": "change_pct"},
        {"name": "成交量", "id": "volume"},
        {"name": "覆盖度", "id": "coverage", "presentation": "markdown"},
        {"name": "实时", "id": "realtime_status", "presentation": "markdown"},
        {"name": "去缓存", "id": "goto_cache", "presentation": "markdown"},
        {"name": "", "id": "remove"},  # FR-1.1：× 删除列
    ]
    for r in data:
        r.setdefault("remove", "×")
    style_data_conditional = [
        {"if": {"filter_query": "{change_raw} > 0", "column_id": "change_pct"},
         "color": "#dc3545"},
        {"if": {"filter_query": "{change_raw} < 0", "column_id": "change_pct"},
         "color": "#198754"},
        {"if": {"row_index": "odd"}, "backgroundColor": "#fafbfc"},
        # FR-1.1：× 删除列窄对齐 + hover 提示色
        {"if": {"column_id": "remove"},
         "textAlign": "center", "cursor": "pointer",
         "maxWidth": 36, "minWidth": 36, "width": 36,
         "color": "#dc3545", "fontWeight": "bold", "fontSize": "16px"},
    ]
    if highlight:
        style_data_conditional.append(
            {"if": {"filter_query": "{code} = '" + highlight + "'"},
             "backgroundColor": "#fff3cd", "fontWeight": "bold"})
    return dash_table.DataTable(
        id="qb-data-table",
        columns=columns,
        data=data,
        row_selectable="multi",
        page_size=15,
        markdown_options={"html": True},
        filter_action="custom",
        filter_query="",
        tooltip_data=[
            {"volume": {"value": f"原始值：{r.get('volume_raw', '-')}", "type": "markdown"},
             "remove": {"value": "移除此标的", "type": "markdown"}}
            for r in data
        ],
        tooltip_duration=2000,
        style_table={"overflowX": "auto"},
        style_cell={"padding": "8px", "fontSize": "13px"},
        style_header={"backgroundColor": "#f8f9fa", "fontWeight": "bold"},
        style_data_conditional=style_data_conditional,
    )


# --------------------------------------------------------------------------- #
# 回调注册
# --------------------------------------------------------------------------- #
def register_quote_callbacks(app):
    @app.callback(
        Output("qb-add-symbol-dropdown", "options"),
        Input("url", "pathname"),
    )
    def load_qb_symbols(pathname):
        # D4：初始加载已缓存标的
        return _get_cached_symbols()

    # W2：用户输入时动态全量搜索
    @app.callback(
        Output("qb-add-symbol-dropdown", "options", allow_duplicate=True),
        Input("qb-add-symbol-dropdown", "search_value"),
        prevent_initial_call=True,
    )
    def search_full_market(search_value):
        if not search_value or len(search_value.strip()) < 1:
            return no_update
        try:
            svc = get_data_service()
            matches = svc.search_symbols(search_value.strip())
            if not matches:
                return [{"label": "未找到匹配标的（试试代码、名称或拼音）", "value": "", "disabled": True}]
            # 前 20 个匹配项
            return [
                {"label": f"{m.get('name','')} {m.get('code','')}".strip(), "value": m["value"]}
                for m in matches[:20]
            ]
        except Exception:
            return [{"label": "搜索服务暂时不可用", "value": "", "disabled": True}]

    @app.callback(
        Output("qb-watchlist-store", "data", allow_duplicate=True),
        Output("qb-table-container", "children", allow_duplicate=True),
        Input("qb-add-btn", "n_clicks"),
        Input("qb-manual-refresh", "n_clicks"),
        Input("qb-refresh-interval", "n_intervals"),
        State("qb-add-symbol-dropdown", "value"),
        State("qb-watchlist-store", "data"),
        State("qb-adj-mode", "value"),  # FR-5：透传复权口径
        prevent_initial_call=True,
    )
    def update_watchlist(add_clicks, refresh_clicks, auto_interval, new_symbol, watchlist, adj_mode):
        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else ""

        # FR-5.3 / T-4：加载/刷新前清理死标（保留 store 中尚未落盘的焦点符号，
        # fail-open：目录不可读/为空不裁剪）
        wl = list(watchlist or []) or _load_watchlist() or []
        kept, removed = _prune_watchlist(wl)
        if removed:
            logger.info("watchlist_pruned removed=%s", removed)
            wl = kept
            _save_watchlist(wl)
        watchlist = wl

        if triggered_id == "qb-add-btn" and new_symbol:
            # W2：支持 multi=True（list）和旧版单值兼容
            symbols_to_add = new_symbol if isinstance(new_symbol, list) else [new_symbol]
            for sym in symbols_to_add:
                if not sym or sym in watchlist:
                    continue
                watchlist.append(sym)
                # W2：自动触发一次日线获取（非缓存标的填入数据）
                try:
                    svc = get_data_service()
                    svc.fetch_bars([sym], "", "", "daily")
                except Exception:
                    logger.debug("auto_fetch_bars for %s failed (will fill on next refresh)", sym)
            _save_watchlist(watchlist)

        if not watchlist:
            return watchlist, html.Div("自选列表为空，请添加标的", className="text-muted text-center mt-4")

        table_data = _fetch_quote_data(watchlist, adj_mode)
        return watchlist, _build_quote_table(table_data)

    @app.callback(
        Output("qb-refresh-interval", "disabled"),
        Input("qb-auto-refresh-toggle", "value"),
    )
    def toggle_auto_refresh(enabled):
        return not enabled

    @app.callback(
        Output("qb-trading-status", "data"),
        Input("url", "pathname"),
        Input("qb-refresh-interval", "n_intervals"),  # FR-6：心跳保持交易状态更新
    )
    def check_trading_hours(pathname, n_intervals):
        import datetime
        now = datetime.datetime.now()
        weekday = now.weekday()
        if weekday >= 5:
            return False
        hour = now.hour
        minute = now.minute
        if hour < 9 or (hour == 9 and minute < 15):
            return False
        if (hour == 11 and minute >= 30) or hour == 12:
            return False
        if hour >= 15:
            return False
        return True

    @app.callback(
        Output("qb-health-div", "children"),
        Input("qb-watchlist-store", "data"),
    )
    def render_health(watchlist):
        """FR-4.3：看板健康度仪表盘——实时/分钟覆盖率汇总 + 批量去缓存入口。
        FR-7：仅池变化时重建，去除 n_intervals（避免60秒心跳闪烁）。"""
        watchlist = watchlist or []
        cov = _safe_coverage(watchlist)
        total = len(watchlist)
        rt = sum(1 for t in watchlist if (cov.get(t) or {}).get("has_realtime"))
        mn = sum(1 for t in watchlist if (cov.get(t) or {}).get("has_minute"))
        if total == 0:
            return html.Span("自选为空，添加标的前往「数据查询」获取缓存",
                             className="text-muted")
        missing = total - max(rt, mn)
        return html.Div([
            html.Span(f"看板 {total} 标的：实时覆盖 {rt}/{total}，分钟覆盖 {mn}/{total}",
                     className="me-3"),
            dbc.Button("批量去缓存补齐", id="qb-batch-cache-btn", color="info",
                      size="sm", outline=True),
        ], className="d-flex align-items-center")

    @app.callback(
        Output("qb-watchlist-store", "data", allow_duplicate=True),
        Output("qb-table-container", "children", allow_duplicate=True),
        Output("url", "search", allow_duplicate=True),
        Output("qb-chart-symbol", "data", allow_duplicate=True),  # FR-2.3：焦点标的作为图表标的
        Input("url", "search"),
        State("url", "pathname"),
        State("qb-watchlist-store", "data"),
        prevent_initial_call=True,
    )
    def consume_focus_board(search, pathname, watchlist):
        """FR-3.3 / IC-1 / U-2：看板消费 ?focus=<ticker>。

        - 仅当该标的在 cache_catalog 有任意覆盖时才入自选（防死标）；
        - 命中则置顶高亮并显示其行情；
        - 消费后清除 ?focus=，避免手动刷新反复置顶。
        - FR-2.3：设置 qb-chart-symbol 为焦点标的。
        """
        if not search or pathname != "/market-watch":
            return no_update, no_update, no_update, no_update
        q = parse_qs(search.lstrip("?"))
        focus = (q.get("focus") or [None])[0]
        if not focus:
            return no_update, no_update, no_update, no_update

        wl = list(watchlist or [])
        if focus not in wl:
            if _catalog().has_any_data(focus):
                wl.append(focus)
            else:
                # 死标：不入自选，仅清除参数（FR-5.3 结构性归零思路）
                return no_update, no_update, _strip_focus(search), no_update

        # 联动 A（FR-3.1 / FR-7.5）：纳入自动加载宇宙（idempotent）
        try:
            _catalog().set_auto_load_enabled(focus, True)
        except Exception:
            pass

        if focus in wl:
            wl.remove(focus)
            wl.insert(0, focus)  # 置顶高亮
        data = _fetch_quote_data(wl)
        return wl, _build_quote_table(data, highlight=focus), _strip_focus(search), focus

    @app.callback(
        Output("url", "pathname", allow_duplicate=True),
        Output("url", "search", allow_duplicate=True),
        Input("qb-batch-cache-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def batch_goto_cache(n_clicks):
        """FR-2（行情看板体验优化）：一键批量去缓存——携带全部自选标的跳转获取数据页
        预填待缓存池（consume_cache_intent 消费），上限 20 个。"""
        if not n_clicks:
            return no_update, no_update
        wl = _load_watchlist() or []
        if not wl:
            return no_update, no_update
        symbols = ",".join(wl[:20])
        return "/data-center", f"?symbols={symbols}"

    @app.callback(
        # FR-5.3 / T-4：导航到行情看板即清理死标并即时渲染（首次加载也生效，无空白死行）
        # allow_duplicate + 首触发必须用 'initial_duplicate'（Dash 校验要求），
        # 否则与 update_watchlist / consume_focus_board 共享输出报 DuplicateCallback。
        Output("qb-watchlist-store", "data", allow_duplicate=True),
        Output("qb-table-container", "children", allow_duplicate=True),
        Output("qb-chart-symbol", "data"),  # FR-2.3：初始化图表标的为首个
        Input("url", "pathname"),
        prevent_initial_call="initial_duplicate",
    )
    def prune_watchlist_on_load(pathname):
        if pathname != "/market-watch":
            return no_update, no_update, no_update
        wl = _load_watchlist() or []
        kept, removed = _prune_watchlist(wl)
        if removed:
            logger.info("watchlist_pruned removed=%s", removed)
            _save_watchlist(kept)
        if not kept:
            return kept, html.Div("自选列表为空，请添加标的", className="text-muted text-center mt-4"), None
        return kept, _build_quote_table(_fetch_quote_data(kept)), kept[0]


    @app.callback(
        # FR-2.4 / Task #22：复权口径切换时按当前口径重渲染行情表。
        # 不复权为默认（risk #3：新口径上线前保持日线未复权展示，避免静默错误）。
        Output("qb-table-container", "children", allow_duplicate=True),
        Input("qb-adj-mode", "value"),
        State("qb-watchlist-store", "data"),
        prevent_initial_call=True,
    )
    def rerender_on_adj_mode(adj_mode, watchlist):
        wl = list(watchlist or []) or _load_watchlist() or []
        if not wl:
            return html.Div("自选列表为空，请添加标的", className="text-muted text-center mt-4")
        return _build_quote_table(_fetch_quote_data(wl, adj_mode))

    # ------------------------------------------------------------------ #
    # W1：看板内筛选——输入即过滤（客户端，零网络开销）
    # ------------------------------------------------------------------ #
    @app.callback(
        Output("qb-data-table", "filter_query", allow_duplicate=True),
        Input("qb-table-filter", "value"),
        prevent_initial_call=True,
    )
    def table_filter(filter_value):
        """W1：实时筛选表格行（代码/名称匹配，不区分大小写）。

        使用 Dash DataTable 的 filter_query 语法（客户端过滤）。
        """
        if not filter_value or not filter_value.strip():
            return ""
        q = filter_value.strip()
        # 同时匹配 code 和 name 列
        return f"{{code}} contains '{q}' || {{name}} contains '{q}'"

    # ------------------------------------------------------------------ #
    # FR-1.1：单行 × 删除 + FR-2.3：点击切换 K 线标的
    # ------------------------------------------------------------------ #
    @app.callback(
        Output("qb-watchlist-store", "data", allow_duplicate=True),
        Output("qb-table-container", "children", allow_duplicate=True),
        Output("qb-chart-symbol", "data", allow_duplicate=True),
        Input("qb-data-table", "active_cell"),
        State("qb-data-table", "data"),
        State("qb-watchlist-store", "data"),
        State("qb-adj-mode", "value"),
        prevent_initial_call=True,
    )
    def on_table_cell_click(active_cell, table_data, watchlist, adj_mode):
        """监听 DataTable 单元格点击。

        - column_id == "remove" → 单行删除该标的
        - 其他列 → 切换 K 线图表标的为该行标的
        """
        if not active_cell:
            return no_update, no_update, no_update
        row = active_cell.get("row")
        col = active_cell.get("column_id", "")
        if row is None or not table_data or row >= len(table_data):
            return no_update, no_update, no_update
        ticker = table_data[row].get("code", "")
        if not ticker:
            return no_update, no_update, no_update

        if col == "remove":
            wl = list(watchlist or [])
            if ticker not in wl:
                return no_update, no_update, no_update
            wl = [t for t in wl if t != ticker]
            _save_watchlist(wl)
            if not wl:
                return wl, html.Div("自选列表为空，请添加标的",
                                    className="text-muted text-center mt-4"), None
            return wl, _build_quote_table(_fetch_quote_data(wl, adj_mode)), (
                ticker if ticker in wl else wl[0])

        # 非删除列 → 切换 K 线标的
        return no_update, no_update, ticker

    # ------------------------------------------------------------------ #
    # FR-1.2/FR-4：批量删除——选中后显示按钮，点击删除选中
    # ------------------------------------------------------------------ #
    @app.callback(
        Output("qb-delete-bar", "children"),
        Input("qb-data-table", "selected_rows"),
        State("qb-data-table", "data"),
    )
    def render_delete_btn_visibility(selected_rows, table_data):
        if not selected_rows or not table_data:
            return ""
        count = len(selected_rows)
        return html.Div([
            html.Span(f"已选中 {count} 个标的", className="text-muted me-2 small"),
            dbc.Button(f"删除选中 ({count})", id="qb-delete-selected-btn",
                       color="danger", size="sm"),
        ], className="d-flex align-items-center")

    @app.callback(
        Output("qb-watchlist-store", "data", allow_duplicate=True),
        Output("qb-table-container", "children", allow_duplicate=True),
        Output("qb-chart-symbol", "data", allow_duplicate=True),
        Input("qb-delete-selected-btn", "n_clicks"),
        State("qb-data-table", "selected_rows"),
        State("qb-data-table", "data"),
        State("qb-watchlist-store", "data"),
        State("qb-adj-mode", "value"),
        prevent_initial_call=True,
    )
    def on_delete_selected(n_clicks, selected_rows, table_data, watchlist, adj_mode):
        if not n_clicks or not selected_rows or not table_data:
            return no_update, no_update, no_update
        tickers_to_remove = {table_data[r].get("code", "") for r in selected_rows}
        wl = [t for t in (watchlist or []) if t not in tickers_to_remove]
        _save_watchlist(wl)
        if not wl:
            return wl, html.Div("自选列表为空，请添加标的",
                                className="text-muted text-center mt-4"), None
        return wl, _build_quote_table(_fetch_quote_data(wl, adj_mode)), wl[0]

    # ------------------------------------------------------------------ #
    # FR-1.3：清空自选——弹窗确认
    # ------------------------------------------------------------------ #
    @app.callback(
        Output("qb-clear-modal", "is_open"),
        Output("qb-watchlist-store", "data", allow_duplicate=True),
        Output("qb-table-container", "children", allow_duplicate=True),
        Output("qb-chart-symbol", "data", allow_duplicate=True),
        Input("qb-clear-all-btn", "n_clicks"),
        Input("qb-clear-cancel", "n_clicks"),
        Input("qb-clear-confirm", "n_clicks"),
        State("qb-clear-modal", "is_open"),
        prevent_initial_call=True,
    )
    def on_clear_watchlist(open_clicks, cancel_clicks, confirm_clicks, is_open):
        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else ""
        if triggered_id == "qb-clear-confirm":
            _save_watchlist([])
            return False, [], html.Div("自选列表为空，请添加标的",
                                       className="text-muted text-center mt-4"), None
        if triggered_id == "qb-clear-all-btn":
            return True, no_update, no_update, no_update
        return False, no_update, no_update, no_update

    @app.callback(
        # FR-2.2 / Task #25：看板分钟 K 线——按所选「分钟周期」读取 qb-chart-symbol 的分钟线。
        # FR-2.3：使用 qb-chart-symbol 替代固定 wl[0]；移除 n_intervals（D6：分钟线盘中不变）。
        # period 切换 / 图表标的切换时重渲染。
        Output("qb-minute-chart", "figure"),
        Input("qb-minute-period", "value"),
        Input("qb-chart-symbol", "data"),
    )
    def render_minute_chart(period, chart_symbol):
        if not chart_symbol:
            return _build_minute_chart(None, period or "5", [])
        try:
            bars = get_data_service().get_minute_bars(chart_symbol, period or "5")
        except Exception as e:
            logger.warning("render_minute_chart failed %s: %s", chart_symbol, e)
            bars = []
        return _build_minute_chart(chart_symbol, period or "5", bars)

    # ------------------------------------------------------------------ #
    # FR-2.2：日 K 线渲染回调
    # ------------------------------------------------------------------ #
    @app.callback(
        Output("qb-daily-chart", "figure"),
        Input("qb-chart-symbol", "data"),
        Input("qb-adj-mode", "value"),
        Input("qb-daily-range", "value"),  # P1-1：时间范围选择
        Input("qb-daily-date-range", "start_date"),  # FR-3：自定义起止日期
        Input("qb-daily-date-range", "end_date"),
    )
    def render_daily_chart(chart_symbol, adj_mode, daily_range, custom_start, custom_end):
        if not chart_symbol:
            return _build_daily_chart(None, [], adj_mode)
        if daily_range == "custom" and custom_start and custom_end:
            # FR-3（行情看板体验优化）：自定义时间段——按 trade_date 区间过滤
            try:
                bars = _fetch_daily_bars(chart_symbol, adj_mode=adj_mode or "none",
                                         start=custom_start, end=custom_end)
            except Exception as e:
                logger.warning("render_daily_chart(custom) failed %s: %s", chart_symbol, e)
                bars = []
        else:
            limit = daily_range if isinstance(daily_range, int) else 120
            try:
                bars = _fetch_daily_bars(chart_symbol, limit=limit, adj_mode=adj_mode or "none")
            except Exception as e:
                logger.warning("render_daily_chart failed %s: %s", chart_symbol, e)
                bars = []
        return _build_daily_chart(chart_symbol, bars, adj_mode or "none")

    # ------------------------------------------------------------------ #
    # FR-3（行情看板体验优化）：「当日」快捷按钮
    # ------------------------------------------------------------------ #
    @app.callback(
        Output("qb-daily-date-range", "start_date"),
        Output("qb-daily-date-range", "end_date"),
        Output("qb-daily-range", "value"),
        Input("qb-daily-today-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def set_quote_daily_today(n_clicks):
        if not n_clicks:
            return no_update, no_update, no_update
        today = datetime.date.today().isoformat()
        return today, today, "custom"


def _build_daily_chart(symbol, bars, adj_mode="none"):
    """构建日 K 线图：Candlestick + 成交量柱（阳红阴绿）+ MA5/MA10/MA20。

    P0-1：make_subplots 双行（价格/成交量）
    P0-2：叠加均线 Scatter trace
    P2-1：hovermode x unified + rangeslider + 标题含口径
    """
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                         vertical_spacing=0.05, row_heights=[0.75, 0.25])

    if not symbol:
        fig.add_annotation(text="自选为空，添加标的后可查看日K线",
                           xref="paper", yref="paper", showarrow=False, font={"size": 13})
        fig.update_layout(height=300, margin={"l": 30, "r": 10, "t": 30, "b": 30})
        return fig
    if not bars:
        fig.add_annotation(text=f"{symbol} 暂无日线数据",
                           xref="paper", yref="paper", showarrow=False, font={"size": 13})
        fig.update_layout(height=300, margin={"l": 30, "r": 10, "t": 30, "b": 30})
        return fig

    dates = [str(b["trade_date"]) for b in bars]

    # P0-1：Candlestick（row 1）
    fig.add_trace(go.Candlestick(
        x=dates,
        open=[float(b["open"]) for b in bars],
        high=[float(b["high"]) for b in bars],
        low=[float(b["low"]) for b in bars],
        close=[float(b["close"]) for b in bars],
        name="日线",
    ), row=1, col=1)

    # P0-1：成交量柱（row 2），阳红阴绿（中国行情惯例）
    vol_colors = ["#dc3545" if float(b["close"]) >= float(b["open"]) else "#198754"
                  for b in bars]
    fig.add_trace(go.Bar(
        x=dates,
        y=[float(b.get("volume", 0)) for b in bars],
        marker_color=vol_colors,
        name="成交量",
        showlegend=False,
    ), row=2, col=1)

    # P0-2：均线（row 1）
    ma_configs = [
        ("MA5", "ma5", "#1e90ff"),
        ("MA10", "ma10", "#ff8c00"),
        ("MA20", "ma20", "#9370db"),
    ]
    for name, key, color in ma_configs:
        vals = [float(b.get(key)) if b.get(key) is not None else None for b in bars]
        if any(v is not None for v in vals):
            fig.add_trace(go.Scatter(
                x=dates, y=vals, mode="lines", name=name,
                line=dict(color=color, width=1.5),
                connectgaps=False,
            ), row=1, col=1)

    # P2-1：布局美化
    adj_label = {"none": "不复权", "qfq": "前复权", "hfq": "后复权"}.get(adj_mode, adj_mode)
    fig.update_layout(
        title=f"{symbol} 日K线  |  MA5 MA10 MA20  |  {adj_label}",
        height=400,
        margin={"l": 40, "r": 10, "t": 50, "b": 30},
        hovermode="x unified",
        legend=dict(orientation="h", y=1.02, x=0.5, xanchor="center"),
    )
    # 网格
    fig.update_xaxes(showgrid=True, gridcolor="#f0f0f0", row=1)
    fig.update_xaxes(showgrid=True, gridcolor="#f0f0f0", row=2)
    fig.update_yaxes(showgrid=True, gridcolor="#f0f0f0", row=1, title_text="价格")
    fig.update_yaxes(showgrid=True, gridcolor="#f0f0f0", row=2, title_text="成交量")
    # W3：跳过周末（subplot 模式须指定 row=1）
    fig.update_xaxes(rangeslider_visible=True, rangebreaks=[dict(bounds=["sat", "mon"])], row=1)
    return fig


def _fetch_daily_bars(ticker, limit=120, adj_mode="none", start=None, end=None):
    """从 bars_daily 表读取日线数据，支持复权口径换算（FR-2.2）。

    使用与 _quote_row 一致的 polars DataFrame API（df["col"][idx] 而非 df.iloc）。
    """
    db = _get_db()
    if start and end:
        # FR-3（行情看板体验优化）：自定义时间段——按 trade_date 区间过滤（升序直接可用）
        df = db.query_df(
            "SELECT trade_date, open, high, low, close, volume FROM bars_daily "
            "WHERE ticker=? AND trade_date >= ? AND trade_date <= ? "
            "ORDER BY trade_date ASC",
            [ticker, start, end])
        ascending = True
    else:
        df = db.query_df(
            "SELECT trade_date, open, high, low, close, volume FROM bars_daily "
            "WHERE ticker=? ORDER BY trade_date DESC LIMIT ?",
            [ticker, limit])
        ascending = False
    n = len(df)
    if n == 0:
        return []
    # 自定义区间为升序，固定档为 DESC 需反转（plotly candlestick 要求升序）
    bars = []
    idx_range = range(n) if ascending else range(n - 1, -1, -1)
    for i in idx_range:
        bar = {
            "trade_date": str(df["trade_date"][i])[:10],
            "open": float(df["open"][i]),
            "high": float(df["high"][i]),
            "low": float(df["low"][i]),
            "close": float(df["close"][i]),
            "volume": float(df["volume"][i]) if df["volume"][i] else 0,
        }
        if adj_mode in ("qfq", "hfq"):
            f = _adj_factor(db, ticker, bar["trade_date"], adj_mode)
            if f:
                if adj_mode == "hfq":
                    ratio = f
                else:
                    # 前复权：以最新日因子归一
                    latest = _adj_factor(db, ticker, bars[0]["trade_date"] if bars else bar["trade_date"], adj_mode)
                    latest_f = latest if not bars else (bars[0].get("_adj_factor") or latest)
                    ratio = f / (latest_f or 1.0)
                    if not bars:
                        if latest is None:
                            ratio = 1.0
                        else:
                            bar["_adj_factor"] = f
                bar["open"] = round(bar["open"] * ratio, 2)
                bar["high"] = round(bar["high"] * ratio, 2)
                bar["low"] = round(bar["low"] * ratio, 2)
                bar["close"] = round(bar["close"] * ratio, 2)
        bars.append(bar)
    # 移除内部标记
    for b in bars:
        b.pop("_adj_factor", None)
    # P0-2：预计算均线（已按 adj_mode 换算过 close）
    closes = [b["close"] for b in bars]
    for i, b in enumerate(bars):
        b["ma5"] = round(sum(closes[max(0, i-4):i+1]) / min(i+1, 5), 2) if i >= 4 else None
        b["ma10"] = round(sum(closes[max(0, i-9):i+1]) / min(i+1, 10), 2) if i >= 9 else None
        b["ma20"] = round(sum(closes[max(0, i-19):i+1]) / min(i+1, 20), 2) if i >= 19 else None
    return bars


def _build_minute_chart(symbol, period, bars):
    """FR-2.2 / Task #25：构建分钟 K 线图（plotly candlestick）。

    symbol 为空或该周期无分钟线时返回带提示文案的空图，避免空白组件。
    """
    import plotly.graph_objects as go

    fig = go.Figure()
    if not symbol:
        fig.add_annotation(text="自选为空，添加标的后可查看分钟K线",
                           xref="paper", yref="paper", showarrow=False, font={"size": 13})
        fig.update_layout(height=300, margin={"l": 30, "r": 10, "t": 30, "b": 30})
        return fig
    if not bars:
        fig.add_annotation(
            text=f"{symbol} 暂无 {period}m 分钟线（请先获取该标的分钟数据）",
            xref="paper", yref="paper", showarrow=False, font={"size": 13})
        fig.update_layout(height=300, margin={"l": 30, "r": 10, "t": 30, "b": 30})
        return fig
    fig.add_trace(go.Candlestick(
        x=[str(b["bar_time"]) for b in bars],
        open=[float(b["open"]) for b in bars],
        high=[float(b["high"]) for b in bars],
        low=[float(b["low"]) for b in bars],
        close=[float(b["close"]) for b in bars],
        name=f"{period}m",
    ))
    fig.update_layout(
        title=f"{symbol} {period}m 分钟K线",
        height=320,
        margin={"l": 40, "r": 10, "t": 40, "b": 30},
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
    )
    # FR-1（行情看板体验优化）：隐藏 A 股/港股每日午休（11:30–13:00）空白带，
    # 交易时段连续展示，避免大段断裂影响观感。
    fig.update_xaxes(rangebreaks=[dict(bounds=["11:30", "13:00"])])
    return fig



def _strip_focus(search: str) -> str:
    """从 URL search 中移除 focus 参数（保留其它），U-2。"""
    q = parse_qs(search.lstrip("?"))
    q.pop("focus", None)
    if not q:
        return ""
    return "?" + urlencode(q, doseq=True)
