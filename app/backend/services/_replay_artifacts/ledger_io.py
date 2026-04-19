from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, TYPE_CHECKING

from sqlalchemy.orm import Session

from app.backend.database.connection import Base
from app.backend.database.models import ReplayResearchFeedbackLedger
from src.research.feedback import read_research_feedback
from src.research.models import ResearchFeedbackRecord

if TYPE_CHECKING:
    from app.backend.services.replay_artifact_service import ReplayArtifactService


class ReplayLedgerIoHelper:
    def __init__(self, service: ReplayArtifactService) -> None:
        self._service = service

    @property
    def _reports_root(self) -> Path:
        return self._service._reports_root

    @property
    def _session_factory(self) -> Any:
        return self._service._session_factory

    def get_report_dir(self, report_name: str) -> Path:
        return self._get_report_dir(report_name)

    def sync_feedback_ledger_for_day(
        self,
        *,
        report_name: str,
        trade_date: str,
        feedback_path: Path,
        records: list[ResearchFeedbackRecord],
    ) -> None:
        self._sync_feedback_ledger_for_day(
            report_name=report_name,
            trade_date=trade_date,
            feedback_path=feedback_path,
            records=records,
        )

    def read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        return self._read_jsonl(path)

    def _get_report_dir(self, report_name: str) -> Path:
        report_dir = self._reports_root / report_name
        if not report_dir.is_dir():
            raise FileNotFoundError(f"Replay report not found: {report_name}")
        return report_dir

    def _sync_feedback_ledger(self, *, report_name: str | None = None) -> None:
        if report_name is not None:
            report_dirs = [self._get_report_dir(report_name)]
        else:
            report_dirs = sorted(summary_path.parent for summary_path in self._reports_root.glob("*/session_summary.json"))

        for report_dir in report_dirs:
            try:
                session_summary = self._read_json(report_dir / "session_summary.json")
            except FileNotFoundError:
                continue
            artifact_root = self._resolve_selection_artifact_root(report_dir, session_summary)
            if artifact_root is None or not artifact_root.exists():
                continue

            for day_dir in sorted(path for path in artifact_root.iterdir() if path.is_dir()):
                feedback_path = day_dir / "research_feedback.jsonl"
                if not feedback_path.exists():
                    continue
                records = read_research_feedback(file_path=feedback_path, skip_invalid=False)
                self._sync_feedback_ledger_for_day(
                    report_name=report_dir.name,
                    trade_date=day_dir.name,
                    feedback_path=feedback_path,
                    records=records,
                )

    def _feedback_record_key(
        self,
        *,
        report_name: str,
        trade_date: str,
        record: ResearchFeedbackRecord,
    ) -> tuple[str, str, str, str, str, datetime]:
        return (
            report_name,
            trade_date,
            record.symbol,
            record.reviewer,
            record.primary_tag,
            self._normalize_feedback_created_at(record.created_at),
        )

    def _sync_feedback_ledger_for_day(
        self,
        *,
        report_name: str,
        trade_date: str,
        feedback_path: Path,
        records: list[ResearchFeedbackRecord],
    ) -> None:
        with self._db_session() as db:
            existing_rows = (
                db.query(ReplayResearchFeedbackLedger)
                .filter(
                    ReplayResearchFeedbackLedger.report_name == report_name,
                    ReplayResearchFeedbackLedger.trade_date == trade_date,
                )
                .all()
            )

            existing_by_key = {
                (
                    row.report_name,
                    row.trade_date,
                    row.symbol,
                    row.reviewer,
                    row.primary_tag,
                    self._normalize_feedback_created_at(row.created_at),
                ): row
                for row in existing_rows
            }

            incoming_keys = set()
            for record in records:
                record_key = self._feedback_record_key(
                    report_name=report_name,
                    trade_date=trade_date,
                    record=record,
                )
                incoming_keys.add(record_key)
                ledger_row = existing_by_key.get(record_key)
                payload = {
                    "feedback_path": str(feedback_path),
                    "run_id": record.run_id,
                    "artifact_version": record.artifact_version,
                    "label_version": record.label_version,
                    "symbol": record.symbol,
                    "review_scope": record.review_scope,
                    "reviewer": record.reviewer,
                    "review_status": record.review_status,
                    "primary_tag": record.primary_tag,
                    "tags": list(record.tags or []),
                    "confidence": float(record.confidence),
                    "research_verdict": record.research_verdict,
                    "notes": record.notes,
                    "created_at": self._normalize_feedback_created_at(record.created_at),
                }
                if ledger_row is None:
                    db.add(
                        ReplayResearchFeedbackLedger(
                            report_name=report_name,
                            trade_date=trade_date,
                            **payload,
                        )
                    )
                else:
                    for field_name, field_value in payload.items():
                        setattr(ledger_row, field_name, field_value)

            for row in existing_rows:
                row_key = (
                    row.report_name,
                    row.trade_date,
                    row.symbol,
                    row.reviewer,
                    row.primary_tag,
                    self._normalize_feedback_created_at(row.created_at),
                )
                if row_key not in incoming_keys:
                    db.delete(row)

            db.commit()

    def _resolve_selection_artifact_root(
        self,
        report_dir: Path,
        session_summary: dict[str, Any],
    ) -> Path | None:
        artifact_root_value = (session_summary.get("artifacts") or {}).get("selection_artifact_root")
        if artifact_root_value:
            artifact_root = Path(str(artifact_root_value))
            if artifact_root.exists():
                return artifact_root
        fallback_root = report_dir / "selection_artifacts"
        return fallback_root if fallback_root.exists() else None

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(path)
        return json.loads(path.read_text(encoding="utf-8"))

    def _read_text(self, path: Path) -> str:
        if not path.exists():
            raise FileNotFoundError(path)
        return path.read_text(encoding="utf-8")

    def _ensure_feedback_ledger_table(self) -> None:
        bind = getattr(self._session_factory, "kw", {}).get("bind") if hasattr(self._session_factory, "kw") else None
        if bind is not None:
            Base.metadata.create_all(bind=bind, tables=[ReplayResearchFeedbackLedger.__table__])

    def _normalize_feedback_created_at(self, value: Any) -> datetime:
        if isinstance(value, datetime):
            normalized = value
        else:
            normalized = datetime.fromisoformat(str(value))
        if normalized.tzinfo is not None:
            return normalized.astimezone().replace(tzinfo=None)
        return normalized

    @contextmanager
    def _db_session(self) -> Any:
        db: Session = self._session_factory()
        try:
            yield db
        finally:
            db.close()

    def _sync_session_feedback_summary(
        self,
        *,
        report_dir: Path,
        directory_summary: Any,
        summary_path: Path,
    ) -> None:
        session_summary_path = report_dir / "session_summary.json"
        if not session_summary_path.exists():
            return
        session_summary = self._read_json(session_summary_path)
        artifacts = session_summary.setdefault("artifacts", {})
        artifacts["research_feedback_summary"] = str(summary_path)
        session_summary["research_feedback_summary"] = directory_summary.model_dump(mode="json")
        session_summary_path.write_text(
            json.dumps(session_summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows
