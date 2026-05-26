from __future__ import annotations

from collections.abc import Collection
from typing import Any


def _safe_float(value: Any) -> float | None:
    """Return a float when parsing succeeds, otherwise ``None``."""
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any, default: float = 0.0) -> float:
    """Convert mixed inputs into float while preserving a caller-provided default."""
    parsed = _safe_float(value)
    return default if parsed is None else float(parsed)


def resolve_gate_action(gate: str, *, tradeable_gates: Collection[str]) -> str:
    """Map the regime gate into the current research-or-tradeable action."""
    return "tradeable" if str(gate or "") in set(tradeable_gates) else "research_only"


def derive_entry_status(
    row: dict[str, Any],
    *,
    gate_action: str,
    max_open_gap: float,
    confirm_score_min: float,
) -> str:
    """Classify the current row into the existing early-runner entry status contract."""
    if gate_action == "research_only":
        return "research_only"
    if _as_float(row.get("next_open_return"), 0.0) > max_open_gap:
        return "abandoned_gap"
    if _as_float(row.get("gap_to_limit"), 1.0) <= 0.01:
        return "unfilled"
    if _as_float(row.get("confirm_score"), 0.0) >= confirm_score_min:
        return "filled"
    return "not_confirmed"


def derive_failure_reason(row: dict[str, Any], *, entry_status: str) -> str:
    """Return the existing failure-reason labels used by the artifact."""
    if entry_status == "abandoned_gap":
        return "gap_trap"
    if entry_status == "unfilled":
        return "liquidity_unfilled"
    if _as_float(row.get("ret_5d"), 0.0) > 0.25 or _as_float(row.get("ret_10d"), 0.0) > 0.50:
        return "overheated_entry"
    if _as_float(row.get("next_high_return"), 0.0) > 0.02 and _as_float(row.get("next_close_return"), 0.0) < 0.0:
        return "fake_breakout"
    if _as_float(row.get("volume_expansion_quality"), 0.0) > 0.80 and _as_float(row.get("next_open_to_close_return"), 0.0) < 0.0:
        return "volume_exhaustion"
    if _as_float(row.get("sector_resonance"), 0.0) < 0.28:
        return "theme_collapse"
    if str(row.get("btst_regime_gate") or "") == "halt":
        return "btst_regime_halt"
    return "unknown"


def select_confirmed_entries(rows: list[dict[str, Any]], *, confirm_score_min: float) -> list[dict[str, Any]]:
    """Return the subset that currently qualifies as confirmed early-runner entries."""
    return [row for row in rows if row.get("entry_status") == "filled" and _as_float(row.get("confirm_score"), 0.0) >= confirm_score_min]


def build_runtime_supplemental_entry(row: dict[str, Any]) -> dict[str, Any]:
    """Translate one confirmed early-runner row into a short-trade supplemental entry."""
    normalized = dict(row or {})
    theme_label = str(normalized.get("hot_theme_board") or normalized.get("theme_name") or normalized.get("industry") or "").strip()
    reason_codes = [
        "early_runner_confirmed",
        "early_runner_runtime_candidate",
    ]
    if theme_label:
        reason_codes.append("theme_radar_pass")
    if _as_float(normalized.get("confirm_score"), 0.0) >= 0.60:
        reason_codes.append("intraday_confirm_pass")
    return {
        "ticker": str(normalized.get("ticker") or "").strip(),
        "decision": "early_runner_promoted",
        "reason": "early_runner_confirmed",
        "reasons": ["early_runner_confirmed", "short_trade_runtime_candidate"],
        "candidate_source": "early_runner_runtime_adapter",
        "upstream_candidate_source": str(normalized.get("candidate_source") or "unknown"),
        "candidate_reason_codes": reason_codes,
        "score_b": round(_as_float(normalized.get("pre_score"), _as_float(normalized.get("score_target"), 0.0)), 4),
        "score_final": round(_as_float(normalized.get("confirm_score"), 0.0), 4),
        "quality_score": round(max(_as_float(normalized.get("pre_score"), 0.0), _as_float(normalized.get("confirm_score"), 0.0)), 4),
        "preferred_entry_mode": str(normalized.get("preferred_entry_mode") or "reconfirm_on_open"),
        "historical_prior": dict(normalized.get("historical_prior") or {}),
        "market_state": dict(normalized.get("market_state") or {}),
        "projected_theme_exposure": _as_float(normalized.get("projected_theme_exposure"), 0.0),
        "metrics": {
            "trend_acceleration": _as_float(normalized.get("trend_acceleration"), 0.0),
            "breakout_freshness": _as_float(normalized.get("breakout_freshness"), 0.0),
            "volume_expansion_quality": _as_float(normalized.get("volume_expansion_quality"), 0.0),
            "close_strength": _as_float(normalized.get("close_strength"), 0.0),
            "sector_resonance": _as_float(normalized.get("sector_resonance"), 0.0),
            "catalyst_freshness": _as_float(normalized.get("catalyst_freshness"), 0.0),
            "theme_breadth_score": _as_float(normalized.get("theme_breadth_score"), 0.0),
            "confirm_score": _as_float(normalized.get("confirm_score"), 0.0),
        },
        "short_trade_boundary_metrics": {
            "candidate_score": round(_as_float(normalized.get("confirm_score"), 0.0), 4),
            "gate_status": {
                "btst_regime_gate": str(normalized.get("btst_regime_gate") or ""),
                "gate_action": str(normalized.get("gate_action") or ""),
            },
            "blockers": list(normalized.get("runtime_blockers") or []),
        },
        "theme_name": theme_label,
        "theme_category": str(normalized.get("theme_category") or ""),
        "is_new_theme": bool(normalized.get("is_new_theme")),
    }


def build_runtime_supplemental_entries(
    analysis: dict[str, Any],
    *,
    trade_date: str,
    require_tradeable_gate: bool = True,
) -> list[dict[str, Any]]:
    """Build runtime-ready supplemental entries from the latest early-runner analysis artifact."""
    daily_boards = [dict(board or {}) for board in list(dict(analysis or {}).get("daily_boards") or [])]
    board = next((dict(item) for item in daily_boards if str(item.get("trade_date") or "") == str(trade_date or "")), {})
    if not board:
        return []
    if require_tradeable_gate and str(board.get("gate_action") or "") != "tradeable":
        return []
    confirmed_entries = [dict(entry or {}) for entry in list(board.get("confirmed_entries") or [])]
    return [build_runtime_supplemental_entry(row) for row in confirmed_entries if str(dict(row or {}).get("ticker") or "").strip()]
