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
    db = DuckDBManager()
    if not db._initialized:
        try:
            db.connect("./data/fisherquant.db", read_pool_size=4)
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


def _quote_row(sym, snap, cov, adj_mode="none"):
    """构建单行行情数据：快照优先，无快照降级日线（FR-6.1/6.2）。

    adj_mode ∈ {none, qfq, hfq}：仅日线降级路径按复权口径换算最新价与涨跌幅
    （FR-2.4 / Task #22 口径一致性）；实时快照为实际成交价，不受复权影响。
    """
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
        "name": sym.split(".")[0],
        "last_price": f"{last:.2f}" if last is not None else "-",
        "change_pct": f"{pct:+.2f}%" if pct is not None else "-",
        "volume": _fmt_volume(vol) if vol is not None else "-",
        "volume_raw": vol,
        "change_raw": change_raw,
        "coverage": _coverage_badges(cov),
        "realtime_status": realtime_status,
        "daily_fallback": daily_fallback,
        "goto_cache": f"[去缓存](/data-center?tab=tab-cached&focus={sym})",
    }


def _empty_row(sym, cov):
    return {
        "code": sym, "name": sym.split(".")[0], "last_price": "-",
        "change_pct": "-", "volume": "-", "volume_raw": None,
        "change_raw": 0.0, "coverage": _coverage_badges(cov),
        "realtime_status": '<span style="color:#c8ccd0" title="无数据">—</span>',
        "daily_fallback": True,
        "goto_cache": f"[去缓存](/data-center?tab=tab-cached&focus={sym})",
    }


def _fetch_quote_data(symbols, adj_mode="none"):
    """FR-6 行情源切换 + FR-4.1 覆盖度徽标：快照优先，缺则降级日线。
    adj_mode 透传复权口径（FR-2.4 / Task #22）。"""
    cov = _safe_coverage(symbols)
    snap = _safe_snapshots(symbols)
    data = []
    for sym in symbols:
        try:
            data.append(_quote_row(sym, snap.get(sym), cov.get(sym), adj_mode))
        except Exception:
            data.append(_empty_row(sym, cov.get(sym)))
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
    ]
    style_data_conditional = [
        {"if": {"filter_query": "{change_raw} > 0", "column_id": "change_pct"},
         "color": "#dc3545"},
        {"if": {"filter_query": "{change_raw} < 0", "column_id": "change_pct"},
         "color": "#198754"},
        {"if": {"row_index": "odd"}, "backgroundColor": "#fafbfc"},
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
        tooltip_data=[
            {"volume": {"value": f"原始值：{r.get('volume_raw', '-')}", "type": "markdown"}}
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
        # IC-3：仅已缓存标的可加（防死标）
        return _get_cached_symbols()

    @app.callback(
        Output("qb-watchlist-store", "data", allow_duplicate=True),
        Output("qb-table-container", "children", allow_duplicate=True),
        Input("qb-add-btn", "n_clicks"),
        Input("qb-manual-refresh", "n_clicks"),
        Input("qb-refresh-interval", "n_intervals"),
        State("qb-add-symbol-dropdown", "value"),
        State("qb-watchlist-store", "data"),
        prevent_initial_call=True,
    )
    def update_watchlist(add_clicks, refresh_clicks, auto_interval, new_symbol, watchlist):
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
            # FR-5.2：仅允许已缓存标的入自选（死标不入）
            if not _is_dead_symbol(new_symbol) and new_symbol not in watchlist:
                watchlist.append(new_symbol)
                _save_watchlist(watchlist)

        if not watchlist:
            return watchlist, html.Div("自选列表为空，请添加标的", className="text-muted text-center mt-4")

        table_data = _fetch_quote_data(watchlist)
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
    )
    def check_trading_hours(pathname):
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
        Input("qb-refresh-interval", "n_intervals"),
    )
    def render_health(watchlist, n_intervals):
        """FR-4.3：看板变健康度仪表盘——实时/分钟覆盖率汇总 + 批量去缓存入口。"""
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
        """
        if not search or pathname != "/quote-board":
            return no_update, no_update, no_update
        q = parse_qs(search.lstrip("?"))
        focus = (q.get("focus") or [None])[0]
        if not focus:
            return no_update, no_update, no_update

        wl = list(watchlist or [])
        if focus not in wl:
            if _catalog().has_any_data(focus):
                wl.append(focus)
            else:
                # 死标：不入自选，仅清除参数（FR-5.3 结构性归零思路）
                return no_update, no_update, _strip_focus(search)

        # 联动 A（FR-3.1 / FR-7.5）：纳入自动加载宇宙（idempotent）
        try:
            _catalog().set_auto_load_enabled(focus, True)
        except Exception:
            pass

        if focus in wl:
            wl.remove(focus)
            wl.insert(0, focus)  # 置顶高亮
        data = _fetch_quote_data(wl)
        return wl, _build_quote_table(data, highlight=focus), _strip_focus(search)

    @app.callback(
        Output("url", "pathname", allow_duplicate=True),
        Output("url", "search", allow_duplicate=True),
        Input("qb-batch-cache-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def batch_goto_cache(n_clicks):
        """FR-4.3：一键批量去缓存——跳转目录页补齐缺失类型。"""
        if not n_clicks:
            return no_update, no_update
        return "/data-center", "?tab=tab-cached"

    @app.callback(
        # FR-5.3 / T-4：导航到行情看板即清理死标并即时渲染（首次加载也生效，无空白死行）
        # allow_duplicate + 首触发必须用 'initial_duplicate'（Dash 校验要求），
        # 否则与 update_watchlist / consume_focus_board 共享输出报 DuplicateCallback。
        Output("qb-watchlist-store", "data", allow_duplicate=True),
        Output("qb-table-container", "children", allow_duplicate=True),
        Input("url", "pathname"),
        prevent_initial_call="initial_duplicate",
    )
    def prune_watchlist_on_load(pathname):
        if pathname != "/quote-board":
            return no_update, no_update
        wl = _load_watchlist() or []
        kept, removed = _prune_watchlist(wl)
        if removed:
            logger.info("watchlist_pruned removed=%s", removed)
            _save_watchlist(kept)
        if not kept:
            return kept, html.Div("自选列表为空，请添加标的", className="text-muted text-center mt-4")
        return kept, _build_quote_table(_fetch_quote_data(kept))


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

    @app.callback(
        # FR-2.2 / Task #25：看板分钟 K 线——按所选「分钟周期」读取首个自选标的的分钟线。
        # period 切换 / 自选变化（watchlist-store）/ 自动刷新（interval）时重渲染；
        # 输出唯一组件 qb-minute-chart，与其他回调无 Output 冲突。
        Output("qb-minute-chart", "figure"),
        Input("qb-minute-period", "value"),
        Input("qb-watchlist-store", "data"),
        Input("qb-refresh-interval", "n_intervals"),
    )
    def render_minute_chart(period, watchlist, n_intervals):
        wl = list(watchlist or []) or _load_watchlist() or []
        symbol = wl[0] if wl else None
        if not symbol:
            return _build_minute_chart(None, period or "5", [])
        try:
            bars = get_data_service().get_minute_bars(symbol, period or "5")
        except Exception as e:
            logger.warning("render_minute_chart failed %s: %s", symbol, e)
            bars = []
        return _build_minute_chart(symbol, period or "5", bars)


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
    )
    return fig



def _strip_focus(search: str) -> str:
    """从 URL search 中移除 focus 参数（保留其它），U-2。"""
    q = parse_qs(search.lstrip("?"))
    q.pop("focus", None)
    if not q:
        return ""
    return "?" + urlencode(q, doseq=True)
