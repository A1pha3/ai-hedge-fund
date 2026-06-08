"""极端场景处理器。"""

from __future__ import annotations

# Severity ordering (most severe wins).  When multiple triggers fire we pick
# the highest-severity mode and the strictest position cap.
_MODE_SEVERITY = {
    "normal": 0,
    "shrink": 1,
    "defense": 2,
    "recovery": 3,
}


def _pick_mode(current: str, candidate: str) -> str:
    """Return whichever mode is more severe."""
    if _MODE_SEVERITY.get(candidate, 0) > _MODE_SEVERITY.get(current, 0):
        return candidate
    return current


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

    triggered_modes: list[str] = []
    triggered_caps: list[float] = [1.0]

    if hs300_daily_return <= -0.05 or limit_down_count >= 500:
        triggered_modes.append("defense")
        triggered_caps.append(0.3)
        response["pause_new_buys"] = True
        response["alerts"].append("crisis_defense_mode")

    if len(recent_total_volumes) >= 3 and all(volume < 4000 for volume in recent_total_volumes[-3:]):
        triggered_modes.append("shrink")
        triggered_caps.append(0.5)
        response["pause_new_buys"] = True
        response["alerts"].append("low_volume_shrink")

    if drawdown_pct <= -0.10:
        response["pause_new_buys"] = True
        response["alerts"].append("drawdown_warning")

    if drawdown_pct <= -0.15:
        triggered_modes.append("recovery")
        triggered_caps.append(0.0)  # recovery is paired with forced_reduce_ratio
        response["forced_reduce_ratio"] = 0.5
        response["recovery_cooldown_days"] = 5
        response["pause_new_buys"] = True
        response["alerts"].append("drawdown_forced_reduce")

    # Apply severity ordering: most-severe mode wins, strictest cap wins.
    # R20.10 invariant: mode and cap are always consistent because each trigger
    # appends a mode whose severity is monotonically related to its cap strictness:
    #   shrink(severity=1, cap=0.5) < defense(severity=2, cap=0.3) < recovery(severity=3, cap=0.0)
    # Therefore picking the highest-severity mode and the minimum cap always agree.
    # When only a subset triggers (e.g. defense + shrink), severity picks defense
    # (2 > 1) and min() picks 0.3 (defense's cap) — consistent.
    chosen_mode = response["mode"]
    for mode in triggered_modes:
        chosen_mode = _pick_mode(chosen_mode, mode)
    response["mode"] = chosen_mode
    response["position_cap"] = min(triggered_caps)

    return response
