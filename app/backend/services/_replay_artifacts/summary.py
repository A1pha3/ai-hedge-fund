from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.backend.services.replay_artifact_service import ReplayArtifactService


class ReplaySummaryHelper:
    def __init__(self, service: ReplayArtifactService) -> None:
        self._service = service

    @property
    def _reports_root(self) -> Path:
        return self._service._reports_root

    def _read_json(self, path: Path) -> dict[str, Any]:
        return self._service._read_json(path)

    def _resolve_selection_artifact_root(self, report_dir: Path, session_summary: dict[str, Any]) -> Path | None:
        return self._service._resolve_selection_artifact_root(report_dir, session_summary)

    def _safe_average(self, values: list[float]) -> float | None:
        return self._service._safe_average(values)

    def derive_cache_benchmark_overview(self, session_summary: dict[str, Any]) -> dict[str, Any]:
        return self._derive_cache_benchmark_overview(session_summary)

    def derive_btst_followup_overview(self, session_summary: dict[str, Any]) -> dict[str, Any] | None:
        return self._derive_btst_followup_overview(session_summary)

    def derive_btst_control_tower_overview(self, report_dir: Path, *, resolve_contexts: bool = False) -> dict[str, Any] | None:
        return self._derive_btst_control_tower_overview(report_dir, resolve_contexts=resolve_contexts)

    def _resolve_cache_benchmark_summary(self, benchmark_payload: dict[str, Any]) -> dict[str, Any]:
        benchmark_summary = benchmark_payload.get("summary") if isinstance(benchmark_payload, dict) else {}
        return benchmark_summary if isinstance(benchmark_summary, dict) else {}

    def _build_cache_benchmark_status(self, benchmark_status: dict[str, Any], benchmark_payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "requested": bool(benchmark_status.get("requested") or benchmark_payload.get("requested") or False),
            "executed": bool(benchmark_status.get("executed") or benchmark_payload.get("executed") or False),
            "write_status": benchmark_status.get("write_status") or benchmark_payload.get("write_status"),
            "reason": benchmark_status.get("reason") or benchmark_payload.get("reason"),
        }

    def _build_cache_benchmark_metrics(self, benchmark_payload: dict[str, Any], benchmark_summary: dict[str, Any]) -> dict[str, Any]:
        return {
            "ticker": benchmark_payload.get("ticker"),
            "trade_date": benchmark_payload.get("trade_date"),
            "reuse_confirmed": benchmark_summary.get("reuse_confirmed"),
            "disk_hit_gain": benchmark_summary.get("disk_hit_gain"),
            "miss_reduction": benchmark_summary.get("miss_reduction"),
            "set_reduction": benchmark_summary.get("set_reduction"),
            "first_hit_rate": benchmark_summary.get("first_hit_rate"),
            "second_hit_rate": benchmark_summary.get("second_hit_rate"),
        }

    def _build_cache_benchmark_artifacts(self, artifacts: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "data_cache_benchmark_json": artifacts.get("data_cache_benchmark_json"),
                "data_cache_benchmark_markdown": artifacts.get("data_cache_benchmark_markdown"),
                "data_cache_benchmark_appended_report": artifacts.get("data_cache_benchmark_appended_report"),
            }.items()
            if value
        }

    def _derive_cache_benchmark_overview(self, session_summary: dict[str, Any]) -> dict[str, Any]:
        artifacts = session_summary.get("artifacts") or {}
        benchmark_payload = session_summary.get("data_cache_benchmark") or {}
        benchmark_status = session_summary.get("data_cache_benchmark_status") or {}
        benchmark_summary = self._resolve_cache_benchmark_summary(benchmark_payload)

        overview = self._build_cache_benchmark_status(benchmark_status, benchmark_payload)
        overview.update(self._build_cache_benchmark_metrics(benchmark_payload, benchmark_summary))
        overview["artifacts"] = self._build_cache_benchmark_artifacts(artifacts)
        return overview

    def _resolve_btst_followup_artifact_paths(self, session_summary: dict[str, Any]) -> dict[str, Any]:
        followup = session_summary.get("btst_followup") or {}
        artifacts = session_summary.get("artifacts") or {}
        return {
            "brief_json": followup.get("brief_json") or artifacts.get("btst_next_day_trade_brief_json"),
            "brief_markdown": followup.get("brief_markdown") or artifacts.get("btst_next_day_trade_brief_markdown"),
            "execution_card_json": followup.get("execution_card_json") or artifacts.get("btst_premarket_execution_card_json"),
            "execution_card_markdown": followup.get("execution_card_markdown") or artifacts.get("btst_premarket_execution_card_markdown"),
        }

    def _load_btst_followup_brief_payload(self, brief_json_path_value: Any, followup: dict[str, Any]) -> dict[str, Any]:
        embedded_payload = followup.get("brief_payload")
        if isinstance(embedded_payload, dict):
            return dict(embedded_payload)
        if not brief_json_path_value:
            return {}

        brief_json_path = Path(str(brief_json_path_value))
        if not brief_json_path.exists():
            return {}

        try:
            return self._read_json(brief_json_path)
        except (OSError, json.JSONDecodeError, FileNotFoundError):
            return {}

    def _filter_btst_followup_dict_entries(self, values: Any) -> list[dict[str, Any]]:
        return [item for item in (values or []) if isinstance(item, dict)]

    def _extract_btst_followup_entries(self, brief_payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        return {
            "selected_entries": self._filter_btst_followup_dict_entries(brief_payload.get("selected_entries")),
            "near_miss_entries": self._filter_btst_followup_dict_entries(brief_payload.get("near_miss_entries")),
            "excluded_entries": self._filter_btst_followup_dict_entries(brief_payload.get("excluded_research_entries")),
        }

    def _build_btst_followup_artifacts(self, artifact_paths: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in artifact_paths.items() if value}

    def _resolve_btst_followup_primary_entry(
        self,
        brief_payload: dict[str, Any],
        selected_entries: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        primary_entry = brief_payload.get("primary_entry")
        if isinstance(primary_entry, dict):
            return primary_entry
        return selected_entries[0] if selected_entries else None

    def _normalize_btst_followup_tickers(self, entries: list[dict[str, Any]]) -> list[str]:
        return [str(item.get("ticker")) for item in entries if item.get("ticker")]

    def _summarize_btst_followup_entries(self, entries: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        selected_entries = entries["selected_entries"]
        near_miss_entries = entries["near_miss_entries"]
        excluded_entries = entries["excluded_entries"]
        return {
            "watchlist_tickers": self._normalize_btst_followup_tickers(near_miss_entries),
            "excluded_research_tickers": self._normalize_btst_followup_tickers(excluded_entries),
            "selected_count": len(selected_entries),
            "watchlist_count": len(near_miss_entries),
            "excluded_research_count": len(excluded_entries),
        }

    def _build_btst_followup_overview(
        self,
        *,
        followup: dict[str, Any],
        session_summary: dict[str, Any],
        brief_payload: dict[str, Any],
        entries: dict[str, list[dict[str, Any]]],
        primary_entry: dict[str, Any] | None,
        artifact_paths: dict[str, Any],
    ) -> dict[str, Any]:
        overview = {
            "available": True,
            "trade_date": followup.get("trade_date") or brief_payload.get("trade_date"),
            "next_trade_date": followup.get("next_trade_date") or brief_payload.get("next_trade_date"),
            "selection_target": brief_payload.get("selection_target") or (session_summary.get("plan_generation") or {}).get("selection_target"),
            "primary_entry_ticker": primary_entry.get("ticker") if isinstance(primary_entry, dict) else None,
            "artifacts": self._build_btst_followup_artifacts(artifact_paths),
        }
        overview.update(self._summarize_btst_followup_entries(entries))
        return overview

    def _derive_btst_followup_overview(self, session_summary: dict[str, Any]) -> dict[str, Any] | None:
        followup = session_summary.get("btst_followup") or {}
        artifact_paths = self._resolve_btst_followup_artifact_paths(session_summary)
        if not any(artifact_paths.values()):
            return None

        brief_payload = self._load_btst_followup_brief_payload(artifact_paths["brief_json"], followup)
        entries = self._extract_btst_followup_entries(brief_payload)
        primary_entry = self._resolve_btst_followup_primary_entry(brief_payload, entries["selected_entries"])
        return self._build_btst_followup_overview(
            followup=followup,
            session_summary=session_summary,
            brief_payload=brief_payload,
            entries=entries,
            primary_entry=primary_entry,
            artifact_paths=artifact_paths,
        )

    def _normalize_btst_reference(self, payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(payload, dict) or not payload:
            return None

        report_dir_value = payload.get("report_dir") or payload.get("report_dir_abs")
        report_name = Path(str(report_dir_value)).name if report_dir_value else None
        normalized = {
            "report_dir": report_dir_value,
            "report_name": report_name,
            "selection_target": payload.get("selection_target"),
            "trade_date": payload.get("trade_date"),
            "next_trade_date": payload.get("next_trade_date"),
        }
        if not any(normalized.values()):
            return None
        return normalized

    def _extract_btst_ticker(self, *values: Any) -> str | None:
        for value in values:
            if value is None:
                continue
            match = re.search(r"(?<!\d)(\d{6})(?!\d)", str(value))
            if match:
                return match.group(1)
        return None

    def _collect_snapshot_stock_symbols(self, payload: Any, symbols: set[str]) -> None:
        if isinstance(payload, dict):
            for key, value in payload.items():
                if isinstance(key, str) and re.fullmatch(r"\d{6}", key.strip()):
                    symbols.add(key.strip())
                self._collect_snapshot_stock_symbols(value, symbols)
            return

        if isinstance(payload, list):
            for item in payload:
                self._collect_snapshot_stock_symbols(item, symbols)
            return

        if isinstance(payload, str):
            normalized = payload.strip()
            if re.fullmatch(r"\d{6}", normalized):
                symbols.add(normalized)

    def _list_btst_context_report_dirs(self, *, preferred_report_names: list[str] | None = None) -> list[Path]:
        preferred = {name for name in (preferred_report_names or []) if name}
        return sorted(
            [summary_path.parent for summary_path in self._reports_root.glob("*/session_summary.json")],
            key=lambda path: (
                0 if path.name in preferred else 1,
                -path.stat().st_mtime_ns,
                path.name,
            ),
        )

    def _load_btst_context_source(
        self,
        candidate_report_dir: Path,
    ) -> tuple[dict[str, Any], Path, str | None] | None:
        session_summary_path = candidate_report_dir / "session_summary.json"
        try:
            session_summary = self._read_json(session_summary_path)
        except FileNotFoundError:
            return None

        artifact_root = self._resolve_selection_artifact_root(candidate_report_dir, session_summary)
        if artifact_root is None or not artifact_root.exists():
            return None

        selection_target = (session_summary.get("plan_generation") or {}).get("selection_target") or session_summary.get("selection_target")
        return session_summary, artifact_root, selection_target

    def _iter_btst_context_snapshot_days(self, artifact_root: Path) -> list[Path]:
        return sorted((path for path in artifact_root.iterdir() if path.is_dir()), key=lambda path: path.name, reverse=True)

    def _register_btst_snapshot_context(
        self,
        context_index: dict[str, dict[str, Any]],
        *,
        candidate_report_dir: Path,
        trade_date: str,
        snapshot: dict[str, Any],
        selection_target: str | None,
    ) -> None:
        snapshot_symbols: set[str] = set()
        self._collect_snapshot_stock_symbols(snapshot, snapshot_symbols)
        for symbol in snapshot_symbols:
            context_index.setdefault(
                symbol,
                {
                    "report_name": candidate_report_dir.name,
                    "trade_date": trade_date,
                    "symbol": symbol,
                    "selection_target": selection_target,
                },
            )

    def _build_btst_replay_context_index(self, *, preferred_report_names: list[str] | None = None) -> dict[str, dict[str, Any]]:
        context_index: dict[str, dict[str, Any]] = {}
        for candidate_report_dir in self._list_btst_context_report_dirs(preferred_report_names=preferred_report_names):
            context_source = self._load_btst_context_source(candidate_report_dir)
            if context_source is None:
                continue
            _session_summary, artifact_root, selection_target = context_source
            for day_dir in self._iter_btst_context_snapshot_days(artifact_root):
                snapshot_path = day_dir / "selection_snapshot.json"
                if not snapshot_path.exists():
                    continue

                snapshot = self._read_json(snapshot_path)
                self._register_btst_snapshot_context(
                    context_index,
                    candidate_report_dir=candidate_report_dir,
                    trade_date=day_dir.name,
                    snapshot=snapshot,
                    selection_target=selection_target,
                )

        return context_index

    def _format_btst_lane_evidence_value(self, value: Any) -> str:
        if isinstance(value, bool):
            return "yes" if value else "no"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return f"{value:.4f}".rstrip("0").rstrip(".")
        return str(value)

    def _summarize_btst_lane_evidence(self, evidence: dict[str, Any] | None) -> list[str]:
        if not isinstance(evidence, dict) or not evidence:
            return []

        label_map = {
            "target_case_count": "cases",
            "distinct_window_count": "windows",
            "missing_window_count": "missing windows",
            "next_close_positive_rate": "close+ rate",
            "next_close_return_mean": "close mean",
            "next_high_return_mean": "high mean",
            "threshold_only_candidate_count": "threshold-only",
            "same_rule_peer_ticker_count": "same-rule peers",
            "window_blocked_case_count": "blocked cases",
            "window_near_miss_rescuable_count": "rescuable",
            "freeze_verdict": "freeze",
            "transition_locality": "locality",
        }
        preferred_keys = [
            "target_case_count",
            "distinct_window_count",
            "missing_window_count",
            "next_close_positive_rate",
            "next_close_return_mean",
            "next_high_return_mean",
            "threshold_only_candidate_count",
            "same_rule_peer_ticker_count",
            "window_blocked_case_count",
            "window_near_miss_rescuable_count",
            "freeze_verdict",
            "transition_locality",
        ]

        highlights: list[str] = []
        for key in preferred_keys:
            if evidence.get(key) is None:
                continue
            highlights.append(f"{label_map.get(key, key)} {self._format_btst_lane_evidence_value(evidence[key])}")
            if len(highlights) >= 3:
                return highlights

        for key, value in evidence.items():
            if value is None:
                continue
            label = label_map.get(str(key), str(key).replace("_", " "))
            candidate = f"{label} {self._format_btst_lane_evidence_value(value)}"
            if candidate not in highlights:
                highlights.append(candidate)
            if len(highlights) >= 3:
                break

        return highlights

    def _load_btst_rollout_governance_payload(self, governance_synthesis_payload: dict[str, Any]) -> dict[str, Any]:
        source_reports = dict(governance_synthesis_payload.get("source_reports") or {})
        rollout_governance_path = source_reports.get("rollout_governance")
        if not rollout_governance_path:
            return {}
        rollout_governance_file = Path(rollout_governance_path)
        if not rollout_governance_file.exists():
            return {}
        return self._read_json(rollout_governance_file)

    def _extract_btst_governance_rows(self, rollout_governance_payload: dict[str, Any]) -> list[dict[str, Any]]:
        return [dict(row) for row in list(rollout_governance_payload.get("governance_rows") or []) if isinstance(row, dict)]

    def _build_btst_lane_matrix(self, governance_synthesis_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {str(row.get("ticker") or row.get("lane_id") or ""): dict(row) for row in list(governance_synthesis_payload.get("lane_matrix") or []) if isinstance(row, dict)}

    def _build_btst_rollout_lane_row(
        self,
        governance_row: dict[str, Any],
        *,
        lane_matrix: dict[str, dict[str, Any]],
        context_index: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        ticker = self._extract_btst_ticker(governance_row.get("ticker"))
        matrix_row = lane_matrix.get(str(governance_row.get("ticker") or ""), {})
        return {
            "lane_id": matrix_row.get("lane_id"),
            "ticker": governance_row.get("ticker"),
            "governance_tier": governance_row.get("governance_tier") or matrix_row.get("governance_tier"),
            "lane_status": governance_row.get("status") or matrix_row.get("lane_status"),
            "action_tier": matrix_row.get("action_tier"),
            "blocker": governance_row.get("blocker") or matrix_row.get("blocker"),
            "validation_verdict": matrix_row.get("validation_verdict"),
            "missing_window_count": matrix_row.get("missing_window_count"),
            "next_step": governance_row.get("next_step") or matrix_row.get("next_step"),
            "evidence_highlights": self._summarize_btst_lane_evidence(governance_row.get("evidence") or {}),
            "context_reference": context_index.get(ticker) if ticker else None,
        }

    def _derive_btst_rollout_lane_rows(
        self,
        governance_synthesis_payload: dict[str, Any],
        *,
        resolve_contexts: bool,
        preferred_report_names: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        rollout_governance_payload = self._load_btst_rollout_governance_payload(governance_synthesis_payload)
        governance_rows = self._extract_btst_governance_rows(rollout_governance_payload)
        if not governance_rows:
            return []

        lane_matrix = self._build_btst_lane_matrix(governance_synthesis_payload)
        context_index = self._build_btst_replay_context_index(preferred_report_names=preferred_report_names) if resolve_contexts else {}
        return [
            self._build_btst_rollout_lane_row(
                governance_row,
                lane_matrix=lane_matrix,
                context_index=context_index,
            )
            for governance_row in governance_rows
        ]

    def _btst_control_tower_paths(self) -> dict[str, Path]:
        return {
            "delta_json": self._reports_root / "btst_open_ready_delta_latest.json",
            "delta_markdown": self._reports_root / "btst_open_ready_delta_latest.md",
            "nightly_json": self._reports_root / "btst_nightly_control_tower_latest.json",
            "nightly_markdown": self._reports_root / "btst_nightly_control_tower_latest.md",
            "manifest_json": self._reports_root / "report_manifest_latest.json",
            "manifest_markdown": self._reports_root / "report_manifest_latest.md",
            "governance_synthesis_json": self._reports_root / "btst_governance_synthesis_latest.json",
        }

    def _build_btst_control_tower_preferred_report_names(
        self,
        report_dir: Path,
        current_reference: dict[str, Any] | None,
        previous_reference: dict[str, Any] | None,
    ) -> list[str]:
        return [
            str(item)
            for item in [
                report_dir.name,
                current_reference.get("report_name") if current_reference else None,
                previous_reference.get("report_name") if previous_reference else None,
            ]
            if item
        ]

    def _derive_btst_control_tower_next_actions(
        self,
        control_tower_snapshot: dict[str, Any],
        lane_context_by_ticker: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        next_actions: list[dict[str, Any]] = []
        for item in (control_tower_snapshot.get("next_actions") or [])[:3]:
            if not isinstance(item, dict):
                continue
            action_ticker = self._extract_btst_ticker(
                item.get("task_id"),
                item.get("title"),
                item.get("why_now"),
                item.get("next_step"),
            )
            next_actions.append(
                {
                    "task_id": item.get("task_id"),
                    "title": item.get("title"),
                    "why_now": item.get("why_now"),
                    "next_step": item.get("next_step"),
                    "source": item.get("source"),
                    "context_reference": lane_context_by_ticker.get(action_ticker) if action_ticker else None,
                }
            )
        return next_actions

    def _existing_btst_control_tower_path(self, path: Path) -> str | None:
        return str(path) if path.exists() else None

    def _resolve_btst_control_tower_source_artifact(
        self,
        source_paths: dict[str, Any],
        source_key: str,
        fallback_path: Path | None = None,
    ) -> Any:
        return source_paths.get(source_key) or (self._existing_btst_control_tower_path(fallback_path) if fallback_path else None)

    def _build_btst_control_tower_artifacts(
        self,
        *,
        paths: dict[str, Path],
        source_paths: dict[str, Any],
        governance_source_reports: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "open_ready_delta_json": self._existing_btst_control_tower_path(paths["delta_json"]),
                "open_ready_delta_markdown": self._existing_btst_control_tower_path(paths["delta_markdown"]),
                "nightly_control_tower_json": self._existing_btst_control_tower_path(paths["nightly_json"]),
                "nightly_control_tower_markdown": self._existing_btst_control_tower_path(paths["nightly_markdown"]),
                "governance_synthesis_json": self._existing_btst_control_tower_path(paths["governance_synthesis_json"]),
                "rollout_governance_json": governance_source_reports.get("rollout_governance"),
                "report_manifest_json": self._resolve_btst_control_tower_source_artifact(source_paths, "report_manifest_json", paths["manifest_json"]),
                "report_manifest_markdown": self._resolve_btst_control_tower_source_artifact(source_paths, "report_manifest_markdown", paths["manifest_markdown"]),
                "current_priority_board_json": self._resolve_btst_control_tower_source_artifact(source_paths, "current_priority_board_json"),
                "previous_priority_board_json": self._resolve_btst_control_tower_source_artifact(source_paths, "previous_priority_board_json"),
            }.items()
            if value
        }

    def _extract_btst_control_tower_recommendation(self, control_tower_snapshot: dict[str, Any]) -> Any:
        recommendation = control_tower_snapshot.get("recommendation")
        if recommendation:
            return recommendation
        return (control_tower_snapshot.get("synthesis") or {}).get("recommendation")

    def _derive_btst_control_tower_closed_frontiers(self, control_tower_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        closed_frontiers: list[dict[str, Any]] = []
        for item in list(control_tower_snapshot.get("closed_frontiers") or []):
            if not isinstance(item, dict):
                continue
            closed_frontiers.append(
                {
                    "frontier_id": item.get("frontier_id"),
                    "status": item.get("status"),
                    "headline": item.get("headline"),
                    "best_variant_name": item.get("best_variant_name"),
                    "passing_variant_count": item.get("passing_variant_count"),
                    "best_variant_released_tickers": [str(value) for value in list(item.get("best_variant_released_tickers") or []) if value],
                    "best_variant_focus_released_tickers": [str(value) for value in list(item.get("best_variant_focus_released_tickers") or []) if value],
                }
            )
        return closed_frontiers

    def _load_btst_control_tower_payloads(self, paths: dict[str, Path]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        delta_payload = self._read_json(paths["delta_json"]) if paths["delta_json"].exists() else {}
        nightly_payload = self._read_json(paths["nightly_json"]) if paths["nightly_json"].exists() else {}
        governance_synthesis_payload = self._read_json(paths["governance_synthesis_json"]) if paths["governance_synthesis_json"].exists() else {}
        return delta_payload, nightly_payload, governance_synthesis_payload

    def _derive_btst_control_tower_references(
        self,
        delta_payload: dict[str, Any],
        nightly_payload: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        current_reference = self._normalize_btst_reference(delta_payload.get("current_reference")) or self._normalize_btst_reference(nightly_payload.get("latest_btst_run"))
        previous_reference = self._normalize_btst_reference(delta_payload.get("previous_reference"))
        return current_reference, previous_reference

    def _derive_btst_control_tower_rollout_bundle(
        self,
        report_dir: Path,
        *,
        current_reference: dict[str, Any] | None,
        previous_reference: dict[str, Any] | None,
        governance_synthesis_payload: dict[str, Any],
        resolve_contexts: bool,
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        preferred_report_names = self._build_btst_control_tower_preferred_report_names(report_dir, current_reference, previous_reference)
        rollout_lane_rows = self._derive_btst_rollout_lane_rows(
            governance_synthesis_payload,
            resolve_contexts=resolve_contexts,
            preferred_report_names=preferred_report_names,
        )
        lane_context_by_ticker = {str(row.get("ticker")): dict(row.get("context_reference") or {}) for row in rollout_lane_rows if row.get("ticker") and row.get("context_reference")}
        return rollout_lane_rows, lane_context_by_ticker

    def _build_btst_control_tower_overview(
        self,
        report_dir: Path,
        *,
        delta_payload: dict[str, Any],
        nightly_payload: dict[str, Any],
        control_tower_snapshot: dict[str, Any],
        validation: dict[str, Any],
        current_reference: dict[str, Any] | None,
        previous_reference: dict[str, Any] | None,
        priority_delta: dict[str, Any],
        governance_delta: dict[str, Any],
        replay_delta: dict[str, Any],
        recommendation: Any,
        closed_frontiers: list[dict[str, Any]],
        rollout_lane_rows: list[dict[str, Any]],
        next_actions: list[dict[str, Any]],
        artifacts: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "available": True,
            "generated_at": delta_payload.get("generated_at") or nightly_payload.get("generated_at"),
            "comparison_basis": delta_payload.get("comparison_basis"),
            "overall_delta_verdict": delta_payload.get("overall_delta_verdict"),
            "operator_focus": [str(item) for item in (delta_payload.get("operator_focus") or []) if item],
            "current_reference": current_reference,
            "previous_reference": previous_reference,
            "selected_report_matches_current_reference": bool(current_reference and current_reference.get("report_name") == report_dir.name),
            "priority_has_changes": bool(priority_delta.get("has_changes")),
            "governance_has_changes": bool(governance_delta.get("has_changes")),
            "replay_has_changes": bool(replay_delta.get("has_changes")),
            "governance_overall_verdict": governance_delta.get("current_overall_verdict") or validation.get("overall_verdict"),
            "recommendation": recommendation,
            "waiting_lane_count": control_tower_snapshot.get("waiting_lane_count"),
            "ready_lane_count": control_tower_snapshot.get("ready_lane_count"),
            "lane_status_counts": dict(control_tower_snapshot.get("lane_status_counts") or {}),
            "refresh_status": {str(key): str(value) for key, value in (nightly_payload.get("refresh_status") or {}).items()},
            "closed_frontiers": closed_frontiers,
            "rollout_lane_rows": rollout_lane_rows,
            "next_actions": next_actions,
            "artifacts": artifacts,
        }

    def _derive_btst_control_tower_overview(self, report_dir: Path, *, resolve_contexts: bool = False) -> dict[str, Any] | None:
        paths = self._btst_control_tower_paths()
        if not any(paths[key].exists() for key in ("delta_json", "delta_markdown", "nightly_json", "nightly_markdown")):
            return None

        delta_payload, nightly_payload, governance_synthesis_payload = self._load_btst_control_tower_payloads(paths)
        control_tower_snapshot = nightly_payload.get("control_tower_snapshot") or {}
        validation = control_tower_snapshot.get("validation") or {}
        source_paths = delta_payload.get("source_paths") or {}
        governance_source_reports = dict(governance_synthesis_payload.get("source_reports") or {})

        current_reference, previous_reference = self._derive_btst_control_tower_references(delta_payload, nightly_payload)
        rollout_lane_rows, lane_context_by_ticker = self._derive_btst_control_tower_rollout_bundle(
            report_dir,
            current_reference=current_reference,
            previous_reference=previous_reference,
            governance_synthesis_payload=governance_synthesis_payload,
            resolve_contexts=resolve_contexts,
        )
        next_actions = self._derive_btst_control_tower_next_actions(control_tower_snapshot, lane_context_by_ticker)
        artifacts = self._build_btst_control_tower_artifacts(
            paths=paths,
            source_paths=source_paths,
            governance_source_reports=governance_source_reports,
        )
        priority_delta = delta_payload.get("priority_delta") or {}
        governance_delta = delta_payload.get("governance_delta") or {}
        replay_delta = delta_payload.get("replay_delta") or {}
        recommendation = self._extract_btst_control_tower_recommendation(control_tower_snapshot)
        closed_frontiers = self._derive_btst_control_tower_closed_frontiers(control_tower_snapshot)

        return self._build_btst_control_tower_overview(
            report_dir,
            delta_payload=delta_payload,
            nightly_payload=nightly_payload,
            control_tower_snapshot=control_tower_snapshot,
            validation=validation,
            current_reference=current_reference,
            previous_reference=previous_reference,
            priority_delta=priority_delta,
            governance_delta=governance_delta,
            replay_delta=replay_delta,
            recommendation=recommendation,
            closed_frontiers=closed_frontiers,
            rollout_lane_rows=rollout_lane_rows,
            next_actions=next_actions,
            artifacts=artifacts,
        )
