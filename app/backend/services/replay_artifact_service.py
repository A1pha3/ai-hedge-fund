from __future__ import annotations

import json
from contextlib import contextmanager
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.backend.database.connection import SessionLocal
from app.backend.database.connection import Base
from app.backend.database.models import ReplayResearchFeedbackLedger, ReplayResearchFeedbackWorkflowItem
from src.research.feedback import append_research_feedback, read_research_feedback, summarize_research_feedback, summarize_research_feedback_directory
from src.research.models import RESEARCH_FEEDBACK_ALLOWED_REVIEW_STATUS, RESEARCH_FEEDBACK_ALLOWED_TAGS, ResearchFeedbackRecord


class ReplayArtifactService:
    def __init__(self, *, session_factory: Any | None = None) -> None:
        self._repo_root = Path(__file__).resolve().parents[3]
        self._reports_root = self._repo_root / "data" / "reports"
        self._session_factory = session_factory or SessionLocal
        self._ensure_feedback_ledger_table()

    def list_replays(self) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for summary_path in sorted(self._reports_root.glob("*/session_summary.json")):
            report_dir = summary_path.parent
            try:
                summaries.append(self._build_replay_summary(report_dir, include_tickers=False))
            except FileNotFoundError:
                continue
        summaries.sort(key=lambda item: item["report_dir"], reverse=True)
        return summaries

    def get_replay(self, report_name: str) -> dict[str, Any]:
        report_dir = self._get_report_dir(report_name)
        return self._build_replay_summary(report_dir, include_tickers=True)

    def get_selection_artifact_day(self, report_name: str, trade_date: str) -> dict[str, Any]:
        report_dir = self._get_report_dir(report_name)
        session_summary = self._read_json(report_dir / "session_summary.json")
        artifact_root = self._resolve_selection_artifact_root(report_dir, session_summary)
        if artifact_root is None:
            raise FileNotFoundError(f"Selection artifact root not found for report: {report_name}")

        day_dir = artifact_root / trade_date
        if not day_dir.is_dir():
            raise FileNotFoundError(f"Selection artifact day not found: {report_name}/{trade_date}")

        snapshot_path = day_dir / "selection_snapshot.json"
        review_path = day_dir / "selection_review.md"
        feedback_path = day_dir / "research_feedback.jsonl"
        snapshot = self._read_json(snapshot_path)
        feedback_records = read_research_feedback(file_path=feedback_path, skip_invalid=False)
        feedback_records = sorted(
            feedback_records,
            key=lambda record: record.created_at,
            reverse=True,
        )
        self._sync_feedback_ledger_for_day(
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
            "review_markdown": self._read_text(review_path),
            "feedback_record_count": len(feedback_records),
            "feedback_records": [record.model_dump(mode="json") for record in feedback_records],
            "feedback_summary": feedback_summary.model_dump(mode="json"),
            "feedback_options": {
                "allowed_tags": list(RESEARCH_FEEDBACK_ALLOWED_TAGS),
                "allowed_review_statuses": list(RESEARCH_FEEDBACK_ALLOWED_REVIEW_STATUS),
            },
            "blocker_counts": self._counter_to_list(blocker_counts),
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

    def get_feedback_activity(
        self,
        *,
        report_name: str | None = None,
        reviewer: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        normalized_limit = max(1, min(int(limit), 200))
        self._sync_feedback_ledger(report_name=report_name)

        with self._db_session() as db:
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
        normalized_limit = max(1, min(int(limit), 200))
        self._sync_feedback_ledger(report_name=report_name)
        self._sync_workflow_items(report_name=report_name)

        with self._db_session() as db:
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
        self._sync_feedback_ledger(report_name=report_name)
        self._sync_workflow_items(report_name=report_name)

        with self._db_session() as db:
            item = (
                db.query(ReplayResearchFeedbackWorkflowItem)
                .filter(ReplayResearchFeedbackWorkflowItem.report_name == report_name)
                .filter(ReplayResearchFeedbackWorkflowItem.trade_date == trade_date)
                .filter(ReplayResearchFeedbackWorkflowItem.symbol == symbol)
                .filter(ReplayResearchFeedbackWorkflowItem.review_scope == review_scope)
                .one_or_none()
            )
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

    def _build_replay_summary(self, report_dir: Path, include_tickers: bool) -> dict[str, Any]:
        session_summary = self._read_json(report_dir / "session_summary.json")
        daily_events = self._read_jsonl(report_dir / "daily_events.jsonl")
        pipeline_timings = self._read_jsonl(report_dir / "pipeline_timings.jsonl")

        final_value = self._extract_final_value(session_summary)
        initial_capital = float(session_summary.get("initial_capital", 0.0) or 0.0)
        total_return_pct = None
        if initial_capital:
            total_return_pct = ((final_value - initial_capital) / initial_capital) * 100

        derived = self._derive_daily_event_metrics(daily_events, session_summary)
        runtime = self._derive_runtime_metrics(pipeline_timings)

        summary: dict[str, Any] = {
            "report_dir": report_dir.name,
            "window": {
                "start_date": session_summary.get("start_date"),
                "end_date": session_summary.get("end_date"),
            },
            "run_header": {
                "mode": session_summary.get("mode"),
                "plan_generation_mode": (session_summary.get("plan_generation") or {}).get("mode"),
                "model_provider": session_summary.get("model_provider"),
                "model_name": session_summary.get("model_name"),
            },
            "headline_kpi": {
                "initial_capital": initial_capital,
                "final_value": final_value,
                "total_return_pct": total_return_pct,
                "sharpe_ratio": (session_summary.get("performance_metrics") or {}).get("sharpe_ratio"),
                "sortino_ratio": (session_summary.get("performance_metrics") or {}).get("sortino_ratio"),
                "max_drawdown_pct": (session_summary.get("performance_metrics") or {}).get("max_drawdown"),
                "max_drawdown_date": (session_summary.get("performance_metrics") or {}).get("max_drawdown_date"),
                "executed_trade_days": (session_summary.get("daily_event_stats") or {}).get("executed_trade_days"),
                "total_executed_orders": (session_summary.get("daily_event_stats") or {}).get("total_executed_orders"),
            },
            "deployment_funnel_runtime": {
                **derived["funnel"],
                **runtime,
            },
            "artifacts": session_summary.get("artifacts") or {},
            "cache_benchmark_overview": self._derive_cache_benchmark_overview(session_summary),
            "selection_artifact_overview": self._derive_selection_artifact_overview(report_dir, session_summary, daily_events),
        }

        if include_tickers:
            summary["ticker_execution_digest"] = derived["tickers"]
            summary["final_portfolio_snapshot"] = session_summary.get("final_portfolio_snapshot") or {}

        return summary

    def _prepare_selection_artifact_feedback_context(self, *, report_name: str, trade_date: str) -> dict[str, Any]:
        report_dir = self._get_report_dir(report_name)
        session_summary = self._read_json(report_dir / "session_summary.json")
        artifact_root = self._resolve_selection_artifact_root(report_dir, session_summary)
        if artifact_root is None:
            raise FileNotFoundError(f"Selection artifact root not found for report: {report_name}")

        day_dir = artifact_root / trade_date
        if not day_dir.is_dir():
            raise FileNotFoundError(f"Selection artifact day not found: {report_name}/{trade_date}")

        snapshot = self._read_json(day_dir / "selection_snapshot.json")
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
        report_dir: Path,
        artifact_root: Path,
        trade_date: str,
        feedback_path: Path,
    ) -> dict[str, Any]:
        directory_summary = summarize_research_feedback_directory(artifact_root=artifact_root, skip_invalid=False)
        summary_path = artifact_root / "research_feedback_summary.json"
        summary_path.write_text(json.dumps(directory_summary.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        self._sync_session_feedback_summary(report_dir=report_dir, directory_summary=directory_summary, summary_path=summary_path)

        day_records = read_research_feedback(file_path=feedback_path, skip_invalid=False)
        self._sync_feedback_ledger_for_day(
            report_name=report_dir.name,
            trade_date=trade_date,
            feedback_path=feedback_path,
            records=day_records,
        )
        self._sync_workflow_items_for_report(report_name=report_dir.name)
        day_summary = summarize_research_feedback(records=day_records)
        return {
            "feedback_record_count": len(day_records),
            "feedback_summary": day_summary.model_dump(mode="json"),
            "directory_summary": directory_summary.model_dump(mode="json"),
            "feedback_path": str(feedback_path),
        }

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

    def _sync_workflow_items(self, *, report_name: str | None = None) -> None:
        with self._db_session() as db:
            query = db.query(ReplayResearchFeedbackLedger)
            if report_name:
                query = query.filter(ReplayResearchFeedbackLedger.report_name == report_name)
            rows = query.order_by(ReplayResearchFeedbackLedger.created_at.desc()).all()

            latest_by_key: dict[tuple[str, str, str, str], ReplayResearchFeedbackLedger] = {}
            for row in rows:
                latest_by_key.setdefault((row.report_name, row.trade_date, row.symbol, row.review_scope), row)

            for row in latest_by_key.values():
                item = (
                    db.query(ReplayResearchFeedbackWorkflowItem)
                    .filter(ReplayResearchFeedbackWorkflowItem.report_name == row.report_name)
                    .filter(ReplayResearchFeedbackWorkflowItem.trade_date == row.trade_date)
                    .filter(ReplayResearchFeedbackWorkflowItem.symbol == row.symbol)
                    .filter(ReplayResearchFeedbackWorkflowItem.review_scope == row.review_scope)
                    .one_or_none()
                )
                if item is None:
                    item = ReplayResearchFeedbackWorkflowItem(
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
                else:
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
                db.add(item)
            db.commit()

    def _sync_workflow_items_for_report(self, *, report_name: str) -> None:
        self._sync_workflow_items(report_name=report_name)

    def _extract_final_value(self, session_summary: dict[str, Any]) -> float:
        portfolio_values = session_summary.get("portfolio_values") or []
        if portfolio_values:
            last_value = portfolio_values[-1].get("Portfolio Value")
            if last_value is not None:
                return float(last_value)
        return 0.0

    def _derive_daily_event_metrics(self, daily_events: list[dict[str, Any]], session_summary: dict[str, Any]) -> dict[str, Any]:
        layer_b_values: list[float] = []
        watchlist_values: list[float] = []
        buy_order_values: list[float] = []
        buy_blockers: Counter[str] = Counter()
        watch_blockers: Counter[str] = Counter()
        invested_ratios: list[float] = []
        peak_invested_ratio = 0.0

        ticker_buy_counts: Counter[str] = Counter()
        ticker_sell_counts: Counter[str] = Counter()
        ticker_max_unrealized: defaultdict[str, float] = defaultdict(float)

        final_snapshot = (session_summary.get("final_portfolio_snapshot") or {}).get("positions") or {}
        realized_gains = (session_summary.get("final_portfolio_snapshot") or {}).get("realized_gains") or {}

        initial_capital = float(session_summary.get("initial_capital", 0.0) or 0.0)

        for record in daily_events:
            current_plan = record.get("current_plan") or {}
            risk_metrics = current_plan.get("risk_metrics") or {}
            counts = risk_metrics.get("counts") or {}
            funnel = risk_metrics.get("funnel_diagnostics") or {}
            filters = funnel.get("filters") or {}

            layer_b = counts.get("layer_b_count")
            watch_count = counts.get("watchlist_count")
            buy_count = counts.get("buy_order_count")
            if layer_b is not None:
                layer_b_values.append(float(layer_b))
            if watch_count is not None:
                watchlist_values.append(float(watch_count))
            if buy_count is not None:
                buy_order_values.append(float(buy_count))

            watch_reasons = ((filters.get("watchlist") or {}).get("reason_counts") or {})
            buy_reasons = ((filters.get("buy_orders") or {}).get("reason_counts") or {})
            watch_blockers.update({str(key): int(value) for key, value in watch_reasons.items()})
            buy_blockers.update({str(key): int(value) for key, value in buy_reasons.items()})

            portfolio_snapshot = record.get("portfolio_snapshot") or {}
            current_prices = record.get("current_prices") or {}
            positions = portfolio_snapshot.get("positions") or {}
            invested_value = 0.0
            for ticker, position in positions.items():
                if not isinstance(position, dict):
                    continue
                long_shares = float(position.get("long", 0) or 0)
                if long_shares <= 0:
                    continue
                current_price = current_prices.get(ticker)
                if current_price is None:
                    continue
                invested_value += long_shares * float(current_price)
                ticker_max_unrealized[ticker] = max(
                    ticker_max_unrealized[ticker],
                    float(position.get("max_unrealized_pnl_pct", 0.0) or 0.0),
                )

            if initial_capital > 0:
                invested_ratio = invested_value / initial_capital
                invested_ratios.append(invested_ratio)
                peak_invested_ratio = max(peak_invested_ratio, invested_ratio)

            decisions = record.get("decisions") or {}
            for ticker, decision in decisions.items():
                if not isinstance(decision, dict):
                    continue
                action = decision.get("action")
                if action == "buy":
                    ticker_buy_counts[ticker] += 1
                elif action == "sell":
                    ticker_sell_counts[ticker] += 1

        ticker_digests: list[dict[str, Any]] = []
        for ticker in sorted(set(ticker_buy_counts) | set(ticker_sell_counts) | set(final_snapshot) | set(realized_gains)):
            position = final_snapshot.get(ticker) or {}
            realized = realized_gains.get(ticker) or {}
            final_long = position.get("long", 0) if isinstance(position, dict) else 0
            realized_pnl = realized.get("long", 0.0) if isinstance(realized, dict) else 0.0
            if not ticker_buy_counts[ticker] and not ticker_sell_counts[ticker] and not final_long and not realized_pnl:
                continue
            ticker_digests.append(
                {
                    "ticker": ticker,
                    "buy_count": ticker_buy_counts[ticker],
                    "sell_count": ticker_sell_counts[ticker],
                    "final_long": final_long,
                    "realized_pnl": realized_pnl,
                    "max_unrealized_pnl_pct": ticker_max_unrealized.get(ticker, 0.0),
                    "entry_score": position.get("entry_score") if isinstance(position, dict) else None,
                }
            )

        ticker_digests.sort(key=lambda item: (item["buy_count"] + item["sell_count"], abs(item["realized_pnl"])), reverse=True)

        return {
            "funnel": {
                "avg_invested_ratio": self._safe_average(invested_ratios),
                "peak_invested_ratio": peak_invested_ratio,
                "avg_layer_b_count": self._safe_average(layer_b_values),
                "avg_watchlist_count": self._safe_average(watchlist_values),
                "avg_buy_order_count": self._safe_average(buy_order_values),
                "top_buy_blockers": self._counter_to_list(buy_blockers),
                "top_watchlist_blockers": self._counter_to_list(watch_blockers),
            },
            "tickers": ticker_digests,
        }

    def _derive_runtime_metrics(self, pipeline_timings: list[dict[str, Any]]) -> dict[str, Any]:
        total_day_seconds: list[float] = []
        post_market_seconds: list[float] = []
        for record in pipeline_timings:
            timing_seconds = record.get("timing_seconds") or {}
            total_day = timing_seconds.get("total_day")
            post_market = timing_seconds.get("post_market")
            if total_day is not None:
                total_day_seconds.append(float(total_day))
            if post_market is not None:
                post_market_seconds.append(float(post_market))
        return {
            "avg_total_day_seconds": self._safe_average(total_day_seconds),
            "avg_post_market_seconds": self._safe_average(post_market_seconds),
        }

    def _derive_cache_benchmark_overview(self, session_summary: dict[str, Any]) -> dict[str, Any]:
        artifacts = session_summary.get("artifacts") or {}
        benchmark_payload = session_summary.get("data_cache_benchmark") or {}
        benchmark_status = session_summary.get("data_cache_benchmark_status") or {}
        benchmark_summary = benchmark_payload.get("summary") if isinstance(benchmark_payload, dict) else {}
        if not isinstance(benchmark_summary, dict):
            benchmark_summary = {}

        return {
            "requested": bool(benchmark_status.get("requested") or benchmark_payload.get("requested") or False),
            "executed": bool(benchmark_status.get("executed") or benchmark_payload.get("executed") or False),
            "write_status": benchmark_status.get("write_status") or benchmark_payload.get("write_status"),
            "reason": benchmark_status.get("reason") or benchmark_payload.get("reason"),
            "ticker": benchmark_payload.get("ticker"),
            "trade_date": benchmark_payload.get("trade_date"),
            "reuse_confirmed": benchmark_summary.get("reuse_confirmed"),
            "disk_hit_gain": benchmark_summary.get("disk_hit_gain"),
            "miss_reduction": benchmark_summary.get("miss_reduction"),
            "set_reduction": benchmark_summary.get("set_reduction"),
            "first_hit_rate": benchmark_summary.get("first_hit_rate"),
            "second_hit_rate": benchmark_summary.get("second_hit_rate"),
            "artifacts": {
                key: value
                for key, value in {
                    "data_cache_benchmark_json": artifacts.get("data_cache_benchmark_json"),
                    "data_cache_benchmark_markdown": artifacts.get("data_cache_benchmark_markdown"),
                    "data_cache_benchmark_appended_report": artifacts.get("data_cache_benchmark_appended_report"),
                }.items()
                if value
            },
        }

    def _derive_selection_artifact_overview(
        self,
        report_dir: Path,
        session_summary: dict[str, Any],
        daily_events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        artifact_root = self._resolve_selection_artifact_root(report_dir, session_summary)
        if artifact_root is None or not artifact_root.exists():
            return {
                "available": False,
                "trade_date_count": 0,
                "available_trade_dates": [],
                "write_status_counts": {},
                "blocker_counts": [],
                "feedback_summary": None,
            }

        write_status_counts: Counter[str] = Counter()
        for record in daily_events:
            selection_artifacts = (record.get("current_plan") or {}).get("selection_artifacts") or record.get("selection_artifacts") or {}
            write_status = selection_artifacts.get("write_status")
            if write_status:
                write_status_counts[str(write_status)] += 1

        trade_dates: list[str] = []
        blocker_counts: Counter[str] = Counter()
        for day_dir in sorted(path for path in artifact_root.iterdir() if path.is_dir()):
            snapshot_path = day_dir / "selection_snapshot.json"
            if not snapshot_path.exists():
                continue
            trade_dates.append(day_dir.name)
            snapshot = self._read_json(snapshot_path)
            for candidate in snapshot.get("selected") or []:
                if not isinstance(candidate, dict):
                    continue
                execution_bridge = candidate.get("execution_bridge") or {}
                block_reason = execution_bridge.get("block_reason")
                if block_reason:
                    blocker_counts[str(block_reason)] += 1

        feedback_summary_path = artifact_root / "research_feedback_summary.json"
        feedback_summary = self._read_json(feedback_summary_path) if feedback_summary_path.exists() else None

        return {
            "available": True,
            "artifact_root": str(artifact_root),
            "trade_date_count": len(trade_dates),
            "available_trade_dates": trade_dates,
            "write_status_counts": dict(write_status_counts),
            "blocker_counts": self._counter_to_list(blocker_counts),
            "feedback_summary": feedback_summary,
        }

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

    def _feedback_record_key(self, *, report_name: str, trade_date: str, record: ResearchFeedbackRecord) -> tuple[str, str, str, str, str, datetime]:
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
            existing_rows = db.query(ReplayResearchFeedbackLedger).filter(
                ReplayResearchFeedbackLedger.report_name == report_name,
                ReplayResearchFeedbackLedger.trade_date == trade_date,
            ).all()

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
                record_key = self._feedback_record_key(report_name=report_name, trade_date=trade_date, record=record)
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

    def _resolve_selection_artifact_root(self, report_dir: Path, session_summary: dict[str, Any]) -> Path | None:
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

    def _sync_session_feedback_summary(self, *, report_dir: Path, directory_summary: Any, summary_path: Path) -> None:
        session_summary_path = report_dir / "session_summary.json"
        if not session_summary_path.exists():
            return
        session_summary = self._read_json(session_summary_path)
        artifacts = session_summary.setdefault("artifacts", {})
        artifacts["research_feedback_summary"] = str(summary_path)
        session_summary["research_feedback_summary"] = directory_summary.model_dump(mode="json")
        session_summary_path.write_text(json.dumps(session_summary, ensure_ascii=False, indent=2), encoding="utf-8")

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def _safe_average(self, values: list[float]) -> float | None:
        if not values:
            return None
        return sum(values) / len(values)

    def _counter_to_list(self, counter: Counter[str], limit: int = 5) -> list[dict[str, Any]]:
        return [{"reason": reason, "count": count} for reason, count in counter.most_common(limit)]