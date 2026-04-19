from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from app.backend.database.connection import SessionLocal
from app.backend.services._replay_artifacts.ledger_io import ReplayLedgerIoHelper
from app.backend.services._replay_artifacts.selection_feedback import (
    ReplaySelectionFeedbackHelper,
)
from app.backend.services._replay_artifacts.selection_overview import (
    ReplaySelectionOverviewHelper,
)
from app.backend.services._replay_artifacts.summary import ReplaySummaryHelper
from app.backend.services._replay_artifacts.workflow import ReplayFeedbackWorkflowHelper
from src.research.models import ResearchFeedbackRecord


class ReplayArtifactService:
    def __init__(self, *, session_factory: Any | None = None) -> None:
        self._repo_root = Path(__file__).resolve().parents[3]
        self._reports_root = self._repo_root / "data" / "reports"
        self._session_factory = session_factory or SessionLocal
        self._ledger_io_helper = ReplayLedgerIoHelper(self)
        self._ensure_feedback_ledger_table()
        self._selection_feedback_helper = ReplaySelectionFeedbackHelper(self)
        self._selection_overview_helper = ReplaySelectionOverviewHelper(self)
        self._summary_helper = ReplaySummaryHelper(self)
        self._workflow_helper = ReplayFeedbackWorkflowHelper(self)

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
        return self._selection_feedback_helper.get_selection_artifact_day(report_name, trade_date)

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
        return self._selection_feedback_helper.append_selection_artifact_feedback(
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
        )

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
        return self._selection_feedback_helper.append_selection_artifact_feedback_batch(
            report_name=report_name,
            trade_date=trade_date,
            reviewer=reviewer,
            symbols=symbols,
            primary_tag=primary_tag,
            research_verdict=research_verdict,
            tags=tags,
            review_status=review_status,
            confidence=confidence,
            notes=notes,
            created_at=created_at,
        )

    def get_feedback_activity(
        self,
        *,
        report_name: str | None = None,
        reviewer: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        return self._workflow_helper.get_feedback_activity(
            report_name=report_name,
            reviewer=reviewer,
            limit=limit,
        )

    def list_workflow_queue(
        self,
        *,
        assignee: str | None = None,
        workflow_status: str | None = None,
        report_name: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        return self._workflow_helper.list_workflow_queue(
            assignee=assignee,
            workflow_status=workflow_status,
            report_name=report_name,
            limit=limit,
        )

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
        return self._workflow_helper.update_workflow_item(
            report_name=report_name,
            trade_date=trade_date,
            symbol=symbol,
            review_scope=review_scope,
            assignee=assignee,
            workflow_status=workflow_status,
        )

    def _load_replay_summary_inputs(self, report_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        return (
            self._read_json(report_dir / "session_summary.json"),
            self._read_jsonl(report_dir / "daily_events.jsonl"),
            self._read_jsonl(report_dir / "pipeline_timings.jsonl"),
        )

    def _derive_replay_total_return_pct(self, session_summary: dict[str, Any], final_value: float) -> tuple[float, float | None]:
        initial_capital = float(session_summary.get("initial_capital", 0.0) or 0.0)
        if not initial_capital:
            return initial_capital, None
        return initial_capital, ((final_value - initial_capital) / initial_capital) * 100

    def _build_replay_headline_kpi(
        self,
        session_summary: dict[str, Any],
        *,
        initial_capital: float,
        final_value: float,
        total_return_pct: float | None,
    ) -> dict[str, Any]:
        performance_metrics = session_summary.get("performance_metrics") or {}
        daily_event_stats = session_summary.get("daily_event_stats") or {}
        return {
            "initial_capital": initial_capital,
            "final_value": final_value,
            "total_return_pct": total_return_pct,
            "sharpe_ratio": performance_metrics.get("sharpe_ratio"),
            "sortino_ratio": performance_metrics.get("sortino_ratio"),
            "max_drawdown_pct": performance_metrics.get("max_drawdown"),
            "max_drawdown_date": performance_metrics.get("max_drawdown_date"),
            "executed_trade_days": daily_event_stats.get("executed_trade_days"),
            "total_executed_orders": daily_event_stats.get("total_executed_orders"),
        }

    def _build_replay_summary_body(
        self,
        report_dir: Path,
        *,
        session_summary: dict[str, Any],
        daily_events: list[dict[str, Any]],
        derived: dict[str, Any],
        runtime: dict[str, Any],
        headline_kpi: dict[str, Any],
        include_tickers: bool,
    ) -> dict[str, Any]:
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
            "headline_kpi": headline_kpi,
            "deployment_funnel_runtime": {
                **derived["funnel"],
                **runtime,
            },
            "artifacts": session_summary.get("artifacts") or {},
            "cache_benchmark_overview": self._derive_cache_benchmark_overview(session_summary),
            "selection_artifact_overview": self._derive_selection_artifact_overview(
                report_dir,
                session_summary,
                daily_events,
                resolve_btst_contexts=include_tickers,
            ),
        }
        if include_tickers:
            summary["ticker_execution_digest"] = derived["tickers"]
            summary["final_portfolio_snapshot"] = session_summary.get("final_portfolio_snapshot") or {}
        return summary

    def _build_replay_summary(self, report_dir: Path, include_tickers: bool) -> dict[str, Any]:
        session_summary, daily_events, pipeline_timings = self._load_replay_summary_inputs(report_dir)
        final_value = self._extract_final_value(session_summary)
        initial_capital, total_return_pct = self._derive_replay_total_return_pct(session_summary, final_value)
        derived = self._derive_daily_event_metrics(daily_events, session_summary)
        runtime = self._derive_runtime_metrics(pipeline_timings)
        headline_kpi = self._build_replay_headline_kpi(
            session_summary,
            initial_capital=initial_capital,
            final_value=final_value,
            total_return_pct=total_return_pct,
        )
        return self._build_replay_summary_body(
            report_dir,
            session_summary=session_summary,
            daily_events=daily_events,
            derived=derived,
            runtime=runtime,
            headline_kpi=headline_kpi,
            include_tickers=include_tickers,
        )

    def _sync_workflow_items(self, *, report_name: str | None = None) -> None:
        self._workflow_helper._sync_workflow_items(report_name=report_name)

    def _sync_workflow_items_for_report(self, *, report_name: str) -> None:
        self._workflow_helper._sync_workflow_items_for_report(report_name=report_name)

    def _extract_final_value(self, session_summary: dict[str, Any]) -> float:
        portfolio_values = session_summary.get("portfolio_values") or []
        if portfolio_values:
            last_value = portfolio_values[-1].get("Portfolio Value")
            if last_value is not None:
                return float(last_value)
        return 0.0

    def _extract_daily_event_funnel_metrics(self, record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        return self._selection_overview_helper._extract_daily_event_funnel_metrics(record)

    def _accumulate_daily_event_count_values(
        self,
        counts: dict[str, Any],
        *,
        layer_b_values: list[float],
        watchlist_values: list[float],
        buy_order_values: list[float],
    ) -> None:
        self._selection_overview_helper._accumulate_daily_event_count_values(
            counts,
            layer_b_values=layer_b_values,
            watchlist_values=watchlist_values,
            buy_order_values=buy_order_values,
        )

    def _accumulate_daily_event_blockers(
        self,
        filters: dict[str, Any],
        *,
        buy_blockers: Counter[str],
        watch_blockers: Counter[str],
    ) -> None:
        self._selection_overview_helper._accumulate_daily_event_blockers(
            filters,
            buy_blockers=buy_blockers,
            watch_blockers=watch_blockers,
        )

    def _accumulate_daily_event_invested_ratio(
        self,
        *,
        record: dict[str, Any],
        initial_capital: float,
        invested_ratios: list[float],
        ticker_max_unrealized: defaultdict[str, float],
    ) -> float:
        return self._selection_overview_helper._accumulate_daily_event_invested_ratio(
            record=record,
            initial_capital=initial_capital,
            invested_ratios=invested_ratios,
            ticker_max_unrealized=ticker_max_unrealized,
        )

    def _accumulate_daily_event_record(
        self,
        record: dict[str, Any],
        *,
        initial_capital: float,
        layer_b_values: list[float],
        watchlist_values: list[float],
        buy_order_values: list[float],
        buy_blockers: Counter[str],
        watch_blockers: Counter[str],
        invested_ratios: list[float],
        ticker_buy_counts: Counter[str],
        ticker_sell_counts: Counter[str],
        ticker_max_unrealized: defaultdict[str, float],
    ) -> float:
        return self._selection_overview_helper._accumulate_daily_event_record(
            record,
            initial_capital=initial_capital,
            layer_b_values=layer_b_values,
            watchlist_values=watchlist_values,
            buy_order_values=buy_order_values,
            buy_blockers=buy_blockers,
            watch_blockers=watch_blockers,
            invested_ratios=invested_ratios,
            ticker_buy_counts=ticker_buy_counts,
            ticker_sell_counts=ticker_sell_counts,
            ticker_max_unrealized=ticker_max_unrealized,
        )

    def _extract_invested_value(
        self,
        *,
        record: dict[str, Any],
        ticker_max_unrealized: defaultdict[str, float],
    ) -> float:
        return self._selection_overview_helper._extract_invested_value(
            record=record,
            ticker_max_unrealized=ticker_max_unrealized,
        )

    def _accumulate_decision_counts(
        self,
        decisions: dict[str, Any],
        ticker_buy_counts: Counter[str],
        ticker_sell_counts: Counter[str],
    ) -> None:
        self._selection_overview_helper._accumulate_decision_counts(
            decisions,
            ticker_buy_counts,
            ticker_sell_counts,
        )

    def _build_daily_event_ticker_digests(
        self,
        *,
        ticker_buy_counts: Counter[str],
        ticker_sell_counts: Counter[str],
        ticker_max_unrealized: defaultdict[str, float],
        final_snapshot: dict[str, Any],
        realized_gains: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return self._selection_overview_helper._build_daily_event_ticker_digests(
            ticker_buy_counts=ticker_buy_counts,
            ticker_sell_counts=ticker_sell_counts,
            ticker_max_unrealized=ticker_max_unrealized,
            final_snapshot=final_snapshot,
            realized_gains=realized_gains,
        )

    def _derive_daily_event_metrics(self, daily_events: list[dict[str, Any]], session_summary: dict[str, Any]) -> dict[str, Any]:
        return self._selection_overview_helper._derive_daily_event_metrics(
            daily_events,
            session_summary,
        )

    def _accumulate_target_summary_metadata(
        self,
        target_summary: dict[str, Any],
        aggregated_counts: Counter[str],
        delta_classification_counts: Counter[str],
    ) -> None:
        for field_name in [
            "selection_target_count",
            "research_target_count",
            "short_trade_target_count",
            "research_selected_count",
            "research_near_miss_count",
            "research_rejected_count",
            "short_trade_selected_count",
            "short_trade_near_miss_count",
            "short_trade_blocked_count",
            "short_trade_rejected_count",
            "shell_target_count",
        ]:
            field_value = target_summary.get(field_name)
            if field_value is not None:
                aggregated_counts[field_name] += int(field_value)

        for delta_name, delta_count in (target_summary.get("delta_classification_counts") or {}).items():
            delta_classification_counts[str(delta_name)] += int(delta_count)

    def _accumulate_dual_target_delta_metadata(
        self,
        trade_date: str,
        dual_target_delta: dict[str, Any],
        delta_classification_counts: Counter[str],
        dominant_delta_reason_counts: Counter[str],
        representative_cases: list[dict[str, Any]],
    ) -> None:
        for delta_name, delta_count in (dual_target_delta.get("delta_counts") or {}).items():
            delta_classification_counts[str(delta_name)] += int(delta_count)
        for reason in dual_target_delta.get("dominant_delta_reasons") or []:
            dominant_delta_reason_counts[str(reason)] += 1
        for case_item in dual_target_delta.get("representative_cases") or []:
            if not isinstance(case_item, dict):
                continue
            representative_cases.append(
                {
                    "trade_date": trade_date,
                    "ticker": case_item.get("ticker"),
                    "delta_classification": case_item.get("delta_classification"),
                    "research_decision": case_item.get("research_decision"),
                    "short_trade_decision": case_item.get("short_trade_decision"),
                    "delta_summary": case_item.get("delta_summary") or [],
                }
            )

    def _derive_runtime_metrics(self, pipeline_timings: list[dict[str, Any]]) -> dict[str, Any]:
        return self._selection_overview_helper._derive_runtime_metrics(pipeline_timings)

    def _derive_cache_benchmark_overview(self, session_summary: dict[str, Any]) -> dict[str, Any]:
        return self._summary_helper.derive_cache_benchmark_overview(session_summary)

    def _derive_btst_followup_overview(self, session_summary: dict[str, Any]) -> dict[str, Any] | None:
        return self._summary_helper.derive_btst_followup_overview(session_summary)

    def _extract_btst_followup_entries(self, brief_payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        return self._summary_helper._extract_btst_followup_entries(brief_payload)

    def _summarize_btst_followup_entries(self, entries: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        return self._summary_helper._summarize_btst_followup_entries(entries)

    def _build_btst_replay_context_index(self, *, preferred_report_names: list[str] | None = None) -> dict[str, dict[str, Any]]:
        return self._summary_helper._build_btst_replay_context_index(preferred_report_names=preferred_report_names)

    def _derive_btst_rollout_lane_rows(
        self,
        governance_synthesis_payload: dict[str, Any],
        *,
        resolve_contexts: bool,
        preferred_report_names: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return self._summary_helper._derive_btst_rollout_lane_rows(
            governance_synthesis_payload,
            resolve_contexts=resolve_contexts,
            preferred_report_names=preferred_report_names,
        )

    def _build_btst_control_tower_artifacts(
        self,
        *,
        paths: dict[str, Path],
        source_paths: dict[str, Any],
        governance_source_reports: dict[str, Any],
    ) -> dict[str, Any]:
        return self._summary_helper._build_btst_control_tower_artifacts(
            paths=paths,
            source_paths=source_paths,
            governance_source_reports=governance_source_reports,
        )

    def _derive_btst_control_tower_overview(self, report_dir: Path, *, resolve_contexts: bool = False) -> dict[str, Any] | None:
        return self._summary_helper.derive_btst_control_tower_overview(
            report_dir,
            resolve_contexts=resolve_contexts,
        )

    def _build_unavailable_selection_artifact_overview(
        self,
        report_dir: Path,
        session_summary: dict[str, Any],
        *,
        resolve_btst_contexts: bool,
    ) -> dict[str, Any]:
        return self._selection_overview_helper._build_unavailable_selection_artifact_overview(
            report_dir,
            session_summary,
            resolve_btst_contexts=resolve_btst_contexts,
        )

    def _count_selection_artifact_write_statuses(self, daily_events: list[dict[str, Any]]) -> Counter[str]:
        return self._selection_overview_helper._count_selection_artifact_write_statuses(daily_events)

    def _collect_selection_artifact_snapshots(
        self,
        artifact_root: Path,
    ) -> tuple[list[str], Counter[str], list[tuple[str, dict[str, Any]]]]:
        return self._selection_overview_helper._collect_selection_artifact_snapshots(artifact_root)

    def _read_selection_feedback_summary(self, artifact_root: Path) -> dict[str, Any] | None:
        return self._selection_overview_helper._read_selection_feedback_summary(artifact_root)

    def _derive_selection_artifact_overview(
        self,
        report_dir: Path,
        session_summary: dict[str, Any],
        daily_events: list[dict[str, Any]],
        *,
        resolve_btst_contexts: bool = False,
    ) -> dict[str, Any]:
        return self._selection_overview_helper.derive_selection_artifact_overview(
            report_dir,
            session_summary,
            daily_events,
            resolve_btst_contexts=resolve_btst_contexts,
        )

    def _merge_trade_date_delta_counts(
        self,
        target_summary: dict[str, Any],
        dual_target_delta: dict[str, Any],
    ) -> dict[str, int]:
        return self._selection_overview_helper._merge_trade_date_delta_counts(
            target_summary,
            dual_target_delta,
        )

    def _build_trade_date_target_counts(self, target_summary: dict[str, Any]) -> dict[str, int]:
        return self._selection_overview_helper._build_trade_date_target_counts(target_summary)

    def _build_trade_date_target_index_row(
        self,
        trade_date: str,
        snapshot: dict[str, Any],
        target_summary: dict[str, Any],
        delta_counts: dict[str, int],
    ) -> dict[str, Any]:
        return self._selection_overview_helper._build_trade_date_target_index_row(
            trade_date,
            snapshot,
            target_summary,
            delta_counts,
        )

    def _derive_trade_date_target_index(self, snapshots_by_trade_date: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
        return self._selection_overview_helper.derive_trade_date_target_index(snapshots_by_trade_date)

    def _extract_short_trade_profile_payload(self, snapshot: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
        return self._selection_overview_helper._extract_short_trade_profile_payload(snapshot)

    def _extract_short_trade_profile_name(self, snapshot: dict[str, Any]) -> str | None:
        return self._selection_overview_helper._extract_short_trade_profile_name(snapshot)

    def _derive_short_trade_profile_overview(self, snapshots_by_trade_date: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
        return self._selection_overview_helper._derive_short_trade_profile_overview(snapshots_by_trade_date)

    def _initialize_dual_target_overview_state(self) -> dict[str, Any]:
        return self._selection_overview_helper._initialize_dual_target_overview_state()

    def _accumulate_dual_target_overview_snapshot(
        self,
        *,
        trade_date: str,
        snapshot: dict[str, Any],
        state: dict[str, Any],
    ) -> None:
        self._selection_overview_helper._accumulate_dual_target_overview_snapshot(
            trade_date=trade_date,
            snapshot=snapshot,
            state=state,
        )

    def _build_dual_target_overview_from_state(self, state: dict[str, Any]) -> dict[str, Any] | None:
        return self._selection_overview_helper._build_dual_target_overview_from_state(state)

    def _derive_dual_target_overview(self, snapshots_by_trade_date: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
        return self._selection_overview_helper._derive_dual_target_overview(snapshots_by_trade_date)

    def _get_report_dir(self, report_name: str) -> Path:
        return self._ledger_io_helper._get_report_dir(report_name)

    def _sync_feedback_ledger(self, *, report_name: str | None = None) -> None:
        self._ledger_io_helper._sync_feedback_ledger(report_name=report_name)

    def _feedback_record_key(self, *, report_name: str, trade_date: str, record: ResearchFeedbackRecord) -> tuple[str, str, str, str, str, datetime]:
        return self._ledger_io_helper._feedback_record_key(report_name=report_name, trade_date=trade_date, record=record)

    def _sync_feedback_ledger_for_day(
        self,
        *,
        report_name: str,
        trade_date: str,
        feedback_path: Path,
        records: list[ResearchFeedbackRecord],
    ) -> None:
        self._ledger_io_helper._sync_feedback_ledger_for_day(report_name=report_name, trade_date=trade_date, feedback_path=feedback_path, records=records)

    def _resolve_selection_artifact_root(self, report_dir: Path, session_summary: dict[str, Any]) -> Path | None:
        return self._ledger_io_helper._resolve_selection_artifact_root(report_dir, session_summary)

    def _read_json(self, path: Path) -> dict[str, Any]:
        return self._ledger_io_helper._read_json(path)

    def _read_text(self, path: Path) -> str:
        return self._ledger_io_helper._read_text(path)

    def _ensure_feedback_ledger_table(self) -> None:
        self._ledger_io_helper._ensure_feedback_ledger_table()

    def _normalize_feedback_created_at(self, value: Any) -> datetime:
        return self._ledger_io_helper._normalize_feedback_created_at(value)

    def _db_session(self) -> Any:
        return self._ledger_io_helper._db_session()

    def _sync_session_feedback_summary(self, *, report_dir: Path, directory_summary: Any, summary_path: Path) -> None:
        self._ledger_io_helper._sync_session_feedback_summary(report_dir=report_dir, directory_summary=directory_summary, summary_path=summary_path)

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        return self._ledger_io_helper._read_jsonl(path)

    def _safe_average(self, values: list[float]) -> float | None:
        if not values:
            return None
        return sum(values) / len(values)

    def _counter_to_list(self, counter: Counter[str], limit: int = 5) -> list[dict[str, Any]]:
        return [{"reason": reason, "count": count} for reason, count in counter.most_common(limit)]
