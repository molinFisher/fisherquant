from ..event.types import OrderSide
from ..config.schemas import AssetFeeConfig, FeesConfig


class FeeCalculator:
    def __init__(self, fee_map: dict[str, AssetFeeConfig]):
        self._fees = fee_map

    @classmethod
    def from_config(cls, config: FeesConfig) -> "FeeCalculator":
        return cls(dict(config.assets))

    def calculate(
        self,
        market: str,
        side: OrderSide,
        trade_value: float,
        quantity: int,
    ) -> dict[str, float]:
        fee_cfg = self._fees.get(market)
        if fee_cfg is None:
            raise ValueError(f"Unknown market: {market}")

        commission = max(trade_value * fee_cfg.commission_rate, fee_cfg.min_commission) if trade_value > 0 else 0.0

        stamp_duty = 0.0
        side_check = fee_cfg.stamp_duty_side
        if side_check == "both" or (side_check == "sell" and side == OrderSide.SELL):
            stamp_duty = trade_value * fee_cfg.stamp_duty

        transfer_fee = trade_value * (fee_cfg.transfer_fee or 0.0)
        regulatory_fee = trade_value * (fee_cfg.regulatory_fee or 0.0)
        settlement_fee = trade_value * (fee_cfg.settlement_fee or 0.0)

        total = commission + stamp_duty + transfer_fee + regulatory_fee + settlement_fee

        return {
            "commission": round(commission, 4),
            "stamp_duty": round(stamp_duty, 4),
            "transfer_fee": round(transfer_fee, 4),
            "regulatory_fee": round(regulatory_fee, 4),
            "settlement_fee": round(settlement_fee, 4),
            "total": round(total, 4),
        }
