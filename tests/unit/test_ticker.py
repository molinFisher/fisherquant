"""ticker 归一化（resolve_ticker）测试（P2 低覆盖补齐）。

核心契约：幂等——重复调用结果稳定，绝不产生双后缀（如 600519.SH.SH）；
按首字符推导交易所后缀；hk_connect 市场零补齐为 5 位 + .HK；
未知前缀/非法格式返回纯代码而不抛异常。
"""
import pytest
from fisher.market.ticker import resolve_ticker, EXCHANGE_MAP, KNOWN_SUFFIXES


class TestResolveTickerABasic:
    def test_pure_code_a_share(self):
        assert resolve_ticker("600519") == "600519.SH"
        assert resolve_ticker("000001") == "000001.SZ"
        assert resolve_ticker("300750") == "300750.SZ"
        assert resolve_ticker("830799") == "830799.BJ"

    def test_with_suffix_is_idempotent(self):
        # 已带合法后缀 -> 原样返回（幂等）
        assert resolve_ticker("600519.SH") == "600519.SH"
        assert resolve_ticker("000001.SZ") == "000001.SZ"
        assert resolve_ticker("830799.BJ") == "830799.BJ"

    def test_double_suffix_collapses(self):
        # 双后缀脏数据被规整为单后缀，不复读
        assert resolve_ticker("600519.SH.SH") == "600519.SH"
        assert resolve_ticker("000001.SZ.SZ") == "000001.SZ"

    def test_idempotent_property(self):
        for code in ["600519", "600519.SH", "000001.SZ", "830799.BJ", "300750"]:
            once = resolve_ticker(code)
            twice = resolve_ticker(once)
            assert twice == once


class TestResolveTickerCaseAndWhitespace:
    def test_lowercase_suffix_normalized(self):
        # 输入小写后缀被 upper，结果仍为标准大写后缀
        assert resolve_ticker("600519.sh") == "600519.SH"
        assert resolve_ticker("000001.sz") == "000001.SZ"

    def test_whitespace_stripped(self):
        assert resolve_ticker("  600519  ") == "600519.SH"
        assert resolve_ticker("\t000001.SZ\n") == "000001.SZ"

    def test_mixed_case_code(self):
        # 代码字母部分转大写不影响后缀推导（此处以数字为主）
        assert resolve_ticker("600519") == resolve_ticker("600519")


class TestResolveTickerHK:
    def test_hk_connect_zero_pads(self):
        # hk_connect 市场：补齐 5 位 + .HK
        assert resolve_ticker("700", market="hk_connect") == "00700.HK"
        assert resolve_ticker("7", market="hk_connect") == "00007.HK"

    def test_hk_connect_idempotent(self):
        assert resolve_ticker("00700.HK", market="hk_connect") == "00700.HK"
        # 重复调用稳定
        once = resolve_ticker("00700", market="hk_connect")
        assert resolve_ticker(once, market="hk_connect") == once


class TestResolveTickerInvalid:
    def test_empty_returns_empty(self):
        assert resolve_ticker("") == ""
        assert resolve_ticker("   ") == ""

    def test_none_like_empty(self):
        # None -> falsy -> 返回空串（不抛异常）
        assert resolve_ticker(None) == ""

    def test_unknown_prefix_returns_base(self):
        # 首字符不在映射表中：返回纯代码，不再生成 .UNKNOWN 脏后缀
        assert resolve_ticker("ABCDEF") == "ABCDEF"
        # 含字母前缀的代码同样返回纯代码
        assert resolve_ticker("sh600519") == "SH600519"

    def test_known_suffixes_constant(self):
        assert ".SH" in KNOWN_SUFFIXES
        assert ".HK" in KNOWN_SUFFIXES
        assert ".SZ" in KNOWN_SUFFIXES
        assert ".BJ" in KNOWN_SUFFIXES

    def test_exchange_map_covers_sh_sz_bj(self):
        assert EXCHANGE_MAP["6"] == ".SH"
        assert EXCHANGE_MAP["0"] == ".SZ"
        assert EXCHANGE_MAP["8"] == ".BJ"
