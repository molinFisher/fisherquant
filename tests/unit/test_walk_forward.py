"""walk_forward 切分测试（P2 低覆盖补齐）。

覆盖 fisher/strategy/walk_forward.py：
- walk_forward 的 fold 数量符合 n_splits；
- 每个 fold 的测试窗口长度符合 n//(n_splits+1)；
- 相邻 fold 的测试区间连续且不重叠（训练/测试无泄漏）；
- train_test_split 按时间切分，train/test 日期集合不相交、顺序正确、比例符合配置；
- 数据不足时 walk_forward 返回 ok=False 且给出 reason。
"""
from datetime import date, timedelta
import pytest
import polars as pl
from fisher.strategy.walk_forward import walk_forward, train_test_split


def _make_bars(n: int) -> pl.DataFrame:
    base = date(2024, 1, 1)
    dates = [(base + timedelta(days=i)).isoformat() for i in range(n)]
    return pl.DataFrame({"ticker": ["X"] * n, "trade_date": dates, "close": [1.0] * n})


def _unique(df: pl.DataFrame) -> list:
    return df.select("trade_date").unique().sort("trade_date")["trade_date"].to_list()


class TestWalkForwardFolds:
    def test_fold_count_equals_n_splits(self):
        df = _make_bars(30)
        captured = []
        result = walk_forward(df, lambda d: captured.append(d.height) or {"nav_history": [100.0 + j for j in range(d.height)]},
                              n_splits=5, train_size=0.6)
        assert result["ok"] is True
        assert result["n_folds"] == 5
        assert len(result["folds"]) == 5
        # 每个 fold 测试窗口长度 = n // (n_splits+1) = 30//6 = 5
        assert set(captured) == {5}

    def test_folds_contiguous_no_leakage(self):
        df = _make_bars(30)
        result = walk_forward(df, lambda d: {"nav_history": [100.0 + i for i in range(d.height)]},
                              n_splits=5, train_size=0.6)
        folds = result["folds"]
        assert len(folds) == 5
        # 相邻 fold 的测试区间严格递增、不重叠 -> 测试集不混入彼此
        for a, b in zip(folds, folds[1:]):
            assert a["end"] < b["start"]

    def test_fold_metrics_present(self):
        df = _make_bars(30)
        result = walk_forward(df, lambda d: {"nav_history": list(range(100, 100 + d.height))},
                              n_splits=5, train_size=0.6)
        fold = result["folds"][0]
        assert "start" in fold and "end" in fold
        assert "cumulative_return" in fold
        assert "sharpe_ratio" in fold
        assert "max_drawdown" in fold

    def test_synthetic_nav_yields_positive_sharpe(self):
        df = _make_bars(30)
        result = walk_forward(df, lambda d: {"nav_history": [100.0 + i for i in range(d.height)]},
                              n_splits=5, train_size=0.6)
        # 单调上涨净值 -> 平均夏普 > 0
        assert result["avg_sharpe"] > 0


class TestWalkForwardInsufficientData:
    def test_too_few_dates_returns_ok_false(self):
        df = _make_bars(3)  # 3 < 2*5
        result = walk_forward(df, lambda d: {"nav_history": list(range(d.height))},
                              n_splits=5, train_size=0.6)
        assert result["ok"] is False
        assert "reason" in result
        assert result["folds"] == []

    def test_invalid_n_splits(self):
        df = _make_bars(20)
        # n_splits < 1 -> 直接判不足
        result = walk_forward(df, lambda d: {"nav_history": list(range(d.height))},
                              n_splits=0, train_size=0.6)
        assert result["ok"] is False


class TestTrainTestSplit:
    def test_split_ratio_and_disjoint(self):
        df = _make_bars(10)
        train, test = train_test_split(df, train_frac=0.6)
        train_dates = set(_unique(train))
        test_dates = set(_unique(test))
        # 比例：cut = int(10*0.6) = 6 -> 训练 6 条，测试 4 条
        assert len(train_dates) == 6
        assert len(test_dates) == 4
        # 不相交（无泄漏）
        assert train_dates.isdisjoint(test_dates)
        # 训练均早于测试
        assert max(train_dates) < min(test_dates)

    def test_split_preserves_rows(self):
        df = _make_bars(10)
        train, test = train_test_split(df, train_frac=0.6)
        # 切分不改变总行数（无重复无丢失）
        assert train.height + test.height == df.height

    def test_too_few_dates_returns_full(self):
        # n < 4 时返回 (df, df) 本身
        df = _make_bars(3)
        train, test = train_test_split(df, train_frac=0.6)
        assert train.height == df.height
        assert test.height == df.height
