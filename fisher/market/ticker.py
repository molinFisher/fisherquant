# fisher/market/ticker.py
"""标的代码归一化工具。

核心约束（PRD v2.0 / R1）：resolve_ticker 必须幂等——若输入已带合法交易所后缀，
则原样返回，避免重复拼接产生 `600519.SH.SH` 这类双后缀脏数据。
"""
from __future__ import annotations

# 按代码首字符推导交易所后缀（A 股 6 位代码、港股 5 位代码）
EXCHANGE_MAP: dict[str, str] = {
    "6": ".SH", "5": ".SH", "9": ".SH",  # 沪市主板 / 沪市基金 / 沪市 B 股
    "0": ".SZ", "3": ".SZ", "2": ".SZ", "4": ".SZ",  # 深市主板 / 创业板 / 深市 B 股 / 其他深市
    "8": ".BJ",  # 北交所
}

# 所有合法交易所后缀；用于幂等判断
KNOWN_SUFFIXES: tuple[str, ...] = (".SH", ".SZ", ".HK", ".BJ")


def resolve_ticker(code: str, market: str = "a_share") -> str:
    """将任意形态的代码归一化为带后缀的标准标的。

    幂等性保证：无论输入是纯代码（`600519`）、单后缀（`600519.SH`）还是
    双后缀脏数据（`600519.SH.SH`），都先取首个 `.` 之前的纯代码重新归一化，
    因此重复调用结果稳定，绝不会产生 `600519.SH.SH`。
    - 未知前缀：返回纯代码，交由调用方决定，不再生成 `.UNKNOWN` 脏后缀。
    """
    code = (code or "").strip().upper()
    if not code:
        return code

    # 始终取首个 '.' 之前的纯代码——这是幂等的核心，杜绝双后缀
    base = code.split(".")[0]

    if market == "hk_connect":
        return f"{base.zfill(5)}.HK"

    suffix = EXCHANGE_MAP.get(base[:1], "")
    if suffix:
        return f"{base}{suffix}"

    # 未知市场/前缀：返回纯代码（不再生成 .UNKNOWN）
    return base
