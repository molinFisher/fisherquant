"""数据查询 Tab 回调（数据中心数据查询功能重设计 PRD v1.1）。

核心设计：
- FR-2/3：单一搜索入口，支持名称/代码/拼音搜索与多代码粘贴（逗号/空格/换行分隔），
  多代码拆分在回调内完成（服务层 search_symbols 接口不变），未收录代码标灰。
- FR-4：selected-symbols-store 为已选池的单一事实来源；候选勾选与池 chips 双向同步。
- FR-5：取数按钮守卫——空池物理禁用并常驻原因提示；「数据类型=财务数据」时
  港股不可取（全港股池禁用，混合池提示"港股将被跳过"，产品决策 2026-07-28）。
- D2：取数结果只写 fetch-results，不覆盖已选池。
"""
import json
import logging
import re

import dash
from dash import Input, Output, State, ALL, no_update, html
import dash_bootstrap_components as dbc

logger = logging.getLogger(__name__)

# 多代码拆分：逗号/中文逗号/分号/空白（含换行）任意组合
_SPLIT_RE = re.compile(r"[,\uFF0C;\uFF1B\s]+")

# 单次取数上限（沿用旧批量输入上限）
MAX_FETCH_SYMBOLS = 20


def _is_hk(item: dict) -> bool:
    """判断池内条目是否港股（market 字段优先，回退 ticker 后缀）。"""
    if item.get("market"):
        return item["market"] == "hk_connect"
    return str(item.get("value", "")).upper().endswith(".HK")


def _market_tag(item: dict) -> str:
    return "港股" if _is_hk(item) else "A股"


def _candidate_options(matches: list[dict], misses: list[str]) -> list[dict]:
    """构建待选框 options：命中项富标签；未收录 token 标灰禁用。"""
    options = []
    for m in matches:
        label_parts = [m.get("name", ""), m.get("code", "")]
        abbr = (m.get("pinyin_abbr") or "").strip()
        tag = _market_tag(m)
        label = f"{label_parts[0]}  {label_parts[1]} · {tag}"
        if abbr:
            label += f" · {abbr}"
        options.append({"label": label, "value": m["value"]})
    for token in misses:
        options.append({
            "label": f"{token} · 未收录",
            "value": f"__miss__{token}",
            "disabled": True,
        })
    return options


