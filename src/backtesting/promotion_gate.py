from __future__ import annotations

from typing import Any


def build_promotion_gate_summary(
    *,
    walk_forward_summary: dict[str, Any],
    risk_budget_summary: dict[str, Any] | None = None,
    exposure_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blockers = [str(item) for item in list(walk_forward_summary.get("rollout_blockers") or []) if str(item).strip()]
    risk_payload = dict(risk_budget_summary or {})
    exposure_payload = dict(exposure_summary or {})
    suppressed = dict(risk_payload.get("suppressed_position_summary") or {})

    if str(risk_payload.get("mode") or "off").strip().lower() == "enforce":
        zero_budget_count = int(suppressed.get("zero_budget_count") or 0)
        reduced_budget_count = int(suppressed.get("reduced_budget_count") or 0)
        if zero_budget_count > 0 or reduced_budget_count >= 3:
            blockers.append("risk_budget_suppression_exceeded")

    max_projected = float(exposure_payload.get("max_projected_theme_exposure") or 0.0)
    max_incremental = float(exposure_payload.get("max_incremental_theme_exposure") or 0.0)
    if max_projected >= 0.35 or max_incremental >= 0.12:
        blockers.append("theme_exposure_cap_breach")

    deduped_blockers = list(dict.fromkeys(blockers))
    return {
        "promotion_ready": not deduped_blockers,
        "promotion_blockers": deduped_blockers,
    }
