"""策略中心 × 缓存数据 联动服务（P0/P1 后端实现）。

职责（对应 PRD_策略中心缓存联动优化_V1.0.md v1.1 的 MVP）：
- 推导某策略回测所需的缓存数据类型（日线必选；A 股须 adj；custom DSL 引用财务指标须 financials）；
- 基于 cache_catalog 的覆盖度布尔 + 日期边界做"数据就绪校验"，产出缺失清单（可拦截/可部分跑）；
- 加载回测用 bars 时对 A 股默认注入前复权（qfq）口径，收益口径正确；
- 计算"使用缓存区间"（各标的 daily_start/end 并集）。

所有方法为纯函数式、依赖 cache_catalog 查询与 DuckDB，便于单测注入。
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import polars as pl

from ...store.engine import DuckDBManager

_A_SHARE_SUFFIXES = (".SH", ".SZ", ".BJ")
_FINANCIAL_KEYWORDS = ("financials", "财报", "财务指标", "财务数据")


def is_a_share(ticker: str) -> bool:
    """A 股判定：代码后缀 .SH/.SZ/.BJ。港股通为 .HK，无复权口径。"""
    return bool(ticker) and ticker.upper().endswith(_A_SHARE_SUFFIXES)


def _requires_financials(strategy_config: dict) -> bool:
    """仅当 custom DSL 显式引用财务指标时才把 financials 列为必需（避免误报）。"""
    if strategy_config.get("type") != "custom":
        return False
    dsl = strategy_config.get("params", {}).get("dsl_config", "")
    if not isinstance(dsl, str):
        dsl = str(dsl)
    dsl_low = dsl.lower()
    return any(kw.lower() in dsl_low for kw in _FINANCIAL_KEYWORDS)


@dataclass
class MissingItem:
    symbol: str
    types: list[str] = field(default_factory=list)   # 缺的具体类型：daily/adj/financials
    out_of_range: bool = False                          # 是否越界（无重叠）
    note: str = ""


@dataclass
class ReadinessReport:
    ready: bool                                            # 全部就绪
    blocking: bool                                         # 全缺，应阻断回测
    missing: list[MissingItem] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    requires_financials: bool = False

    @property
    def status(self) -> str:
        """三态：✓ 可回测 / ⚠ 部分缺(仍可跑) / ✗ 全缺(不可跑)。"""
        if self.ready:
            return "ready"
        if self.blocking:
            return "blocked"
        return "partial"


class StrategyDataService:
    def __init__(self, catalog_service, db: Optional[DuckDBManager] = None):
        self._catalog = catalog_service
        self._db = db

    # ------------------------------------------------------------------ #
    # 必需数据类型推导
    # ------------------------------------------------------------------ #
    def required_types_for(self, strategy_config: dict, symbols: list[str]) -> dict[str, list[str]]:
        """返回 {symbol: [必需类型...]}。日线必选；A 股须 adj；财务策略须 financials。"""
        requires_fin = _requires_financials(strategy_config)
        result: dict[str, list[str]] = {}
        for sym in symbols:
            req = ["daily"]
            if is_a_share(sym):
                req.append("adj")
            if requires_fin:
                req.append("financials")
            result[sym] = req
        return result

    # ------------------------------------------------------------------ #
    # 数据就绪校验
    # ------------------------------------------------------------------ #
    def check_data_readiness(
        self,
        strategy_config: dict,
        start_date: str,
        end_date: str,
        symbols: Optional[list[str]] = None,
    ) -> ReadinessReport:
        """基于 cache_catalog 校验 策略.symbols × [start,end] × 必需类型。

        - symbols 为空 → 视为"全部缓存标的"，只要有任一 has_daily 即不阻断；
        - 任一声称的标的不在 catalog（未缓存）→ 缺 daily（A 股另缺 adj）；
        - 在区间内 has_*=FALSE → 缺对应类型；
        - 区间与 daily_start/daily_end 无重叠 → out_of_range（越界）；
        - blocking = 所有被检标的全部缺失（无可跑数据）。
        """
        syms = list(symbols) if symbols is not None else list(strategy_config.get("symbols") or [])

        if not syms:
            # 全部缓存标的：取 has_daily 的标的作为范围
            all_rows = self._catalog.get_cache_catalog()
            syms = [r["ticker"] for r in all_rows if r.get("has_daily")]
            if not syms:
                return ReadinessReport(
                    ready=False, blocking=True, missing=[], symbols=[],
                    requires_financials=_requires_financials(strategy_config),
                )

        coverage = self._catalog.get_coverage_for_tickers(syms)
        requires_fin = _requires_financials(strategy_config)
        missing: list[MissingItem] = []

        for sym in syms:
            req = ["daily"]
            if is_a_share(sym):
                req.append("adj")
            if requires_fin:
                req.append("financials")

            row = coverage.get(sym)
            if row is None:
                missing.append(MissingItem(
                    symbol=sym, types=req, out_of_range=False, note="未缓存（cache_catalog 无记录）"))
                continue

            miss_types = [t for t in req if not row.get(f"has_{t}")]
            out_of_range = self._is_out_of_range(row, start_date, end_date)
            if miss_types or out_of_range:
                note = "区间越界" if out_of_range and not miss_types else ""
                missing.append(MissingItem(
                    symbol=sym, types=miss_types, out_of_range=out_of_range, note=note))

        blocking = bool(syms) and len(missing) == len(syms)
        return ReadinessReport(
            ready=len(missing) == 0,
            blocking=blocking,
            missing=missing,
            symbols=syms,
            requires_financials=requires_fin,
        )

    @staticmethod
    def _is_out_of_range(row: dict, start_date: str, end_date: str) -> bool:
        ds = row.get("daily_start")
        de = row.get("daily_end")
        if not ds or not de or not start_date or not end_date:
            return False
        ds_s = str(ds)[:10]
        de_s = str(de)[:10]
        # 无重叠：end < ds 或 start > de
        return end_date < ds_s or start_date > de_s

    # ------------------------------------------------------------------ #
    # 复权注入的回测 bars 加载
    # ------------------------------------------------------------------ #
    def load_adjusted_bars(
        self, symbol: str, start_date: str, end_date: str, adj_type: str = "qfq"
    ) -> pl.DataFrame:
        """加载回测用日线；对 A 股按 adj_type（默认 qfq）归一价格。

        复权公式（方向无关，收益率等价）：adjusted = raw / adj_factor。
        返回与 backtest_callbacks._load_bars 同 schema 的 pl.DataFrame：
        [ticker, trade_date, open, high, low, close, volume, amount, market]。
        """
        db = self._db
        if db is None:
            from . import get_db
            db = get_db()
        df = db.query_df(
            "SELECT ticker, trade_date, open, high, low, close, volume, amount, market "
            "FROM bars_daily WHERE ticker=? AND trade_date BETWEEN ? AND ? ORDER BY trade_date",
            [symbol, start_date, end_date],
        )
        if len(df) == 0:
            return df

        if adj_type not in ("qfq", "hfq") or not is_a_share(symbol):
            return df.select(
                ["ticker", "trade_date", "open", "high", "low", "close", "volume", "amount", "market"]
            )

        adj = db.query_df(
            "SELECT trade_date, adj_factor FROM adj_factors "
            "WHERE ticker=? AND adj_type=? AND trade_date BETWEEN ? AND ?",
            [symbol, adj_type, start_date, end_date],
        )
        if len(adj) == 0:
            return df.select(
                ["ticker", "trade_date", "open", "high", "low", "close", "volume", "amount", "market"]
            )

        factor_map = {str(r["trade_date"])[:10]: r["adj_factor"] for r in adj.iter_rows(named=True)}

        rows = []
        for r in df.iter_rows(named=True):
            f = factor_map.get(str(r["trade_date"])[:10])
            if f and f != 0:
                o = r["open"] / f
                h = r["high"] / f
                l = r["low"] / f
                c = r["close"] / f
            else:
                o, h, l, c = r["open"], r["high"], r["low"], r["close"]
            rows.append({
                "ticker": r["ticker"],
                "trade_date": r["trade_date"],
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": r["volume"],
                "amount": r["amount"],
                "market": r["market"],
            })
        return pl.DataFrame(rows).select(
            ["ticker", "trade_date", "open", "high", "low", "close", "volume", "amount", "market"]
        )

    # ------------------------------------------------------------------ #
    # 使用缓存区间（各标的 daily_start/end 并集）
    # ------------------------------------------------------------------ #
    def cache_range_for(
        self, strategy_config: dict, symbols: Optional[list[str]] = None
    ) -> tuple[str, str]:
        syms = list(symbols) if symbols is not None else list(strategy_config.get("symbols") or [])
        default_start = "2024-01-01"
        default_end = date.today().isoformat()

        if not syms:
            all_rows = self._catalog.get_cache_catalog()
            syms = [r["ticker"] for r in all_rows if r.get("has_daily")]
        if not syms:
            return default_start, default_end

        coverage = self._catalog.get_coverage_for_tickers(syms)
        starts, ends = [], []
        for sym in syms:
            row = coverage.get(sym)
            if row and row.get("daily_start") and row.get("daily_end"):
                starts.append(str(row["daily_start"])[:10])
                ends.append(str(row["daily_end"])[:10])
        if not starts:
            return default_start, default_end
        return min(starts), max(ends)