def _dedupe_by_value(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for it in items:
        if it["value"] not in seen:
            seen.add(it["value"])
            out.append(it)
    return out


def register_data_callbacks(app):
    from fisher.dash_app.services import get_data_service

    @app.callback(
        Output("candidate-list", "options"),
        Output("search-status", "children"),
        Output("search-results-store", "data"),
        Input("symbol-search-input", "value"),
        prevent_initial_call=True,
    )
    def search_symbols(query):
        # 三态一：输入不足
        if not query or len(query.strip()) < 2:
            return [], html.Span("请输入至少 2 个字符", className="text-muted"), []

        q = query.strip()
        tokens = [t for t in _SPLIT_RE.split(q) if t]

        try:
            svc = get_data_service()
            if len(tokens) > 1:
                # FR-3：多代码粘贴——逐 token 搜索，优先精确代码命中，合并去重
                matches, misses = [], []
                for token in tokens:
                    res = svc.search_symbols(token)
                    exact = [r for r in res
                             if r.get("code") == token
                             or str(r.get("value", "")).upper() == token.upper()]
                    picked = exact or res[:1]
                    if picked:
                        matches.extend(picked)
                    else:
                        misses.append(token)
                matches = _dedupe_by_value(matches)
            else:
                matches = svc.search_symbols(q)
                misses = []
        except Exception:
            # R-31：不向用户暴露技术堆栈（技术细节已在服务层落日志）
            logger.exception("search_symbols callback failed")
            return [], html.Span("搜索服务暂时不可用，请稍后重试",
                                 className="text-danger"), []

        # 三态二：无结果
        if not matches and not misses:
            try:
                if not svc.symbol_dict_ready():
                    return [], html.Span("标的列表初始化中，请稍候…",
                                         className="text-info"), []
            except Exception:
                logger.debug("symbol_dict_ready 检查失败，回退无结果提示")
            return [], html.Span("未找到匹配的标的，试试代码、名称或拼音",
                                 className="text-warning"), []

        # 三态三：有结果——统计条（总数 + 市场分布 + 未收录数）
        a_n = sum(1 for m in matches if m.get("market") == "a_share")
        hk_n = len(matches) - a_n
        status_children = [
            html.Span(f"找到 {len(matches)} 个结果", className="text-success me-2"),
            html.Small(f"A股 {a_n} · 港股 {hk_n}", className="text-muted"),
        ]
        if misses:
            status_children.append(
                html.Small(f" · 未收录 {len(misses)} 个", className="text-warning ms-1"))
        return (_candidate_options(matches, misses),
                html.Span(status_children), matches)

    @app.callback(
        Output("selected-symbols-store", "data"),
        Output("candidate-list", "value"),
        Input("candidate-list", "value"),
        Input("candidate-select-all-btn", "n_clicks"),
        Input("candidate-invert-btn", "n_clicks"),
        Input("clear-selected-btn", "n_clicks"),
        Input({"type": "pool-remove", "index": ALL}, "n_clicks"),
        State("search-results-store", "data"),
        State("selected-symbols-store", "data"),
        prevent_initial_call=True,
    )
    def sync_selected_pool(checked, sel_all, invert, clear, remove_clicks,
                           results, pool):
        """已选池单一事实来源同步（FR-4）。

        - 勾选/取消勾选：池 = (池 - 当前结果集) + 当前勾选项（池内非当前结果集条目保留）
        - 全选/反选：只作用于当前搜索结果集（产品决策 2026-07-28）
        - × 移除 / 清空已选：只操作池，并同步取消候选勾选
        """
        results = results or []
        pool = list(pool or [])
        checked = list(checked or [])
        current_values = [r["value"] for r in results]
        by_value = {r["value"]: r for r in results}

        triggered = dash.ctx.triggered
        if not triggered:
            return no_update, no_update
        prop_id = triggered[0]["prop_id"]
        tid = prop_id.rsplit(".", 1)[0]

        def _merge(new_checked):
            kept = [p for p in pool if p["value"] not in current_values]
            added = [by_value[v] for v in current_values if v in new_checked]
            return _dedupe_by_value(kept + added)

        # × 移除某个池内条目（pattern-matching id）
        if tid.startswith("{"):
            if not triggered[0].get("value"):
                return no_update, no_update  # chips 重渲染触发的空点击
            ticker = json.loads(tid)["index"]
            new_pool = [p for p in pool if p["value"] != ticker]
            new_checked = [v for v in checked if v != ticker]
            return new_pool, new_checked

        if tid == "clear-selected-btn":
            return [], []

        if tid == "candidate-select-all-btn":
            new_checked = list(current_values)
            return _merge(new_checked), new_checked

        if tid == "candidate-invert-btn":
            new_checked = [v for v in current_values if v not in checked]
            return _merge(new_checked), new_checked

        # candidate-list 勾选变化
        return _merge(checked), no_update

    @app.callback(
        Output("selected-pool", "children"),
        Input("selected-symbols-store", "data"),
        Input("data-type-radio", "value"),
    )
    def render_selected_pool(pool, data_type):
        """池 chips 渲染：名称+代码+市场徽标+× 移除；财务模式下港股 chip 警示。"""
        pool = pool or []
        if not pool:
            return "尚未选择标的（从左侧搜索结果勾选）"
        chips = []
        for item in pool:
            hk = _is_hk(item)
            warn = data_type in ("financials", "adj") and hk
            chips.append(
                dbc.Badge(
                    [
                        html.Span(f"{item.get('name', '')} {item.get('code', '')}"
                                  if item.get("name") else item["value"],
                                  className="me-1"),
                        html.Small(f"[{_market_tag(item)}]", className="me-1"),
                        dbc.Button(
                            "×",
                            id={"type": "pool-remove", "index": item["value"]},
                            color="link", size="sm",
                            className="p-0 text-white align-baseline",
                            style={"lineHeight": "1", "textDecoration": "none"},
                        ),
                    ],
                    color="warning" if warn else ("info" if hk else "danger"),
                    className="me-2 mb-2",
                    title="复权因子/财务数据仅支持 A 股，取数时将被跳过" if warn else "",
                )
            )
        footer = html.Div(f"共 {len(pool)} 个标的", className="text-muted small mt-1")
        return html.Div([html.Div(chips), footer])

    @app.callback(
        Output("fetch-data-button", "disabled", allow_duplicate=True),
        Output("fetch-guard-hint", "children"),
        Input("selected-symbols-store", "data"),
        Input("data-type-radio", "value"),
        prevent_initial_call="initial_duplicate",
    )
    def guard_fetch_button(pool, data_type):
        """FR-5 取数按钮守卫：空池禁用；财务模式全港股禁用、混合提示跳过。"""
        pool = pool or []
        if not pool:
            return True, "已选池为空——请先从搜索结果勾选标的"
        if data_type in ("financials", "adj"):
            hk_items = [p for p in pool if _is_hk(p)]
            label = "财务数据" if data_type == "financials" else "复权因子"
            if len(hk_items) == len(pool):
                return True, f"{label}仅支持 A 股，请至少选择一个 A 股标的"
            if hk_items:
                return False, f"注意：{label}仅支持 A 股，池中 {len(hk_items)} 个港股将被跳过"
        return False, ""

    @app.callback(
        Output("fetch-status", "children"),
        Output("fetch-results", "children"),
        Input("fetch-data-button", "n_clicks"),
        State("selected-symbols-store", "data"),
        State("date-range-picker", "start_date"),
        State("date-range-picker", "end_date"),
        State("data-type-radio", "value"),
        State("minute-period-selector", "value"),
        prevent_initial_call=True,
        running=[
            (Output("fetch-data-button", "disabled"), True, False),
            (Output("fetch-data-button", "children"), "获取中...", "开始获取数据"),
        ],
    )
    def fetch_data(n_clicks, pool, start_date, end_date, data_type, minute_period):
        """同步取数回调。

        注意：不可用 background=True + yield 生成器——Dash 后台回调不支持
        生成器（diskcache pickle 失败：cannot pickle 'generator' object），
        且后台回调在独立进程运行会与主进程的 DuckDB 独占锁冲突。
        单次上限 MAX_FETCH_SYMBOLS(20) 个标的，同步执行可接受。
        取数期间按钮显示「获取中...」，结果一次写入 fetch-results（无进度条）。
        """
        pool = pool or []
        items = _dedupe_by_value([p for p in pool if p.get("value")])[:MAX_FETCH_SYMBOLS]

        if not items:
            return "请先从搜索结果勾选标的", "取数结果将显示在这里"

        svc = get_data_service()
        total = len(items)
        results, errors, skipped = [], [], []

        for item in items:
            symbol = item["value"]
            # 产品决策（2026-07-28）：财务/复权数据仅支持 A 股，港股跳过并明示
            if data_type in ("financials", "adj") and _is_hk(item):
                label = "财务数据" if data_type == "financials" else "复权因子"
                skipped.append(f"⊘ {symbol}: {label}仅支持 A 股，已跳过")
                continue
            period = minute_period.replace("min", "") if minute_period else ""
            try:
                result = svc.fetch_bars([symbol], start_date, end_date, data_type, period)
                sym_result = result.get(symbol, {})
                if sym_result.get("status") == "ok":
                    count = sym_result.get("count", 0)
                    if count:
                        results.append(f"✓ {symbol}: {count}条记录")
                    else:
                        results.append(f"✓ {symbol}: 财务数据已获取")
                else:
                    errors.append(f"✗ {symbol}: {sym_result.get('error', '无数据')}")
            except Exception as e:
                errors.append(f"✗ {symbol}: {str(e)[:80]}")

        summary = f"完成：成功 {len(results)}，失败 {len(errors)}"
        if skipped:
            summary += f"，跳过 {len(skipped)}"
        detail_lines = results + errors + skipped
        detail_el = html.Div([html.P(line, className="mb-1")
                              for line in detail_lines[:40]])
        # D2：结果只写 fetch-results，已选池不受影响
        return summary, detail_el

    @app.callback(
        Output("minute-period-container", "style"),
        Input("data-type-radio", "value"),
    )
    def toggle_minute_period(data_type):
        if data_type == "minute":
            return {"display": "block"}
        return {"display": "none"}
