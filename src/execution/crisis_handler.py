"""极端场景处理器。"""

from __future__ import annotations


def evaluate_crisis_response(
    hs300_daily_return: float,
    limit_down_count: int,
    recent_total_volumes: list[float],
    drawdown_pct: float,
) -> dict:
    response = {
        "mode": "normal",
        "position_cap": 1.0,
        "pause_new_buys": False,
        "forced_reduce_ratio": 0.0,
        "recovery_cooldown_days": 0,
        "alerts": [],
    }

    if hs300_daily_return <= -0.05 or limit_down_count > 500:
        response.update({"mode": "defense", "position_cap": 0.3, "pause_new_buys": True})
        response["alerts"].append("crisis_defense_mode")

    if len(recent_total_volumes) >= 3 and all(volume < 4000 for volume in recent_total_volumes[-3:]):
        response.update({"mode": "shrink", "position_cap": min(response["position_cap"], 0.5), "pause_new_buys": True})
        response["alerts"].append("low_volume_shrink")

    if drawdown_pct <= -0.10:
        response["pause_new_buys"] = True
        response["alerts"].append("drawdown_warning")

    if drawdown_pct <= -0.15:
        response.update({"mode": "recovery", "forced_reduce_ratio": 0.5, "recovery_cooldown_days": 5, "pause_new_buys": True})
        response["alerts"].append("drawdown_forced_reduce")

    return response
