"""market.rules 单元级测试：交易所交易规则（涨跌停/最小变动价位/手数/印花税/时段）。

此前覆盖率约 63%，补齐纯函数分支：A股/港股通/ETF/可转债四类的 price_limits、
tick_size 分档、lot_size、t_plus、stamp_duty/side、trading_sessions，以及
get_rules 的分发与未知市场抛错。
"""
import pytest

from fisher.market.rules import (
    AShareRules, HKConnectRules, ETFRules, CBRules, get_rules,
)


class TestAShareRules:
    def test_t_plus_and_stamp(self):
        r = AShareRules()
        assert r.t_plus == 1
        assert r.stamp_duty == 0.0005
        assert r.stamp_duty_side == "sell"
        assert r.lot_size("600519.SH") == 100
        assert r.tick_size(9.9) == 0.01

    def test_price_limits_normal(self):
        hi, lo = AShareRules().price_limits(10.0)
        assert hi == 10.0 * 1.10
        assert lo == 9.0

    def test_price_limits_star_688(self):
        hi, lo = AShareRules().price_limits(10.0, "688001.SH")
        assert hi == 12.0 and lo == 8.0

    def test_price_limits_chinext_300_301(self):
        assert AShareRules().price_limits(10.0, "300750.SZ")[0] == 12.0
        assert AShareRules().price_limits(10.0, "301000.SZ")[0] == 12.0

    def test_price_limits_bse_8(self):
        hi, lo = AShareRules().price_limits(10.0, "830799.BJ")
        assert hi == 13.0 and lo == 7.0

    def test_price_limits_st(self):
        hi, lo = AShareRules().price_limits(10.0, "ST某某")
        assert hi == 10.5 and lo == 9.5
        hi2, lo2 = AShareRules().price_limits(10.0, "*ST风险")
        assert hi2 == 10.5

    def test_sessions(self):
        assert AShareRules().trading_sessions() == [
            ("09:30", "11:30"), ("13:00", "15:00")]


class TestHKConnectRules:
    def test_t_plus_and_stamp(self):
        r = HKConnectRules()
        assert r.t_plus == 0
        assert r.stamp_duty == 0.001
        assert r.stamp_duty_side == "both"
        assert r.price_limits(10.0) == (float("inf"), 0.0)
        assert r.trading_sessions() == [("09:30", "12:00"), ("13:00", "16:00")]

    def test_lot_size_known_and_default(self):
        r = HKConnectRules()
        assert r.lot_size("00700.HK") == 100
        assert r.lot_size("09988.HK") == 100
        assert r.lot_size("01810.HK") == 200
        assert r.lot_size("01234.HK") == 100  # default

    def test_tick_size_tiers(self):
        r = HKConnectRules()
        assert r.tick_size(0.5) == 0.001
        assert r.tick_size(3.0) == 0.005
        assert r.tick_size(9.0) == 0.01
        assert r.tick_size(50.0) == 0.05
        assert r.tick_size(150.0) == 0.10   # 100 < price < 200
        assert r.tick_size(499.0) == 0.20   # 200 < price < 500
        assert r.tick_size(15.0) == 0.02    # 10 < price < 20
        assert r.tick_size(600.0) == 0.50   # 500 < price < 1000
        assert r.tick_size(1500.0) == 1.0  # 1000 < price < 2000
        assert r.tick_size(3000.0) == 2.0  # 2000 < price < 5000
        assert r.tick_size(6000.0) == 5.0   # 5000 < price < 9995
        assert r.tick_size(9999.0) == 0.0


class TestETFRules:
    def test_basics(self):
        r = ETFRules()
        assert r.t_plus == 1
        assert r.tick_size(1.0) == 0.001
        assert r.lot_size("510300.SH") == 100
        assert r.stamp_duty == 0.0
        assert r.stamp_duty_side == "none"
        hi, lo = r.price_limits(10.0)
        assert hi == 11.0 and lo == 9.0

    def test_sessions(self):
        assert ETFRules().trading_sessions() == [
            ("09:30", "11:30"), ("13:00", "15:00")]


class TestCBRules:
    def test_basics(self):
        r = CBRules()
        assert r.t_plus == 0
        assert r.lot_size("113001.SH") == 10
        assert r.stamp_duty == 0.0
        assert r.stamp_duty_side == "none"

    def test_price_limits_tiers(self):
        # 110/113/118/123/127/128 开头 -> ±20%
        assert CBRules().price_limits(100.0, "113001.SH")[0] == 120.0
        assert CBRules().price_limits(100.0, "128001.SH")[0] == 120.0
        # 其他可转债前缀（如 111）-> 默认 ±30%
        assert CBRules().price_limits(100.0, "111000.SH")[0] == 130.0

    def test_sessions(self):
        assert CBRules().trading_sessions() == [
            ("09:30", "11:30"), ("13:00", "15:00")]


class TestGetRulesDispatch:
    def test_dispatch(self):
        assert isinstance(get_rules("a_share"), AShareRules)
        assert isinstance(get_rules("hk_connect"), HKConnectRules)
        assert isinstance(get_rules("etf"), ETFRules)
        assert isinstance(get_rules("convertible_bond"), CBRules)

    def test_unknown_market_raises(self):
        with pytest.raises(ValueError):
            get_rules("not_a_market")
