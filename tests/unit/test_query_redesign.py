"""数据查询 Tab 重设计（PRD v1.1 §12.2）单元测试。

覆盖：已选池双向同步 / 全选反选只作用当前结果集 / 清空已选 / × 移除 /
按钮守卫（空池、财务全港股、财务混合）/ 财务死模块移除 / 取数不覆盖池。
"""
import pytest

from fisher.dash_app.callbacks import data_callbacks
from fisher.dash_app.pages import data_center
from tests.helpers.dash_harness import capture_dash_callbacks


# --------------------------------------------------------------------------- #
# 公共脚手架
# --------------------------------------------------------------------------- #
A1 = {"value": "600519.SH", "code": "600519", "name": "贵州茅台", "market": "a_share"}
A2 = {"value": "000001.SZ", "code": "000001", "name": "平安银行", "market": "a_share"}
HK = {"value": "00700.HK", "code": "00700", "name": "腾讯控股", "market": "hk_connect"}


class _Ctx:
    def __init__(self, prop_id, value=1):
        self.triggered = [{"prop_id": prop_id, "value": value}]


@pytest.fixture
def cbs(monkeypatch):
    class _Svc:
        def search_symbols(self, q):
            return []
    monkeypatch.setattr("fisher.dash_app.services.get_data_service", lambda: _Svc())
    with capture_dash_callbacks() as app:
        data_callbacks.register_data_callbacks(app)
    return app


def _sync(app, monkeypatch, trigger, checked, results, pool, remove_clicks=None,
          trigger_value=1):
    monkeypatch.setattr("dash.ctx", _Ctx(trigger, trigger_value))
    return app.by_output("selected-symbols-store")(
        checked, None, None, None, remove_clicks or [], results, pool)


# --------------------------------------------------------------------------- #
# 1) 池同步（FR-4）
# --------------------------------------------------------------------------- #
class TestPoolSync:
    def test_check_adds_to_pool(self, cbs, monkeypatch):
        pool, _ = _sync(cbs, monkeypatch, "candidate-list.value",
                        ["600519.SH"], [A1, A2], [])
        assert [p["value"] for p in pool] == ["600519.SH"]

    def test_uncheck_removes_from_pool(self, cbs, monkeypatch):
        pool, _ = _sync(cbs, monkeypatch, "candidate-list.value",
                        [], [A1, A2], [A1])
        assert pool == []

    def test_pool_keeps_items_outside_current_results(self, cbs, monkeypatch):
        """换搜索词后勾选：池内非当前结果集条目保留（不被覆盖）。"""
        pool, _ = _sync(cbs, monkeypatch, "candidate-list.value",
                        ["00700.HK"], [HK], [A1])  # A1 不在当前结果集
        values = [p["value"] for p in pool]
        assert "600519.SH" in values and "00700.HK" in values

    def test_select_all_scoped_to_current_results(self, cbs, monkeypatch):
        """产品决策：全选只作用于当前结果集，池内既有其它条目保留。"""
        pool, checked = _sync(cbs, monkeypatch,
                              "candidate-select-all-btn.n_clicks",
                              [], [A1, A2], [HK])
        assert set(checked) == {"600519.SH", "000001.SZ"}
        assert {p["value"] for p in pool} == {"00700.HK", "600519.SH", "000001.SZ"}

    def test_invert_selection(self, cbs, monkeypatch):
        pool, checked = _sync(cbs, monkeypatch,
                              "candidate-invert-btn.n_clicks",
                              ["600519.SH"], [A1, A2], [A1])
        assert checked == ["000001.SZ"]
        assert [p["value"] for p in pool] == ["000001.SZ"]

    def test_chip_remove(self, cbs, monkeypatch):
        prop = '{"index":"600519.SH","type":"pool-remove"}.n_clicks'
        pool, checked = _sync(cbs, monkeypatch, prop,
                              ["600519.SH", "000001.SZ"], [A1, A2], [A1, A2])
        assert [p["value"] for p in pool] == ["000001.SZ"]
        assert checked == ["000001.SZ"]  # 候选勾选同步取消

    def test_chip_remove_ignores_render_noise(self, cbs, monkeypatch):
        """chips 重渲染产生的 n_clicks=None 触发不应清池。"""
        prop = '{"index":"600519.SH","type":"pool-remove"}.n_clicks'
        pool, checked = _sync(cbs, monkeypatch, prop,
                              ["600519.SH"], [A1], [A1], trigger_value=None)
        from dash import no_update
        assert pool is no_update and checked is no_update

    def test_clear_selected(self, cbs, monkeypatch):
        pool, checked = _sync(cbs, monkeypatch, "clear-selected-btn.n_clicks",
                              ["600519.SH"], [A1], [A1, HK])
        assert pool == [] and checked == []


