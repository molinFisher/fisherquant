# tests/unit/test_market_rules.py
from fisher.market.rules import AShareRules, HKConnectRules, ETFRules, CBRules


class TestAShareRules:
    def test_t_plus_one(self):
        rules = AShareRules()
        assert rules.t_plus == 1

    def test_lot_size_100(self):
        rules = AShareRules()
        assert rules.lot_size("000001.SZ") == 100

    def test_mainboard_price_limits(self):
        rules = AShareRules()
        upper, lower = rules.price_limits(10.0, "000001.SZ")
        assert upper == 11.0
        assert lower == 9.0

    def test_stock_trading_sessions(self):
        rules = AShareRules()
        sessions = rules.trading_sessions()
        assert len(sessions) >= 2

    def test_stamp_duty_sell_only(self):
        rules = AShareRules()
        assert rules.stamp_duty == 0.0005
        assert rules.stamp_duty_side == "sell"


class TestHKConnectRules:
    def test_t_plus_zero(self):
        rules = HKConnectRules()
        assert rules.t_plus == 0

    def test_lot_size_variable(self):
        rules = HKConnectRules()
        assert rules.lot_size("00700.HK") == 100

    def test_no_price_limits(self):
        rules = HKConnectRules()
        upper, lower = rules.price_limits(10.0, "00700.HK")
        assert upper == float("inf")
        assert lower == 0.0

    def test_stamp_duty_both_sides(self):
        rules = HKConnectRules()
        assert rules.stamp_duty == 0.001
        assert rules.stamp_duty_side == "both"


class TestETFRules:
    def test_t_plus_one(self):
        rules = ETFRules()
        assert rules.t_plus == 1

    def test_no_stamp_duty(self):
        rules = ETFRules()
        assert rules.stamp_duty == 0.0
        assert rules.stamp_duty_side == "none"

    def test_lot_size_100(self):
        rules = ETFRules()
        assert rules.lot_size("510050.SH") == 100


class TestCBRules:
    def test_t_plus_zero(self):
        rules = CBRules()
        assert rules.t_plus == 0

    def test_no_stamp_duty(self):
        rules = CBRules()
        assert rules.stamp_duty == 0.0

    def test_lot_size_10(self):
        rules = CBRules()
        assert rules.lot_size("123456.SZ") == 10
