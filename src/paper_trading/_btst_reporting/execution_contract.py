"""Shared BTST execution-contract helpers for follow-up reporting cards."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.paper_trading.btst_decision_enrichment import (
    attach_execution_semantics,
    build_decision_card,
    build_premarket_control_tower,
    build_report_mode,
    build_veto_owner,
    enrich_btst_row,
)
from src.paper_trading.btst_reporting_utils import (
    _load_json,
    _normalize_trade_date,
)


def _resolve_existing_json_path(raw_path: Any, report_dir: Path | None) -> Path | None:
    if not raw_path or isinstance(raw_path, dict):
        return None
    candidate = Path(str(raw_path)).expanduser()
    candidates = [candidate]
    if report_dir is not None and not candidate.is_absolute():
        candidates.append(report_dir / candidate)
    for item in candidates:
        if item.exists():
            return item.resolve()
    return None


def resolve_selection_snapshot(brief: dict[str, Any]) -> dict[str, Any]:
    selection_snapshot = brief.get("selection_snapshot")
    if isinstance(selection_snapshot, dict) and selection_snapshot:
        return dict(selection_snapshot)

    source_paths = dict(brief.get("source_paths") or {})
    report_dir_raw = brief.get("report_dir") or source_paths.get("report_dir")
    report_dir = Path(str(report_dir_raw)).expanduser().resolve() if report_dir_raw else None
    normalized_trade_date = (
        _normalize_trade_date(str(brief.get("trade_date") or ""))
        if brief.get("trade_date")
        else None
    )

    candidate_paths: list[Any] = [
        brief.get("snapshot_path"),
        source_paths.get("snapshot_path"),
    ]
    if report_dir is not None and normalized_trade_date:
        candidate_paths.append(
            report_dir / "selection_artifacts" / normalized_trade_date / "selection_snapshot.json"
        )
        candidate_paths.append(
            report_dir / "selection_artifacts" / normalized_trade_date.replace("-", "") / "selection_snapshot.json"
        )

    for raw_path in candidate_paths:
        path = _resolve_existing_json_path(raw_path, report_dir)
        if path is None:
            continue
        try:
            return dict(_load_json(path))
        except (OSError, ValueError, TypeError):
            continue
    return {}


def build_brief_execution_contract(
    *,
    brief: dict[str, Any],
    selected_entries: list[dict[str, Any]],
    early_runner_status: str = "unavailable",
) -> dict[str, Any]:
    control_selected = [
        enrich_btst_row(entry, role="formal_selected", early_runner_status=early_runner_status)
        for entry in selected_entries
    ]
    decision_card = build_decision_card(
        selected_rows=control_selected,
        early_runner_status=early_runner_status,
        signal_date=str(brief.get("trade_date") or ""),
        next_trade_date=str(brief.get("next_trade_date") or ""),
    )
    if control_selected and str(decision_card.get("trade_bias") or "") in {
        "skip",
        "no_trade",
    }:
        primary_selected = control_selected[0]
        decision_card = {
            **decision_card,
            "trade_bias": "confirmation_only",
            "primary_ticker": primary_selected.get("ticker"),
            "evidence_grade": primary_selected.get("evidence_grade") or "C",
            "data_quality": primary_selected.get("data_quality") or "insufficient",
            "risk_posture": "reduced",
        }

    selection_snapshot = resolve_selection_snapshot(brief)
    control_tower = build_premarket_control_tower(decision_card, selection_snapshot)
    report_mode = build_report_mode(control_tower)
    veto_owner = build_veto_owner(control_tower)
    control_tower = {
        **control_tower,
        "report_mode": report_mode,
        "veto_owner": veto_owner,
    }

    primary_semantic_action: dict[str, Any] = {}
    if control_selected:
        primary_ticker = str(decision_card.get("primary_ticker") or "").strip()
        primary_row = next(
            (
                row
                for row in control_selected
                if str(row.get("ticker") or "").strip() == primary_ticker
            ),
            control_selected[0],
        )
        primary_row = {
            **primary_row,
            "trade_bias": decision_card.get("trade_bias") or primary_row.get("trade_bias"),
            "risk_posture": decision_card.get("risk_posture") or primary_row.get("risk_posture"),
        }
        primary_semantic_action = attach_execution_semantics(
            primary_row,
            report_mode=report_mode,
            control_tower=control_tower,
            veto_owner=veto_owner,
        )

    execution_contract = {
        "report_mode": report_mode,
        "raw_trade_bias": control_tower.get("raw_trade_bias"),
        "effective_trade_bias": control_tower.get("effective_trade_bias"),
        "release_authority": primary_semantic_action.get("release_authority")
        or "none",
        "reason_codes": list(control_tower.get("reason_codes") or []),
    }
    if primary_semantic_action:
        execution_contract["execution_state"] = primary_semantic_action.get(
            "execution_state"
        )
        execution_contract["max_allowed_state_today"] = primary_semantic_action.get(
            "max_allowed_state_today"
        )

    return {
        "selection_snapshot": selection_snapshot,
        "control_tower": control_tower,
        "primary_semantic_action": primary_semantic_action,
        "execution_contract": execution_contract,
    }