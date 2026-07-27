"""标的搜索纯函数单测（PRD FR-1.x / FR-2.x，对应 R-20~R-23）。"""
import pytest

from fisher.dash_app.services.symbol_search import (
    normalize_query,
    escape_like,
    code_variants,
    to_pinyin,
    rank_key,
    rank_results,
    MAX_RESULTS,
)


class TestNormalizeQuery:
    def test_trim_and_upper(self):
        assert normalize_query("  maotai ") == "MAOTAI"

    def test_fullwidth_digits_to_halfwidth(self):
        assert normalize_query("６００５１９") == "600519"

    def test_fullwidth_letters_to_halfwidth(self):
        assert normalize_query("ＧＺＭＴ") == "GZMT"

    def test_fullwidth_space(self):
        assert normalize_query("600\u3000519") == "600 519"

    def test_none_and_empty(self):
        assert normalize_query(None) == ""
        assert normalize_query("   ") == ""

    def test_chinese_untouched(self):
        assert normalize_query(" 贵州茅台 ") == "贵州茅台"


class TestEscapeLike:
    def test_escape_percent(self):
        assert escape_like("50%") == "50\\%"

    def test_escape_underscore(self):
        assert escape_like("a_b") == "a\\_b"

    def test_escape_backslash_first(self):
        # 反斜杠必须先转义，避免二次转义把 % 的转义符再吃掉
        assert escape_like("a\\b") == "a\\\\b"

    def test_escape_combo(self):
        assert escape_like("a_b%c\\d") == "a\\_b\\%c\\\\d"

    def test_plain_text_unchanged(self):
        assert escape_like("600519") == "600519"


class TestCodeVariants:
    def test_short_digit_padded(self):
        assert code_variants("700") == ["700", "00700"]

    def test_four_digit_padded(self):
        assert code_variants("0700") == ["0700", "00700"]

    def test_full_six_digit_no_pad(self):
        assert code_variants("600519") == ["600519"]

    def test_already_five_digit(self):
        assert code_variants("00700") == ["00700"]

    def test_non_digit_empty(self):
        assert code_variants("abc") == []
        assert code_variants("60w") == []


class TestToPinyin:
    def test_basic(self):
        full, abbr = to_pinyin("贵州茅台")
        assert full == "GUIZHOUMAOTAI"
        assert abbr == "GZMT"

    def test_strips_inner_space(self):
        full, abbr = to_pinyin("万 科")
        assert " " not in full
        assert abbr.startswith("W")

    def test_empty(self):
        assert to_pinyin("") == ("", "")


class TestRanking:
    ROWS = [
        {"code": "600519", "ticker": "600519.SH", "name": "贵州茅台",
         "market": "a_share", "pinyin_full": "GUIZHOUMAOTAI", "pinyin_abbr": "GZMT"},
        {"code": "000700", "ticker": "000700.SZ", "name": "模范",
         "market": "a_share", "pinyin_full": "MOFAN", "pinyin_abbr": "MF"},
        {"code": "00700", "ticker": "00700.HK", "name": "腾讯控股",
         "market": "hk_connect", "pinyin_full": "TENGXUNKONGGU", "pinyin_abbr": "TXKG"},
    ]

    def test_exact_variant_first(self):
        r = rank_results(self.ROWS, "700", ["700", "00700"])
        assert r[0]["ticker"] == "00700.HK"

    def test_code_prefix_beats_contains(self):
        rows = [
            {"code": "000600", "ticker": "000600.SZ", "name": "建投能源",
             "market": "a_share", "pinyin_full": "", "pinyin_abbr": ""},
            {"code": "600000", "ticker": "600000.SH", "name": "浦发银行",
             "market": "a_share", "pinyin_full": "", "pinyin_abbr": ""},
        ]
        r = rank_results(rows, "600", ["600", "00600"])
        # 600000 前缀命中，应排在 000600（仅包含）之前
        assert r[0]["ticker"] == "600000.SH"

    def test_pinyin_abbr_match(self):
        r = rank_results(self.ROWS, "GZMT", [])
        assert r[0]["ticker"] == "600519.SH"

    def test_truncate_to_limit(self):
        rows = [{"code": f"{i:06d}", "ticker": f"{i:06d}.SZ", "name": f"股{i}",
                 "market": "a_share", "pinyin_full": "", "pinyin_abbr": ""}
                for i in range(50)]
        r = rank_results(rows, "0", [], limit=MAX_RESULTS)
        assert len(r) == MAX_RESULTS

    def test_rank_key_tiers(self):
        row = self.ROWS[0]
        # 精确代码 -> tier 0
        assert rank_key(row, "600519", ["600519"])[0] == 0
        # 名称前缀 -> tier 2
        assert rank_key(row, "贵州", [])[0] == 2
        # 名称包含 -> tier 3
        assert rank_key(row, "茅台", [])[0] == 3
