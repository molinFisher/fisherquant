import pytest
import polars as pl
from fisher.backtest.time_player import TimePlayer
from fisher.event.types import Bar


@pytest.fixture
def sample_bars_df():
    return pl.DataFrame({
        "ticker": ["A", "A", "B", "B"],
        "trade_date": ["2024-01-01", "2024-01-02", "2024-01-01", "2024-01-02"],
        "open": [10.0, 11.0, 20.0, 21.0],
        "high": [10.5, 11.5, 20.5, 21.5],
        "low": [9.5, 10.5, 19.5, 20.5],
        "close": [10.2, 11.2, 20.2, 21.2],
        "volume": [1000, 1100, 2000, 2100],
        "amount": [10000.0, 11000.0, 20000.0, 21000.0],
        "market": ["a_share", "a_share", "a_share", "a_share"],
    })


class TestTimePlayer:
    def test_init_with_dataframe(self, sample_bars_df):
        player = TimePlayer(sample_bars_df)
        assert player is not None

    def test_iterate_sequential_bars(self, sample_bars_df):
        player = TimePlayer(sample_bars_df)
        bars = list(player)
        assert len(bars) == 4

    def test_bars_are_in_order(self, sample_bars_df):
        player = TimePlayer(sample_bars_df)
        dates = [b.bar_time for b in player]
        assert dates == sorted(dates)

    def test_bar_has_correct_fields(self, sample_bars_df):
        player = TimePlayer(sample_bars_df)
        first = list(player)[0]
        assert isinstance(first, Bar)
        assert first.ticker == "A"
        assert first.close == 10.2
        assert first.volume == 1000

    def test_iterate_by_date(self, sample_bars_df):
        player = TimePlayer(sample_bars_df)
        daily_bars = player.by_date()
        assert len(daily_bars) == 2
        for date_str, bars in daily_bars.items():
            assert len(bars) == 2

    def test_empty_dataframe(self):
        df = pl.DataFrame(schema={
            "ticker": pl.Utf8, "trade_date": pl.Utf8, "open": pl.Float64,
            "high": pl.Float64, "low": pl.Float64, "close": pl.Float64,
            "volume": pl.Int64, "amount": pl.Float64, "market": pl.Utf8,
        })
        player = TimePlayer(df)
        assert list(player) == []

    def test_len_returns_count(self, sample_bars_df):
        player = TimePlayer(sample_bars_df)
        assert len(player) == 4

    def test_filter_ticker(self, sample_bars_df):
        player = TimePlayer(sample_bars_df)
        bars = list(player.filter_ticker("A"))
        assert len(bars) == 2
        assert all(b.ticker == "A" for b in bars)

    def test_iterate_by_date_sorted(self, sample_bars_df):
        player = TimePlayer(sample_bars_df)
        daily = player.by_date()
        dates = list(daily.keys())
        assert dates == sorted(dates)
