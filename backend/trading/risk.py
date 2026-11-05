"""Risk Manager: position sizing, SL/TP, R:R, daily/monthly loss limits, over-risk warnings."""
from __future__ import annotations


def position_size(balance: float, risk_pct: float, entry: float, stop_loss: float,
                  contract_size: float = 1.0) -> dict:
    risk_amount = balance * risk_pct / 100
    per_unit = abs(entry - stop_loss) * contract_size
    if per_unit <= 0:
        raise ValueError("Entry va Stop Loss bir xil bo'lishi mumkin emas")
    qty = risk_amount / per_unit
    return {"risk_amount": round(risk_amount, 2), "qty": round(qty, 6), "notional": round(qty * entry, 2),
            "risk_per_unit": round(per_unit, 6)}


def sl_tp_from_atr(entry: float, atr: float, side: str, sl_mult: float = 1.5, rr: float = 2.0) -> dict:
    d = atr * sl_mult
    if side == "buy":
        sl, tp = entry - d, entry + d * rr
    else:
        sl, tp = entry + d, entry - d * rr
    return {"stop_loss": round(sl, 6), "take_profit": round(tp, 6), "rr": rr}


def risk_reward(entry: float, stop_loss: float, take_profit: float) -> float:
    risk = abs(entry - stop_loss)
    return round(abs(take_profit - entry) / risk, 2) if risk else 0.0


def evaluate_plan(plan: dict, balance: float, limits: dict, day_pnl_pct: float, open_positions: int = 0) -> dict:
    """Returns warnings/blocks for a proposed trade."""
    warnings, blocks = [], []
    entry, sl, tp = plan["entry"], plan.get("stop_loss"), plan.get("take_profit")
    side = plan["side"]
    if sl is None:
        blocks.append("Stop Loss belgilanmagan — ROBIN SL'siz savdoga ruxsat bermaydi")
    else:
        if side == "buy" and sl >= entry or side == "sell" and sl <= entry:
            blocks.append("Stop Loss noto'g'ri tomonda")
    if tp is not None and sl is not None:
        rr = risk_reward(entry, sl, tp)
        plan["rr"] = rr
        if rr < 1:
            warnings.append(f"R:R = {rr} — 1 dan kichik, salbiy kutilma xavfi")
        elif rr < 1.5:
            warnings.append(f"R:R = {rr} — past")
    notional = plan["qty"] * entry
    pos_pct = notional / balance * 100 if balance else 100
    if pos_pct > limits["max_position_pct"] * (plan.get("leverage", 1) or 1):
        blocks.append(f"Pozitsiya hajmi {pos_pct:.1f}% — limit {limits['max_position_pct']}%")
    if sl is not None:
        risk_pct = abs(entry - sl) * plan["qty"] / balance * 100 if balance else 100
        plan["risk_pct"] = round(risk_pct, 3)
        if risk_pct > limits["max_risk_per_trade_pct"]:
            blocks.append(f"Bitta savdo riski {risk_pct:.2f}% — limit {limits['max_risk_per_trade_pct']}%")
    if day_pnl_pct <= -limits["max_daily_loss_pct"]:
        blocks.append(f"Kunlik zarar limiti ({limits['max_daily_loss_pct']}%) yetdi — bugun savdo to'xtatildi")
    if open_positions >= 5:
        warnings.append("5 tadan ortiq ochiq pozitsiya — ortiqcha risk (overtrading)")
    return {"ok": not blocks, "warnings": warnings, "blocks": blocks, "plan": plan}
