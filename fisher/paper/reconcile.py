"""G4 沙盒对账（模拟交易日终对账）。

将"成交流水"重新演算出现金与持仓，与 PaperEngine 报告的账户/持仓比对，
任何不一致即视为差异并告警。即便正确引擎下差异应为 0，该模块用于
实时检测记账漂移、重复成交、丢失成交等异常（为未来实盘对账铺路）。
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Discrepancy:
    field: str
    expected: float
    reported: float
    detail: str = ""


def reconcile(
    fills: list[dict],
    reported_cash: float,
    reported_positions: dict[str, dict],
    initial_cash: float,
    tol: float = 1e-6,
) -> list[Discrepancy]:
    """基于成交流水重算现金/持仓，与报告值比对。

    fills: list of {ticker, side('buy'/'sell'), quantity, price, commission?}
    reported_positions: {ticker: {quantity, market_value?}}
    """
    cash = float(initial_cash)
    qty: dict[str, float] = {}
    for f in fills:
        notional = f["price"] * f["quantity"]
        comm = float(f.get("commission", 0.0))
        side = f["side"]
        tk = f["ticker"]
        if side == "buy":
            cash -= notional + comm
            qty[tk] = qty.get(tk, 0.0) + f["quantity"]
        elif side == "sell":
            cash += notional - comm
            qty[tk] = qty.get(tk, 0.0) - f["quantity"]
        else:
            # 未知方向不参与重算，但记录异常
            pass

    disc: list[Discrepancy] = []
    if abs(cash - reported_cash) > tol:
        disc.append(Discrepancy("cash", cash, reported_cash, "现金对账不一致"))

    for tk, exp_q in qty.items():
        rep_q = reported_positions.get(tk, {}).get("quantity", 0.0)
        if abs(exp_q - rep_q) > tol:
            disc.append(Discrepancy(
                f"position.{tk}.quantity", exp_q, rep_q, "持仓数量对账不一致"))

    # 报告中有持仓但流水未涉及（残留/异常）
    for tk, p in reported_positions.items():
        if tk not in qty and abs(float(p.get("quantity", 0.0))) > tol:
            disc.append(Discrepancy(
                f"position.{tk}.quantity", 0.0,
                float(p.get("quantity", 0.0)), "流水未覆盖的残留持仓"))

    return disc


def daily_settle(
    account: dict,
    positions: dict[str, dict],
    fills: list[dict],
    initial_cash: float,
) -> dict:
    """日终结算步骤：快照账户/持仓并对账，返回 {snapshot, discrepancies}。"""
    snapshot = {
        "cash": account.get("available", account.get("capital", 0.0)),
        "positions": {tk: {"quantity": p.get("quantity", 0)} for tk, p in positions.items()},
    }
    disc = reconcile(fills, snapshot["cash"], snapshot["positions"], initial_cash)
    return {"snapshot": snapshot, "discrepancies": disc}