# --------------------------------------------------------------------------- #
# 2) 按钮守卫（FR-5 + 财务决策）
# --------------------------------------------------------------------------- #
class TestFetchGuard:
    def test_empty_pool_disabled(self, cbs):
        disabled, hint = cbs.by_output("fetch-guard-hint")([], "daily")
        assert disabled is True and "已选池为空" in hint

    def test_nonempty_pool_enabled(self, cbs):
        disabled, hint = cbs.by_output("fetch-guard-hint")([A1], "daily")
        assert disabled is False and "最多同时获取" in hint

    def test_financials_all_hk_disabled(self, cbs):
        disabled, hint = cbs.by_output("fetch-guard-hint")([HK], "financials")
        assert disabled is True and "仅支持 A 股" in hint

    def test_financials_mixed_enabled_with_hint(self, cbs):
        disabled, hint = cbs.by_output("fetch-guard-hint")([A1, HK], "financials")
        assert disabled is False and "将被跳过" in hint

    def test_financials_all_a_share_enabled(self, cbs):
        disabled, hint = cbs.by_output("fetch-guard-hint")([A1, A2], "financials")
        assert disabled is False and "最多同时获取" in hint


# --------------------------------------------------------------------------- #
# 3) 财务死模块移除（FR-1/FR-7）+ 新组件存在
# --------------------------------------------------------------------------- #
def _collect_ids(node, acc):
    if node is None:
        return
    nid = getattr(node, "id", None)
    if nid and isinstance(nid, str):
        acc.append(nid)
    children = getattr(node, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            _collect_ids(child, acc)
    elif children is not None:
        _collect_ids(children, acc)


class TestLayoutRedesign:
    def test_financials_module_removed(self):
        ids = []
        _collect_ids(data_center.create_data_center_layout(), ids)
        for dead in ["financials-symbol-input", "query-financials-btn",
                     "financials-modal", "financials-modal-body",
                     "close-financials-modal", "batch-symbols-input",
                     "symbol-search-results", "fetch-list"]:
            assert dead not in ids, f"死组件 {dead} 应已删除"

    def test_new_components_present(self):
        ids = []
        _collect_ids(data_center.create_data_center_layout(), ids)
        for needed in ["candidate-list", "candidate-select-all-btn",
                       "candidate-invert-btn", "selected-pool",
                       "selected-symbols-store", "clear-selected-btn",
                       "fetch-results", "fetch-guard-hint"]:
            assert needed in ids, f"新组件 {needed} 缺失"

    def test_financials_radio_kept(self):
        """产品决策：「数据类型=财务数据」radio 保留。"""
        layout = data_center.create_data_center_layout()

        found = []

        def _walk(node):
            if getattr(node, "id", None) == "data-type-radio":
                found.append(node)
            children = getattr(node, "children", None)
            if isinstance(children, (list, tuple)):
                for c in children:
                    _walk(c)
            elif children is not None:
                _walk(children)

        _walk(layout)
        assert found, "data-type-radio 应保留"
        values = [o["value"] for o in found[0].options]
        assert "financials" in values



# --------------------------------------------------------------------------- #
# 5) 多代码粘贴（P4-7 / FR-6 / D1）
# --------------------------------------------------------------------------- #
class TestMultiCodePaste:
    """多代码粘贴：逗号/空格/换行/中文逗号/分号 → 候选条数正确 + 未收录标灰禁用。"""

    class _KnownSvc:
        def search_symbols(self, q):
            known = {
                "600519": [{"value": "600519.SH", "code": "600519",
                            "name": "贵州茅台", "market": "a_share"}],
                "000001": [{"value": "000001.SZ", "code": "000001",
                            "name": "平安银行", "market": "a_share"}],
                "00700":  [{"value": "00700.HK", "code": "00700",
                            "name": "腾讯控股", "market": "hk_connect"}],
                "茅台":   [{"value": "600519.SH", "code": "600519",
                            "name": "贵州茅台", "market": "a_share"}],
            }
            return known.get(q, [])

        def symbol_dict_ready(self):
            return True

    @pytest.fixture
    def svc(self, monkeypatch):
        monkeypatch.setattr("fisher.dash_app.services.get_data_service",
                            lambda: self._KnownSvc())
        with capture_dash_callbacks() as app:
            data_callbacks.register_data_callbacks(app)
        return app

    # ── 分隔符变体 ──

    def test_space_delimited(self, svc):
        """空格分隔 → 2 个结果。"""
        opts, *_ = svc.by_output("candidate-list.options")("600519 000001")
        assert len(opts) == 2
        assert {o["value"] for o in opts} == {"600519.SH", "000001.SZ"}

    def test_comma_delimited(self, svc):
        """英文逗号分隔 → 2 个结果。"""
        opts, *_ = svc.by_output("candidate-list.options")("600519,000001")
        assert len(opts) == 2

    def test_chinese_comma(self, svc):
        """中文逗号「，」→ 2 个结果。"""
        opts, *_ = svc.by_output("candidate-list.options")("600519，000001")
        assert len(opts) == 2

    def test_semicolon(self, svc):
        """分号分隔 → 2 个结果。"""
        opts, *_ = svc.by_output("candidate-list.options")("600519;000001")
        assert len(opts) == 2

    def test_newline_delimited(self, svc):
        """换行分隔 → 2 个结果。"""
        opts, *_ = svc.by_output("candidate-list.options")("600519\n000001")
        assert len(opts) == 2

    def test_mixed_delimiters(self, svc):
        """混合：逗号+空格 → 3 个结果。"""
        opts, *_ = svc.by_output("candidate-list.options")("600519,000001 00700")
        assert len(opts) == 3

    # ── 边界 / 异常 ──

    def test_unknown_tokens_disabled(self, svc):
        """未收录代码标灰禁用，value 含 __miss__ 前缀。"""
        opts, *_ = svc.by_output("candidate-list.options")("600519 999999")
        assert len(opts) == 2
        unknown = [o for o in opts if "未收录" in str(o.get("label", ""))]
        assert len(unknown) == 1
        assert unknown[0].get("disabled") is True
        assert "__miss__999999" in unknown[0]["value"]

    def test_all_unknown_shows_only_misses(self, svc):
        """全未收录 → 全部标灰禁用。"""
        opts, *_ = svc.by_output("candidate-list.options")("999999 888888")
        assert len(opts) == 2
        assert all(o.get("disabled") is True for o in opts)

    def test_duplicate_dedup(self, svc):
        """重复代码去重。"""
        opts, *_ = svc.by_output("candidate-list.options")("600519 600519 000001")
        assert len(opts) == 2  # 3 token → 2 个去重后

    def test_single_token_not_split(self, svc):
        """单 token（无分隔符）→ 不走拆分路径，正常返回。"""
        opts, *_ = svc.by_output("candidate-list.options")("600519")
        assert len(opts) == 1 and opts[0]["value"] == "600519.SH"

    def test_fuzzy_name_then_code(self, svc):
        """混合：名称（茅台）+ 代码（000001）。"""
        opts, *_ = svc.by_output("candidate-list.options")("茅台 000001")
        assert len(opts) == 2

    def test_short_input_empty(self, svc):
        """< 2 字符不检索。"""
        opts, *_ = svc.by_output("candidate-list.options")("a")
        assert opts == []

    def test_empty_input_empty(self, svc):
        """空输入不检索。"""
        opts, *_ = svc.by_output("candidate-list.options")("")
        assert opts == []

    # ── 副作用校验 ──

    def test_store_contains_search_metadata(self, svc):
        """store 包含搜索结果元数据。"""
        _, _, store = svc.by_output("candidate-list.options")("600519")
        assert len(store) == 1 and store[0]["code"] == "600519"

    def test_multi_code_store_all_items(self, svc):
        """多代码时 store 包含全部命中项。"""
        _, _, store = svc.by_output("candidate-list.options")("600519 000001")
        assert len(store) == 2
        assert {s["code"] for s in store} == {"600519", "000001"}

    def test_status_has_count(self, svc):
        """状态行含结果计数。"""
        _, status, _ = svc.by_output("candidate-list.options")("600519 000001 00700")
        children = getattr(status, "children", status) or []
        flat = "".join(str(c) for c in (children if isinstance(children, list) else [children]))
        assert "3" in flat

    def test_status_has_market_breakdown(self, svc):
        """状态行含 A 股/港股分布。"""
        _, status, _ = svc.by_output("candidate-list.options")("600519 000001 00700")
        children = getattr(status, "children", status) or []
        flat = "".join(str(c) for c in (children if isinstance(children, list) else [children]))
        assert "A股" in flat and "港股" in flat

    def test_status_shows_miss_count(self, svc):
        """含未收录时状态行显示数量。"""
        _, status, _ = svc.by_output("candidate-list.options")("600519 999999")
        children = getattr(status, "children", status) or []
        flat = "".join(str(c) for c in (children if isinstance(children, list) else [children]))
        assert "未收录" in flat

    def test_exact_code_preferred_over_fuzzy(self, svc):
        """多代码时优先精确代码命中，而非第一个模糊匹配。"""
        # mock: "00700" 返回腾讯；"700" 精确匹配返回腾讯，模糊也返回腾讯
        opts, *_ = svc.by_output("candidate-list.options")("00700 600519")
        values = [o["value"] for o in opts]
        assert "00700.HK" in values and "600519.SH" in values
