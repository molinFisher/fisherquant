"""标的搜索 V1.2 纯函数模块（PRD FR-1.x / FR-2.x）。

无 I/O、无外部依赖（pypinyin 可选降级），全部可单测：
- normalize_query   R-20 归一化（trim / 大写 / 全角转半角）
- escape_like       R-22 LIKE 通配符转义（%、_、\\，配合 ESCAPE '\\'）
- code_variants     R-21 纯数字查询的港股零填充变体（R-01 口径：5 位）
- to_pinyin         R-14 名称 → 全拼 / 首字母（离线生成，写入 symbol_dict）
- rank_results      R-23 排序：代码精确 > 代码前缀 > 名称前缀 > 包含 > 拼音
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from pypinyin import lazy_pinyin, Style
    _HAS_PINYIN = True
except ImportError:  # 环境缺依赖时降级：拼音字段为空，不影响代码/名称搜索
    _HAS_PINYIN = False
    logger.warning("pypinyin 未安装，标的字典拼音字段将为空")

MAX_RESULTS = 20

# 全角 → 半角（含全角空格 U+3000）
_FULLWIDTH_OFFSET = 0xFEE0


def normalize_query(query: str | None) -> str:
    """R-20：trim + 全角转半角 + 统一大写。返回空串表示无效查询。"""
    if not query:
        return ""
    out = []
    for ch in query.strip():
        code = ord(ch)
        if code == 0x3000:  # 全角空格
            ch = " "
        elif 0xFF01 <= code <= 0xFF5E:  # 全角可见字符
            ch = chr(code - _FULLWIDTH_OFFSET)
        out.append(ch)
    return "".join(out).strip().upper()


def escape_like(text: str) -> str:
    r"""R-22：转义 LIKE 通配符。使用方须在 SQL 中带 ESCAPE '\'。"""
    return (
        text.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def code_variants(query: str) -> list[str]:
    """R-21/R-01：纯数字查询生成代码变体（原样 + 港股 5 位零填充）。

    例：'700' -> ['700', '00700']；'600519' -> ['600519']；非数字 -> []。
    """
    q = query.strip()
    if not q.isdigit():
        return []
    variants = [q]
    if len(q) < 5:
        padded = q.zfill(5)
        if padded != q:
            variants.append(padded)
    return variants


def to_pinyin(name: str) -> tuple[str, str]:
    """R-14：名称 → (全拼, 首字母缩写)，均为大写。非中文字符原样保留。

    例：'贵州茅台' -> ('GUIZHOUMAOTAI', 'GZMT')；'万  科Ａ' 内部空格剔除。
    """
    if not name or not _HAS_PINYIN:
        return "", ""
    clean = name.replace(" ", "").replace("\u3000", "")
    if not clean:
        return "", ""
    try:
        full = "".join(lazy_pinyin(clean)).upper()
        abbr = "".join(lazy_pinyin(clean, style=Style.FIRST_LETTER)).upper()
        return full, abbr
    except Exception as e:  # pypinyin 对个别字符抛错时不阻断刷新
        logger.debug("to_pinyin failed for %r: %s", name, e)
        return "", ""


def rank_key(row: dict, nq: str, variants: list[str]) -> tuple:
    """R-23：为单条候选生成排序键（越小越靠前）。

    优先级：
    0 代码精确命中（含零填充变体、ticker 精确）
    1 代码前缀
    2 名称前缀
    3 名称包含
    4 拼音（全拼/缩写）前缀
    5 其他（拼音包含、代码包含）
    同级按 market（a_share 先）、代码升序。
    """
    code = str(row.get("code", "")).upper()
    ticker = str(row.get("ticker", "")).upper()
    name = str(row.get("name", "")).upper()
    py_full = str(row.get("pinyin_full", "")).upper()
    py_abbr = str(row.get("pinyin_abbr", "")).upper()

    all_codes = {code, ticker}
    if code in variants or ticker in variants or nq in all_codes:
        tier = 0
    elif code.startswith(nq) or ticker.startswith(nq) or any(
        code.startswith(v) for v in variants
    ):
        tier = 1
    elif name.startswith(nq):
        tier = 2
    elif nq in name:
        tier = 3
    elif py_abbr.startswith(nq) or py_full.startswith(nq):
        tier = 4
    else:
        tier = 5
    market_order = 0 if row.get("market") == "a_share" else 1
    return (tier, market_order, code)


def rank_results(rows: list[dict], nq: str, variants: list[str],
                 limit: int = MAX_RESULTS) -> list[dict]:
    """R-23：排序并截断到 limit 条。"""
    return sorted(rows, key=lambda r: rank_key(r, nq, variants))[:limit]
