from __future__ import annotations

from collections import Counter
from typing import Any, TYPE_CHECKING

from sqlalchemy.orm import Session

from app.backend.database.models import (
    ReplayResearchFeedbackLedger,
    ReplayResearchFeedbackWorkflowItem,
)

if TYPE_CHECKING:
    from app.backend.services.replay_artifact_service import ReplayArtifactService


class ReplayFeedbackWorkflowHelper:
    def __init__(self, service: ReplayArtifactService) -> None:
        self._service = service

    def get_feedback_activity(
        self,
        *,
        report_name: str | None = None,
        reviewer: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        service = self._service
        normalized_limit = max(1, min(int(limit), 200))
        service._sync_feedback_ledger(report_name=report_name)

        with service._db_session() as db:
            query = db.query(ReplayResearchFeedbackLedger)
            if report_name:
                query = query.filter(ReplayResearchFeedbackLedger.report_name == report_name)
            if reviewer:
                query = query.filter(ReplayResearchFeedbackLedger.reviewer == reviewer)

            all_rows = query.order_by(ReplayResearchFeedbackLedger.created_at.desc()).all()
            rows = all_rows[:normalized_limit]

            status_counts: Counter[str] = Counter()
            tag_counts: Counter[str] = Counter()
            reviewer_counts: Counter[str] = Counter()
            report_counts: Counter[str] = Counter()
            workflow_status_counts: Counter[str] = Counter()
            latest_by_symbol_key: dict[tuple[str, str, str, str], ReplayResearchFeedbackLedger] = {}
            workflow_queue: dict[str, list[dict[str, Any]]] = {
                "draft": [],
                "final": [],
                "adjudicated": [],
            }

            recent_records: list[dict[str, Any]] = []
            for row in all_rows:
                latest_by_symbol_key.setdefault(
                    (row.report_name, row.trade_date, row.symbol, row.review_scope),
                    row,
                )

            for row in rows:
                status_counts[str(row.review_status)] += 1
                reviewer_counts[str(row.reviewer)] += 1
                report_counts[str(row.report_name)] += 1
                for tag in {str(row.primary_tag), *[str(item) for item in list(row.tags or [])]}:
                    tag_counts[tag] += 1
                recent_records.append(self._serialize_feedback_ledger_row(row))

            for row in sorted(latest_by_symbol_key.values(), key=lambda item: item.created_at, reverse=True):
                status = str(row.review_status)
                workflow_status_counts[status] += 1
                if status not in workflow_queue:
                    workflow_queue[status] = []
                if len(workflow_queue[status]) < 10:
                    workflow_queue[status].append(self._serialize_feedback_ledger_row(row))

        return {
            "report_name": report_name,
            "reviewer": reviewer,
            "limit": normalized_limit,
            "record_count": len(recent_records),
            "recent_records": recent_records,
            "review_status_counts": dict(status_counts),
            "tag_counts": dict(tag_counts),
            "reviewer_counts": dict(reviewer_counts),
            "report_counts": dict(report_counts),
            "workflow_status_counts": dict(workflow_status_counts),
            "workflow_queue": workflow_queue,
        }

    def list_workflow_queue(
        self,
        *,
        assignee: str | None = None,
        workflow_status: str | None = None,
        report_name: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        service = self._service
        normalized_limit = max(1, min(int(limit), 200))
        service._sync_feedback_ledger(report_name=report_name)
        self._sync_workflow_items(report_name=report_name)

        with service._db_session() as db:
            query = db.query(ReplayResearchFeedbackWorkflowItem)
            if report_name:
                query = query.filter(ReplayResearchFeedbackWorkflowItem.report_name == report_name)
            if workflow_status:
                query = query.filter(ReplayResearchFeedbackWorkflowItem.workflow_status == workflow_status)
            if assignee == "__unassigned__":
                query = query.filter(ReplayResearchFeedbackWorkflowItem.assignee.is_(None))
            elif assignee:
                query = query.filter(ReplayResearchFeedbackWorkflowItem.assignee == assignee)

            rows = query.order_by(ReplayResearchFeedbackWorkflowItem.latest_feedback_created_at.desc()).limit(normalized_limit).all()

            all_rows_query = db.query(ReplayResearchFeedbackWorkflowItem)
            if report_name:
                all_rows_query = all_rows_query.filter(ReplayResearchFeedbackWorkflowItem.report_name == report_name)
            all_rows = all_rows_query.all()

            workflow_status_counts: Counter[str] = Counter()
            assignee_counts: Counter[str] = Counter()
            report_counts: Counter[str] = Counter()
            for row in all_rows:
                workflow_status_counts[str(row.workflow_status)] += 1
                assignee_counts[str(row.assignee or "__unassigned__")] += 1
                report_counts[str(row.report_name)] += 1

        return {
            "assignee": assignee,
            "workflow_status": workflow_status,
            "report_name": report_name,
            "limit": normalized_limit,
            "item_count": len(rows),
            "items": [self._serialize_workflow_item(row) for row in rows],
            "workflow_status_counts": dict(workflow_status_counts),
            "assignee_counts": dict(assignee_counts),
            "report_counts": dict(report_counts),
        }

    def update_workflow_item(
        self,
        *,
        report_name: str,
        trade_date: str,
        symbol: str,
        review_scope: str,
        assignee: str | None = None,
        workflow_status: str | None = None,
    ) -> dict[str, Any]:
        service = self._service
        service._sync_feedback_ledger(report_name=report_name)
        self._sync_workflow_items(report_name=report_name)

        with service._db_session() as db:
            item = db.query(ReplayResearchFeedbackWorkflowItem).filter(ReplayResearchFeedbackWorkflowItem.report_name == report_name).filter(ReplayResearchFeedbackWorkflowItem.trade_date == trade_date).filter(ReplayResearchFeedbackWorkflowItem.symbol == symbol).filter(ReplayResearchFeedbackWorkflowItem.review_scope == review_scope).one_or_none()
            if item is None:
                raise FileNotFoundError(f"Workflow item not found: {report_name}/{trade_date}/{symbol}/{review_scope}")

            if assignee is not None:
                normalized_assignee = assignee.strip() or None
                item.assignee = normalized_assignee
                if workflow_status is None:
                    if normalized_assignee and item.workflow_status == "unassigned":
                        item.workflow_status = "assigned"
                    elif not normalized_assignee and item.workflow_status in {"assigned", "in_review"}:
                        item.workflow_status = self._default_workflow_status_for_review_status(item.latest_review_status)

            if workflow_status is not None:
                item.workflow_status = workflow_status

            db.add(item)
            db.commit()
            db.refresh(item)
            return self._serialize_workflow_item(item)

    def _serialize_feedback_ledger_row(self, row: ReplayResearchFeedbackLedger) -> dict[str, Any]:
        return {
            "report_name": row.report_name,
            "trade_date": row.trade_date,
            "feedback_path": row.feedback_path,
            "symbol": row.symbol,
            "review_scope": row.review_scope,
            "reviewer": row.reviewer,
            "review_status": row.review_status,
            "primary_tag": row.primary_tag,
            "tags": list(row.tags or []),
            "confidence": row.confidence,
            "research_verdict": row.research_verdict,
            "notes": row.notes,
            "created_at": row.created_at.isoformat(),
        }

    def _serialize_workflow_item(self, item: ReplayResearchFeedbackWorkflowItem) -> dict[str, Any]:
        return {
            "report_name": item.report_name,
            "trade_date": item.trade_date,
            "symbol": item.symbol,
            "review_scope": item.review_scope,
            "feedback_path": item.feedback_path,
            "latest_feedback_created_at": item.latest_feedback_created_at.isoformat(),
            "latest_reviewer": item.latest_reviewer,
            "latest_review_status": item.latest_review_status,
            "latest_primary_tag": item.latest_primary_tag,
            "latest_tags": list(item.latest_tags or []),
            "latest_research_verdict": item.latest_research_verdict,
            "latest_notes": item.latest_notes,
            "assignee": item.assignee,
            "workflow_status": item.workflow_status,
        }

    def _default_workflow_status_for_review_status(self, review_status: str) -> str:
        normalized = str(review_status)
        if normalized == "final":
            return "ready_for_adjudication"
        if normalized == "adjudicated":
            return "closed"
        return "unassigned"

    def _load_latest_feedback_rows(
        self,
        db: Session,
        *,
        report_name: str | None,
    ) -> list[ReplayResearchFeedbackLedger]:
        query = db.query(ReplayResearchFeedbackLedger)
        if report_name:
            query = query.filter(ReplayResearchFeedbackLedger.report_name == report_name)
        rows = query.order_by(ReplayResearchFeedbackLedger.created_at.desc()).all()

        latest_by_key: dict[tuple[str, str, str, str], ReplayResearchFeedbackLedger] = {}
        for row in rows:
            latest_by_key.setdefault((row.report_name, row.trade_date, row.symbol, row.review_scope), row)
        return list(latest_by_key.values())

    def _load_workflow_item_for_feedback(
        self,
        db: Session,
        row: ReplayResearchFeedbackLedger,
    ) -> ReplayResearchFeedbackWorkflowItem | None:
        return db.query(ReplayResearchFeedbackWorkflowItem).filter(ReplayResearchFeedbackWorkflowItem.report_name == row.report_name).filter(ReplayResearchFeedbackWorkflowItem.trade_date == row.trade_date).filter(ReplayResearchFeedbackWorkflowItem.symbol == row.symbol).filter(ReplayResearchFeedbackWorkflowItem.review_scope == row.review_scope).one_or_none()

    def _build_workflow_item_from_feedback(
        self,
        row: ReplayResearchFeedbackLedger,
    ) -> ReplayResearchFeedbackWorkflowItem:
        return ReplayResearchFeedbackWorkflowItem(
            report_name=row.report_name,
            trade_date=row.trade_date,
            symbol=row.symbol,
            review_scope=row.review_scope,
            feedback_path=row.feedback_path,
            latest_feedback_created_at=row.created_at,
            latest_reviewer=row.reviewer,
            latest_review_status=row.review_status,
            latest_primary_tag=row.primary_tag,
            latest_tags=list(row.tags or []),
            latest_research_verdict=row.research_verdict,
            latest_notes=row.notes,
            workflow_status=self._default_workflow_status_for_review_status(row.review_status),
        )

    def _apply_feedback_row_to_workflow_item(
        self,
        item: ReplayResearchFeedbackWorkflowItem,
        row: ReplayResearchFeedbackLedger,
    ) -> None:
        item.feedback_path = row.feedback_path
        item.latest_feedback_created_at = row.created_at
        item.latest_reviewer = row.reviewer
        item.latest_review_status = row.review_status
        item.latest_primary_tag = row.primary_tag
        item.latest_tags = list(row.tags or [])
        item.latest_research_verdict = row.research_verdict
        item.latest_notes = row.notes
        if row.review_status == "adjudicated":
            item.workflow_status = "closed"
        elif row.review_status == "final" and item.workflow_status == "unassigned":
            item.workflow_status = "ready_for_adjudication"
        elif row.review_status == "draft" and not item.assignee and item.workflow_status in {"ready_for_adjudication", "closed"}:
            item.workflow_status = "unassigned"

    def _sync_workflow_items(self, *, report_name: str | None = None) -> None:
        service = self._service
        with service._db_session() as db:
            for row in self._load_latest_feedback_rows(db, report_name=report_name):
                item = self._load_workflow_item_for_feedback(db, row)
                if item is None:
                    item = self._build_workflow_item_from_feedback(row)
                else:
                    self._apply_feedback_row_to_workflow_item(item, row)
                db.add(item)
            db.commit()

    def _sync_workflow_items_for_report(self, *, report_name: str) -> None:
        self._sync_workflow_items(report_name=report_name)
