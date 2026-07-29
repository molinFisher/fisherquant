"""停牌状态数据层（G2：可交易状态校验的数据依赖）。

对应 PRD Action A1：回测接入停牌校验前，必须先有"停牌状态"数据来源。
本模块提供：
- 内存态的停牌表（便于测试与离线场景）；
- 尽力而从的 akshare 获取（网络不可用时降级，不阻塞主流程）；
- `is_suspended(ticker, date)` 供 BacktestEngine 在每根 bar 判定标的是否可交易。
"""
import logging
from datetime import date

logger = logging.getLogger(__name__)


class SuspensionService:
    def __init__(self):
        # key: (ticker, "YYYY-MM-DD") -> True 表示当日停牌
        self._suspended: dict[tuple[str, str], bool] = {}

    def add_suspension(self, ticker: str, date_str: str) -> None:
        self._suspended[(ticker, date_str)] = True

    def add_suspension_range(self, ticker: str, start: str, end: str) -> None:
        """按日期区间批量标记停牌（含端点）。"""
        d0 = date.fromisoformat(start)
        d1 = date.fromisoformat(end)
        cur = d0
        one_day = __import__("datetime").timedelta(days=1)
        while cur <= d1:
            self._suspended[(ticker, cur.isoformat())] = True
            cur += one_day

    def is_suspended(self, ticker: str, date_str: str) -> bool:
        return self._suspended.get((ticker, date_str), False)

    def load_from_akshare(self, tickers: list[str] | None = None) -> int:
        """尽力从 akshare 获取停牌/复牌信息并写入内存表。

        网络或依赖不可用时记录警告并返回 0，不抛异常（离线安全）。
        返回成功写入的 (ticker, date) 记录数。
        """
        try:
            import akshare as ak  # noqa: F401
        except Exception as e:  # noqa: BLE001
            logger.warning("SuspensionService.load_from_akshare: akshare 不可用，跳过 (%s)", e)
            return 0
        try:
            df = ak.stock_suspend()
        except Exception as e:  # noqa: BLE001
            logger.warning("SuspensionService.load_from_akshare: 获取停牌数据失败 (%s)", e)
            return 0
        count = 0
        try:
            for _, row in df.iterrows():
                tk = str(row.get("代码") or row.get("symbol") or "")
                dt = str(row.get("停牌开始日期") or row.get("date") or "")
                if tk and dt:
                    self._suspended[(tk, dt)] = True
                    count += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("SuspensionService.load_from_akshare: 解析失败 (%s)", e)
        return count

    def clear(self) -> None:
        self._suspended.clear()
