from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from typing import Any, TYPE_CHECKING

from src.research.feedback import (
    append_research_feedback,
    read_research_feedback,
    summarize_research_feedback,
    summarize_research_feedback_directory,
)
from src.research.models import (
    RESEARCH_FEEDBACK_ALLOWED_REVIEW_STATUS,
    RESEARCH_FEEDBACK_ALLOWED_TAGS,
    ResearchFeedbackRecord,
)

if TYPE_CHECKING:
    from app.backend.services.replay_artifact_service import ReplayArtifactService


class ReplaySelectionFeedbackHelper:
    def __init__(self, service: ReplayArtifactService) -> None:
        self._service = service

    def get_selection_artifact_day(self, report_name: str, trade_date: str) -> dict[str, Any]:
        service = self._service
        report_dir = service._get_report_dir(report_name)
        session_summary = service._read_json(report_dir / "session_summary.json")
        artifact_root = service._resolve_selection_artifact_root(report_dir, session_summary)
        if artifact_root is None:
            raise FileNotFoundError(f"Selection artifact root not found for report: {report_name}")

        day_dir = artifact_root / trade_date
        if not day_dir.is_dir():
            raise FileNotFoundError(f"Selection artifact day not found: {report_name}/{trade_date}")

        snapshot_path = day_dir / "selection_snapshot.json"
        review_path = day_dir / "selection_review.md"
        feedback_path = day_dir / "research_feedback.jsonl"
        snapshot = service._read_json(snapshot_path)
        feedback_records = read_research_feedback(file_path=feedback_path, skip_invalid=False)
        feedback_records = sorted(
            feedback_records,
            key=lambda record: record.created_at,
            reverse=True,
        )
        service._sync_feedback_ledger_for_day(
            report_name=report_dir.name,
            trade_date=trade_date,
            feedback_path=feedback_path,
            records=feedback_records,
        )
        feedback_summary = summarize_research_feedback(records=feedback_records)

        selected = snapshot.get("selected") or []
        blocker_counts: Counter[str] = Counter()
        for candidate in selected:
            if not isinstance(candidate, dict):
                continue
            execution_bridge = candidate.get("execution_bridge") or {}
            block_reason = execution_bridge.get("block_reason")
            if block_reason:
                blocker_counts[str(block_reason)] += 1

        return {
            "report_dir": report_dir.name,
            "trade_date": trade_date,
            "paths": {
                "snapshot_path": str(snapshot_path),
                "review_path": str(review_path),
                "feedback_path": str(feedback_path),
            },
            "snapshot": snapshot,
            "review_markdown": service._read_text(review_path),
            "feedback_record_count": len(feedback_records),
            "feedback_records": [record.model_dump(mode="json") for record in feedback_records],
            "feedback_summary": feedback_summary.model_dump(mode="json"),
            "feedback_options": {
                "allowed_tags": list(RESEARCH_FEEDBACK_ALLOWED_TAGS),
                "allowed_review_statuses": list(RESEARCH_FEEDBACK_ALLOWED_REVIEW_STATUS),
            },
            "blocker_counts": service._counter_to_list(blocker_counts),
        }

    def append_selection_artifact_feedback(
        self,
        *,
        report_name: str,
        trade_date: str,
        reviewer: str,
        symbol: str,
        primary_tag: str,
        research_verdict: str,
        tags: list[str] | None = None,
        review_status: str = "draft",
        review_scope: str | None = None,
        confidence: float = 0.0,
        notes: str = "",
        created_at: str | None = None,
    ) -> dict[str, Any]:
        context = self._prepare_selection_artifact_feedback_context(report_name=report_name, trade_date=trade_date)
        record = self._build_selection_feedback_record(
            snapshot=context["snapshot"],
            report_name=report_name,
            trade_date=trade_date,
            reviewer=reviewer,
            symbol=symbol,
            primary_tag=primary_tag,
            research_verdict=research_verdict,
            tags=tags,
            review_status=review_status,
            review_scope=review_scope,
            confidence=confidence,
            notes=notes,
            created_at=created_at,
            selected_symbols=context["selected_symbols"],
            rejected_symbols=context["rejected_symbols"],
        )

        append_research_feedback(file_path=context["feedback_path"], record=record)
        finalized = self._finalize_selection_artifact_feedback_append(
            report_dir=context["report_dir"],
            artifact_root=context["artifact_root"],
            trade_date=trade_date,
            feedback_path=context["feedback_path"],
        )
        return {
            "record": record.model_dump(mode="json"),
            **finalized,
        }

    def append_selection_artifact_feedback_batch(
        self,
        *,
        report_name: str,
        trade_date: str,
        reviewer: str,
        symbols: list[str],
        primary_tag: str,
        research_verdict: str,
        tags: list[str] | None = None,
        review_status: str = "draft",
        confidence: float = 0.0,
        notes: str = "",
        created_at: str | None = None,
    ) -> dict[str, Any]:
        normalized_symbols: list[str] = []
        seen_symbols: set[str] = set()
        for raw_symbol in symbols:
            normalized_symbol = str(raw_symbol).strip()
            if not normalized_symbol or normalized_symbol in seen_symbols:
                continue
            seen_symbols.add(normalized_symbol)
            normalized_symbols.append(normalized_symbol)

        if not normalized_symbols:
            raise ValueError("At least one symbol is required for batch feedback append")

        context = self._prepare_selection_artifact_feedback_context(report_name=report_name, trade_date=trade_date)
        batch_created_at = created_at or datetime.now().astimezone().isoformat(timespec="seconds")

        records: list[ResearchFeedbackRecord] = []
        for symbol in normalized_symbols:
            record = self._build_selection_feedback_record(
                snapshot=context["snapshot"],
                report_name=report_name,
                trade_date=trade_date,
                reviewer=reviewer,
                symbol=symbol,
                primary_tag=primary_tag,
                research_verdict=research_verdict,
                tags=tags,
                review_status=review_status,
                review_scope=None,
                confidence=confidence,
                notes=notes,
                created_at=batch_created_at,
                selected_symbols=context["selected_symbols"],
                rejected_symbols=context["rejected_symbols"],
            )
            append_research_feedback(file_path=context["feedback_path"], record=record)
            records.append(record)

        finalized = self._finalize_selection_artifact_feedback_append(
            report_dir=context["report_dir"],
            artifact_root=context["artifact_root"],
            trade_date=trade_date,
            feedback_path=context["feedback_path"],
        )
        return {
            "records": [record.model_dump(mode="json") for record in records],
            "appended_count": len(records),
            **finalized,
        }

    def _prepare_selection_artifact_feedback_context(self, *, report_name: str, trade_date: str) -> dict[str, Any]:
        service = self._service
        report_dir = service._get_report_dir(report_name)
        session_summary = service._read_json(report_dir / "session_summary.json")
        artifact_root = service._resolve_selection_artifact_root(report_dir, session_summary)
        if artifact_root is None:
            raise FileNotFoundError(f"Selection artifact root not found for report: {report_name}")

        day_dir = artifact_root / trade_date
        if not day_dir.is_dir():
            raise FileNotFoundError(f"Selection artifact day not found: {report_name}/{trade_date}")

        snapshot = service._read_json(day_dir / "selection_snapshot.json")
        selected_symbols = {str(item.get("symbol")) for item in (snapshot.get("selected") or []) if isinstance(item, dict) and item.get("symbol")}
        rejected_symbols = {str(item.get("symbol")) for item in (snapshot.get("rejected") or []) if isinstance(item, dict) and item.get("symbol")}
        return {
            "report_dir": report_dir,
            "artifact_root": artifact_root,
            "day_dir": day_dir,
            "snapshot": snapshot,
            "feedback_path": day_dir / "research_feedback.jsonl",
            "selected_symbols": selected_symbols,
            "rejected_symbols": rejected_symbols,
        }

    def _build_selection_feedback_record(
        self,
        *,
        snapshot: dict[str, Any],
        report_name: str,
        trade_date: str,
        reviewer: str,
        symbol: str,
        primary_tag: str,
        research_verdict: str,
        tags: list[str] | None,
        review_status: str,
        review_scope: str | None,
        confidence: float,
        notes: str,
        created_at: str | None,
        selected_symbols: set[str],
        rejected_symbols: set[str],
    ) -> ResearchFeedbackRecord:
        known_symbols = selected_symbols | rejected_symbols
        if symbol not in known_symbols:
            raise ValueError(f"Symbol not found in selection snapshot: {symbol}")

        normalized_review_scope = review_scope or ("watchlist" if symbol in selected_symbols else "near_miss")
        return ResearchFeedbackRecord(
            run_id=str(snapshot.get("run_id") or report_name),
            trade_date=str(snapshot.get("trade_date") or trade_date),
            symbol=symbol,
            review_scope=normalized_review_scope,
            reviewer=reviewer,
            review_status=review_status,
            primary_tag=primary_tag,
            tags=list(tags or []),
            confidence=confidence,
            research_verdict=research_verdict,
            notes=notes,
            created_at=created_at or datetime.now().astimezone().isoformat(timespec="seconds"),
            artifact_version=str(snapshot.get("artifact_version") or "v1"),
        )

    def _finalize_selection_artifact_feedback_append(
        self,
        *,
        report_dir: Any,
        artifact_root: Any,
        trade_date: str,
        feedback_path: Any,
    ) -> dict[str, Any]:
        service = self._service
        directory_summary = summarize_research_feedback_directory(artifact_root=artifact_root, skip_invalid=False)
        summary_path = artifact_root / "research_feedback_summary.json"
        summary_path.write_text(json.dumps(directory_summary.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        service._sync_session_feedback_summary(report_dir=report_dir, directory_summary=directory_summary, summary_path=summary_path)

        day_records = read_research_feedback(file_path=feedback_path, skip_invalid=False)
        service._sync_feedback_ledger_for_day(
            report_name=report_dir.name,
            trade_date=trade_date,
            feedback_path=feedback_path,
            records=day_records,
        )
        service._sync_workflow_items_for_report(report_name=report_dir.name)
        day_summary = summarize_research_feedback(records=day_records)
        return {
            "feedback_record_count": len(day_records),
            "feedback_summary": day_summary.model_dump(mode="json"),
            "directory_summary": directory_summary.model_dump(mode="json"),
            "feedback_path": str(feedback_path),
        }
