from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


class ReplayArtifactService:
    def __init__(self) -> None:
        self._repo_root = Path(__file__).resolve().parents[3]
        self._reports_root = self._repo_root / "data" / "reports"

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
        report_dir = self._reports_root / report_name
        if not report_dir.is_dir():
            raise FileNotFoundError(f"Replay report not found: {report_name}")
        return self._build_replay_summary(report_dir, include_tickers=True)

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
        }

        if include_tickers:
            summary["ticker_execution_digest"] = derived["tickers"]
            summary["final_portfolio_snapshot"] = session_summary.get("final_portfolio_snapshot") or {}

        return summary

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

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(path)
        return json.loads(path.read_text(encoding="utf-8"))

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