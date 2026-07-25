import pytest
from fisher.event.types import OrderSide
from fisher.paper.fees import FeeCalculator
from fisher.config.schemas import AssetFeeConfig, FeesConfig

A_SHARE_FEE = AssetFeeConfig(
    commission_rate=0.00025,
    min_commission=5.0,
    stamp_duty=0.0005,
    stamp_duty_side="sell",
    transfer_fee=0.00001,
    regulatory_fee=0.0000687,
)

ETF_FEE = AssetFeeConfig(
    commission_rate=0.0001,
    min_commission=1.0,
    stamp_duty=0.0,
    stamp_duty_side="none",
)

HK_FEE = AssetFeeConfig(
    commission_rate=0.00025,
    min_commission=100.0,
    stamp_duty=0.001,
    stamp_duty_side="both",
    regulatory_fee=0.0000835,
    settlement_fee=0.00002,
)

CB_FEE = AssetFeeConfig(
    commission_rate=0.00005,
    min_commission=1.0,
    stamp_duty=0.0,
    stamp_duty_side="none",
)


class TestFeeCalculator:
    def test_as_share_buy_commission_min(self):
        calc = FeeCalculator({"a_share": A_SHARE_FEE})
        result = calc.calculate("a_share", OrderSide.BUY, 1000.0, 100)
        assert result["commission"] == 5.0  # min commission kicks in

    def test_as_share_buy_commission(self):
        calc = FeeCalculator({"a_share": A_SHARE_FEE})
        result = calc.calculate("a_share", OrderSide.BUY, 50000.0, 100)
        expected_commission = max(50000.0 * 0.00025, 5.0)  # 12.5 > 5
        assert result["commission"] == pytest.approx(expected_commission)

    def test_as_share_buy_no_stamp_duty(self):
        calc = FeeCalculator({"a_share": A_SHARE_FEE})
        result = calc.calculate("a_share", OrderSide.BUY, 10000.0, 100)
        assert result["stamp_duty"] == 0.0

    def test_as_share_sell_stamp_duty(self):
        calc = FeeCalculator({"a_share": A_SHARE_FEE})
        result = calc.calculate("a_share", OrderSide.SELL, 10000.0, 100)
        assert result["stamp_duty"] == pytest.approx(10000.0 * 0.0005)

    def test_as_share_buy_transfer_fee(self):
        calc = FeeCalculator({"a_share": A_SHARE_FEE})
        result = calc.calculate("a_share", OrderSide.BUY, 10000.0, 100)
        assert result["transfer_fee"] == pytest.approx(10000.0 * 0.00001)

    def test_as_share_total_all_fields_present(self):
        calc = FeeCalculator({"a_share": A_SHARE_FEE})
        result = calc.calculate("a_share", OrderSide.BUY, 10000.0, 100)
        for field in ["commission", "stamp_duty", "transfer_fee", "regulatory_fee", "total"]:
            assert field in result
        expected_total = (
            result["commission"]
            + result["stamp_duty"]
            + result["transfer_fee"]
            + result["regulatory_fee"]
        )
        assert result["total"] == pytest.approx(expected_total)

    def test_etf_no_stamp_duty_either_side(self):
        calc = FeeCalculator({"etf": ETF_FEE})
        buy = calc.calculate("etf", OrderSide.BUY, 10000.0, 100)
        sell = calc.calculate("etf", OrderSide.SELL, 10000.0, 100)
        assert buy["stamp_duty"] == 0.0
        assert sell["stamp_duty"] == 0.0

    def test_hk_connect_stamp_duty_both_sides(self):
        calc = FeeCalculator({"hk_connect": HK_FEE})
        buy = calc.calculate("hk_connect", OrderSide.BUY, 100000.0, 100)
        sell = calc.calculate("hk_connect", OrderSide.SELL, 100000.0, 100)
        assert buy["stamp_duty"] == pytest.approx(100000.0 * 0.001)
        assert sell["stamp_duty"] == pytest.approx(100000.0 * 0.001)

    def test_hk_connect_min_commission(self):
        calc = FeeCalculator({"hk_connect": HK_FEE})
        result = calc.calculate("hk_connect", OrderSide.BUY, 1000.0, 100)
        assert result["commission"] == 100.0  # min HK commission

    def test_cb_commission(self):
        calc = FeeCalculator({"convertible_bond": CB_FEE})
        result = calc.calculate("convertible_bond", OrderSide.BUY, 20000.0, 10)
        expected = max(20000.0 * 0.00005, 1.0)
        assert result["commission"] == pytest.approx(expected)

    def test_unknown_market_raises(self):
        calc = FeeCalculator({"a_share": A_SHARE_FEE})
        with pytest.raises(ValueError, match="Unknown market"):
            calc.calculate("futures", OrderSide.BUY, 10000.0, 100)

    def test_zero_trade_value(self):
        calc = FeeCalculator({"a_share": A_SHARE_FEE})
        result = calc.calculate("a_share", OrderSide.BUY, 0.0, 100)
        assert result["commission"] == 0.0
        assert result["total"] == 0.0

    def test_regulatory_fee_included(self):
        calc = FeeCalculator({"a_share": A_SHARE_FEE})
        result = calc.calculate("a_share", OrderSide.BUY, 100000.0, 100)
        assert result["regulatory_fee"] == pytest.approx(100000.0 * 0.0000687)

    def test_from_config(self):
        config = FeesConfig(assets={"a_share": A_SHARE_FEE, "etf": ETF_FEE})
        calc = FeeCalculator.from_config(config)
        result = calc.calculate("a_share", OrderSide.SELL, 10000.0, 100)
        assert result["stamp_duty"] > 0
        assert result["commission"] > 0
