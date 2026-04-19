from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.backend.services.replay_artifact_service import ReplayArtifactService


class ReplaySelectionOverviewHelper:
    def __init__(self, service: ReplayArtifactService) -> None:
        self._service = service

    def derive_trade_date_target_index(self, snapshots_by_trade_date: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
        return self._derive_trade_date_target_index(snapshots_by_trade_date)

    def derive_selection_artifact_overview(
        self,
        report_dir: Path,
        session_summary: dict[str, Any],
        daily_events: list[dict[str, Any]],
        *,
        resolve_btst_contexts: bool = False,
    ) -> dict[str, Any]:
        return self._derive_selection_artifact_overview(
            report_dir,
            session_summary,
            daily_events,
            resolve_btst_contexts=resolve_btst_contexts,
        )

    def _extract_daily_event_funnel_metrics(self, record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        current_plan = record.get("current_plan") or {}
        risk_metrics = current_plan.get("risk_metrics") or {}
        counts = risk_metrics.get("counts") or {}
        filters = (risk_metrics.get("funnel_diagnostics") or {}).get("filters") or {}
        return counts, filters

    def _accumulate_daily_event_count_values(
        self,
        counts: dict[str, Any],
        *,
        layer_b_values: list[float],
        watchlist_values: list[float],
        buy_order_values: list[float],
    ) -> None:
        count_targets = [
            ("layer_b_count", layer_b_values),
            ("watchlist_count", watchlist_values),
            ("buy_order_count", buy_order_values),
        ]
        for field_name, target in count_targets:
            field_value = counts.get(field_name)
            if field_value is not None:
                target.append(float(field_value))

    def _accumulate_daily_event_blockers(
        self,
        filters: dict[str, Any],
        *,
        buy_blockers: Counter[str],
        watch_blockers: Counter[str],
    ) -> None:
        watch_reasons = (filters.get("watchlist") or {}).get("reason_counts") or {}
        buy_reasons = (filters.get("buy_orders") or {}).get("reason_counts") or {}
        watch_blockers.update({str(key): int(value) for key, value in watch_reasons.items()})
        buy_blockers.update({str(key): int(value) for key, value in buy_reasons.items()})

    def _accumulate_daily_event_invested_ratio(
        self,
        *,
        record: dict[str, Any],
        initial_capital: float,
        invested_ratios: list[float],
        ticker_max_unrealized: defaultdict[str, float],
    ) -> float:
        invested_value = self._extract_invested_value(
            record=record,
            ticker_max_unrealized=ticker_max_unrealized,
        )
        if initial_capital <= 0:
            return 0.0

        invested_ratio = invested_value / initial_capital
        invested_ratios.append(invested_ratio)
        return invested_ratio

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
        counts, filters = self._extract_daily_event_funnel_metrics(record)
        self._accumulate_daily_event_count_values(
            counts,
            layer_b_values=layer_b_values,
            watchlist_values=watchlist_values,
            buy_order_values=buy_order_values,
        )
        self._accumulate_daily_event_blockers(
            filters,
            buy_blockers=buy_blockers,
            watch_blockers=watch_blockers,
        )
        invested_ratio = self._accumulate_daily_event_invested_ratio(
            record=record,
            initial_capital=initial_capital,
            invested_ratios=invested_ratios,
            ticker_max_unrealized=ticker_max_unrealized,
        )
        self._accumulate_decision_counts(record.get("decisions") or {}, ticker_buy_counts, ticker_sell_counts)
        return invested_ratio

    def _extract_invested_value(
        self,
        *,
        record: dict[str, Any],
        ticker_max_unrealized: defaultdict[str, float],
    ) -> float:
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

        return invested_value

    def _accumulate_decision_counts(
        self,
        decisions: dict[str, Any],
        ticker_buy_counts: Counter[str],
        ticker_sell_counts: Counter[str],
    ) -> None:
        for ticker, decision in decisions.items():
            if not isinstance(decision, dict):
                continue
            action = decision.get("action")
            if action == "buy":
                ticker_buy_counts[ticker] += 1
            elif action == "sell":
                ticker_sell_counts[ticker] += 1

    def _build_daily_event_ticker_digests(
        self,
        *,
        ticker_buy_counts: Counter[str],
        ticker_sell_counts: Counter[str],
        ticker_max_unrealized: defaultdict[str, float],
        final_snapshot: dict[str, Any],
        realized_gains: dict[str, Any],
    ) -> list[dict[str, Any]]:
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
        return ticker_digests

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
            peak_invested_ratio = max(
                peak_invested_ratio,
                self._accumulate_daily_event_record(
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
                ),
            )

        return {
            "funnel": {
                "avg_invested_ratio": self._service._safe_average(invested_ratios),
                "peak_invested_ratio": peak_invested_ratio,
                "avg_layer_b_count": self._service._safe_average(layer_b_values),
                "avg_watchlist_count": self._service._safe_average(watchlist_values),
                "avg_buy_order_count": self._service._safe_average(buy_order_values),
                "top_buy_blockers": self._service._counter_to_list(buy_blockers),
                "top_watchlist_blockers": self._service._counter_to_list(watch_blockers),
            },
            "tickers": self._build_daily_event_ticker_digests(
                ticker_buy_counts=ticker_buy_counts,
                ticker_sell_counts=ticker_sell_counts,
                ticker_max_unrealized=ticker_max_unrealized,
                final_snapshot=final_snapshot,
                realized_gains=realized_gains,
            ),
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
            "avg_total_day_seconds": self._service._safe_average(total_day_seconds),
            "avg_post_market_seconds": self._service._safe_average(post_market_seconds),
        }

    def _build_unavailable_selection_artifact_overview(
        self,
        report_dir: Path,
        session_summary: dict[str, Any],
        *,
        resolve_btst_contexts: bool,
    ) -> dict[str, Any]:
        return {
            "available": False,
            "trade_date_count": 0,
            "available_trade_dates": [],
            "trade_date_target_index": [],
            "write_status_counts": {},
            "blocker_counts": [],
            "short_trade_profile_overview": None,
            "dual_target_overview": None,
            "feedback_summary": None,
            "btst_followup_overview": self._service._derive_btst_followup_overview(session_summary),
            "btst_control_tower_overview": self._service._derive_btst_control_tower_overview(report_dir, resolve_contexts=resolve_btst_contexts),
        }

    def _count_selection_artifact_write_statuses(self, daily_events: list[dict[str, Any]]) -> Counter[str]:
        write_status_counts: Counter[str] = Counter()
        for record in daily_events:
            selection_artifacts = (record.get("current_plan") or {}).get("selection_artifacts") or record.get("selection_artifacts") or {}
            write_status = selection_artifacts.get("write_status")
            if write_status:
                write_status_counts[str(write_status)] += 1
        return write_status_counts

    def _collect_selection_artifact_snapshots(
        self,
        artifact_root: Path,
    ) -> tuple[list[str], Counter[str], list[tuple[str, dict[str, Any]]]]:
        trade_dates: list[str] = []
        blocker_counts: Counter[str] = Counter()
        snapshots_by_trade_date: list[tuple[str, dict[str, Any]]] = []

        for day_dir in sorted(path for path in artifact_root.iterdir() if path.is_dir()):
            snapshot_path = day_dir / "selection_snapshot.json"
            if not snapshot_path.exists():
                continue
            trade_dates.append(day_dir.name)
            snapshot = self._service._read_json(snapshot_path)
            snapshots_by_trade_date.append((day_dir.name, snapshot))
            for candidate in snapshot.get("selected") or []:
                if not isinstance(candidate, dict):
                    continue
                execution_bridge = candidate.get("execution_bridge") or {}
                block_reason = execution_bridge.get("block_reason")
                if block_reason:
                    blocker_counts[str(block_reason)] += 1

        return trade_dates, blocker_counts, snapshots_by_trade_date

    def _read_selection_feedback_summary(self, artifact_root: Path) -> dict[str, Any] | None:
        feedback_summary_path = artifact_root / "research_feedback_summary.json"
        return self._service._read_json(feedback_summary_path) if feedback_summary_path.exists() else None

    def _derive_selection_artifact_overview(
        self,
        report_dir: Path,
        session_summary: dict[str, Any],
        daily_events: list[dict[str, Any]],
        *,
        resolve_btst_contexts: bool = False,
    ) -> dict[str, Any]:
        artifact_root = self._service._resolve_selection_artifact_root(report_dir, session_summary)
        if artifact_root is None or not artifact_root.exists():
            return self._build_unavailable_selection_artifact_overview(
                report_dir,
                session_summary,
                resolve_btst_contexts=resolve_btst_contexts,
            )

        write_status_counts = self._count_selection_artifact_write_statuses(daily_events)
        trade_dates, blocker_counts, snapshots_by_trade_date = self._collect_selection_artifact_snapshots(artifact_root)
        feedback_summary = self._read_selection_feedback_summary(artifact_root)

        return {
            "available": True,
            "artifact_root": str(artifact_root),
            "trade_date_count": len(trade_dates),
            "available_trade_dates": trade_dates,
            "trade_date_target_index": self._derive_trade_date_target_index(snapshots_by_trade_date),
            "write_status_counts": dict(write_status_counts),
            "blocker_counts": self._service._counter_to_list(blocker_counts),
            "short_trade_profile_overview": self._derive_short_trade_profile_overview(snapshots_by_trade_date),
            "dual_target_overview": self._derive_dual_target_overview(snapshots_by_trade_date),
            "feedback_summary": feedback_summary,
            "btst_followup_overview": self._service._derive_btst_followup_overview(session_summary),
            "btst_control_tower_overview": self._service._derive_btst_control_tower_overview(report_dir, resolve_contexts=resolve_btst_contexts),
        }

    def _merge_trade_date_delta_counts(
        self,
        target_summary: dict[str, Any],
        dual_target_delta: dict[str, Any],
    ) -> dict[str, int]:
        delta_counts = dict(target_summary.get("delta_classification_counts") or {})
        for delta_name, delta_count in (dual_target_delta.get("delta_counts") or {}).items():
            delta_key = str(delta_name)
            delta_counts[delta_key] = int(delta_counts.get(delta_key, 0)) + int(delta_count)
        return delta_counts

    def _build_trade_date_target_counts(self, target_summary: dict[str, Any]) -> dict[str, int]:
        return {
            "research_selected_count": int(target_summary.get("research_selected_count") or 0),
            "research_near_miss_count": int(target_summary.get("research_near_miss_count") or 0),
            "short_trade_selected_count": int(target_summary.get("short_trade_selected_count") or 0),
            "short_trade_blocked_count": int(target_summary.get("short_trade_blocked_count") or 0),
        }

    def _build_trade_date_target_index_row(
        self,
        trade_date: str,
        snapshot: dict[str, Any],
        target_summary: dict[str, Any],
        delta_counts: dict[str, int],
    ) -> dict[str, Any]:
        row = {
            "trade_date": trade_date,
            "target_mode": snapshot.get("target_mode") or target_summary.get("target_mode"),
            "short_trade_profile_name": self._extract_short_trade_profile_name(snapshot),
            "delta_classification_counts": delta_counts,
        }
        row.update(self._build_trade_date_target_counts(target_summary))
        return row

    def _derive_trade_date_target_index(self, snapshots_by_trade_date: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
        index_rows: list[dict[str, Any]] = []
        for trade_date, snapshot in snapshots_by_trade_date:
            target_summary = snapshot.get("target_summary") or {}
            dual_target_delta = snapshot.get("dual_target_delta") or {}
            delta_counts = self._merge_trade_date_delta_counts(target_summary, dual_target_delta)
            index_rows.append(self._build_trade_date_target_index_row(trade_date, snapshot, target_summary, delta_counts))
        return index_rows

    def _extract_short_trade_profile_payload(self, snapshot: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
        pipeline_config = snapshot.get("pipeline_config_snapshot") or {}
        if not isinstance(pipeline_config, dict):
            return None, {}
        short_trade_profile = pipeline_config.get("short_trade_target_profile") or {}
        if not isinstance(short_trade_profile, dict):
            return None, {}
        profile_name = short_trade_profile.get("name")
        config = short_trade_profile.get("config") or {}
        return (str(profile_name) if profile_name else None), dict(config) if isinstance(config, dict) else {}

    def _extract_short_trade_profile_name(self, snapshot: dict[str, Any]) -> str | None:
        profile_name, _config = self._extract_short_trade_profile_payload(snapshot)
        return profile_name

    def _derive_short_trade_profile_overview(self, snapshots_by_trade_date: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
        profile_name_counts: Counter[str] = Counter()
        latest_profile_name: str | None = None
        latest_profile_config: dict[str, Any] | None = None
        latest_profile_trade_date: str | None = None

        for trade_date, snapshot in snapshots_by_trade_date:
            profile_name, profile_config = self._extract_short_trade_profile_payload(snapshot)
            if not profile_name:
                continue
            profile_name_counts[profile_name] += 1
            latest_profile_name = profile_name
            latest_profile_config = profile_config
            latest_profile_trade_date = trade_date

        if not profile_name_counts:
            return None

        return {
            "profile_name_counts": dict(profile_name_counts),
            "latest_profile_name": latest_profile_name,
            "latest_profile_trade_date": latest_profile_trade_date,
            "latest_profile_config": latest_profile_config or {},
        }

    def _initialize_dual_target_overview_state(self) -> dict[str, Any]:
        return {
            "target_mode_counts": Counter(),
            "delta_classification_counts": Counter(),
            "dominant_delta_reason_counts": Counter(),
            "aggregated_counts": Counter(),
            "representative_cases": [],
            "dual_target_trade_date_count": 0,
            "seen_any_target_metadata": False,
        }

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

    def _accumulate_dual_target_overview_snapshot(
        self,
        *,
        trade_date: str,
        snapshot: dict[str, Any],
        state: dict[str, Any],
    ) -> None:
        target_summary = snapshot.get("target_summary") or {}
        dual_target_delta = snapshot.get("dual_target_delta") or {}
        target_mode = snapshot.get("target_mode") or target_summary.get("target_mode")

        if target_mode:
            normalized_target_mode = str(target_mode)
            state["target_mode_counts"][normalized_target_mode] += 1
            state["seen_any_target_metadata"] = True
            if normalized_target_mode == "dual_target":
                state["dual_target_trade_date_count"] += 1

        if isinstance(target_summary, dict) and target_summary:
            state["seen_any_target_metadata"] = True
            self._accumulate_target_summary_metadata(
                target_summary,
                state["aggregated_counts"],
                state["delta_classification_counts"],
            )

        if isinstance(dual_target_delta, dict) and dual_target_delta:
            state["seen_any_target_metadata"] = True
            self._accumulate_dual_target_delta_metadata(
                trade_date,
                dual_target_delta,
                state["delta_classification_counts"],
                state["dominant_delta_reason_counts"],
                state["representative_cases"],
            )

    def _build_dual_target_overview_from_state(self, state: dict[str, Any]) -> dict[str, Any] | None:
        if not state["seen_any_target_metadata"]:
            return None

        aggregated_counts: Counter[str] = state["aggregated_counts"]
        dominant_delta_reason_counts: Counter[str] = state["dominant_delta_reason_counts"]
        return {
            "target_mode_counts": dict(state["target_mode_counts"]),
            "dual_target_trade_date_count": state["dual_target_trade_date_count"],
            "selection_target_count": aggregated_counts["selection_target_count"],
            "research_target_count": aggregated_counts["research_target_count"],
            "short_trade_target_count": aggregated_counts["short_trade_target_count"],
            "research_selected_count": aggregated_counts["research_selected_count"],
            "research_near_miss_count": aggregated_counts["research_near_miss_count"],
            "research_rejected_count": aggregated_counts["research_rejected_count"],
            "short_trade_selected_count": aggregated_counts["short_trade_selected_count"],
            "short_trade_near_miss_count": aggregated_counts["short_trade_near_miss_count"],
            "short_trade_blocked_count": aggregated_counts["short_trade_blocked_count"],
            "short_trade_rejected_count": aggregated_counts["short_trade_rejected_count"],
            "shell_target_count": aggregated_counts["shell_target_count"],
            "delta_classification_counts": dict(state["delta_classification_counts"]),
            "dominant_delta_reasons": [reason for reason, _count in dominant_delta_reason_counts.most_common(5)],
            "dominant_delta_reason_counts": dict(dominant_delta_reason_counts),
            "representative_cases": state["representative_cases"][:5],
        }

    def _derive_dual_target_overview(self, snapshots_by_trade_date: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
        state = self._initialize_dual_target_overview_state()

        for trade_date, snapshot in snapshots_by_trade_date:
            self._accumulate_dual_target_overview_snapshot(
                trade_date=trade_date,
                snapshot=snapshot,
                state=state,
            )

        return self._build_dual_target_overview_from_state(state)
