from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.btst_analysis_utils import build_surface_summary, extract_btst_price_outcome
from scripts.btst_latest_followup_utils import load_btst_followup_by_ticker_for_report
from src.paper_trading.btst_reporting import _collect_historical_watch_candidate_rows


REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_carryover_anchor_probe_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_carryover_anchor_probe_latest.md"
COUNT_KEYS = (
    "same_ticker_sample_count",
    "same_family_sample_count",
    "same_family_source_sample_count",
    "same_family_source_score_catalyst_sample_count",
    "same_source_score_sample_count",
)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _row_rank(row: dict[str, Any]) -> tuple[float, str]:
    return (_safe_float(row.get("score_target"), default=-999.0), str(row.get("report_dir") or ""))


def _dedupe_historical_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (
            str(row.get("trade_date") or ""),
            str(row.get("ticker") or ""),
            str(row.get("watch_candidate_family") or ""),
            str(row.get("candidate_source") or ""),
            str(row.get("score_bucket") or ""),
            str(row.get("catalyst_bucket") or ""),
        )
        current = deduped.get(key)
        if current is None or _row_rank(row) > _row_rank(current):
            deduped[key] = dict(row)
    return sorted(deduped.values(), key=lambda row: (str(row.get("trade_date") or ""), str(row.get("ticker") or "")))


def _find_latest_target_report_dir(reports_root: str | Path, ticker: str) -> Path:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    candidates: list[tuple[tuple[int, int, str, str], Path]] = []
    for snapshot_path in resolved_reports_root.glob("**/selection_artifacts/*/selection_snapshot.json"):
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        short_trade = dict((((snapshot.get("selection_targets") or {}).get(ticker) or {}).get("short_trade") or {}))
        if not short_trade:
            continue
        explainability = dict(short_trade.get("explainability_payload") or {})
        upstream_relief = dict(explainability.get("upstream_shadow_catalyst_relief") or {})
        rank = (
            1 if str(short_trade.get("decision") or "") == "selected" else 0,
            1 if upstream_relief.get("applied") else 0,
            str(snapshot_path.parent.name),
            str(snapshot_path.parents[2]),
        )
        candidates.append((rank, snapshot_path.parents[2]))
    if not candidates:
        raise ValueError(f"No BTST report found for ticker: {ticker}")
    return max(candidates, key=lambda item: item[0])[1]


def _attach_outcomes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    price_cache: dict[tuple[str, str], Any] = {}
    return [{**row, **extract_btst_price_outcome(str(row.get("ticker") or ""), str(row.get("trade_date") or ""), price_cache)} for row in rows]


def _summarize_anchor(anchor: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    ticker = str(anchor.get("ticker") or "")
    family = str(anchor.get("watch_candidate_family") or "")
    candidate_source = str(anchor.get("candidate_source") or "")
    score_bucket = str(anchor.get("score_bucket") or "")
    catalyst_bucket = str(anchor.get("catalyst_bucket") or "")

    same_ticker_rows = [row for row in rows if str(row.get("ticker") or "") == ticker]
    same_family_rows = [row for row in rows if str(row.get("watch_candidate_family") or "") == family]
    same_source_rows = [row for row in rows if str(row.get("candidate_source") or "") == candidate_source]
    same_family_source_rows = [row for row in same_family_rows if str(row.get("candidate_source") or "") == candidate_source]
    same_family_source_score_catalyst_rows = [
        row
        for row in same_family_source_rows
        if str(row.get("score_bucket") or "") == score_bucket and str(row.get("catalyst_bucket") or "") == catalyst_bucket
    ]
    same_source_score_rows = [row for row in same_source_rows if str(row.get("score_bucket") or "") == score_bucket]

    return {
        "anchor": anchor,
        "fingerprint": {
            "same_ticker_sample_count": len(same_ticker_rows),
            "same_family_sample_count": len(same_family_rows),
            "same_family_source_sample_count": len(same_family_source_rows),
            "same_family_source_score_catalyst_sample_count": len(same_family_source_score_catalyst_rows),
            "same_source_score_sample_count": len(same_source_score_rows),
        },
        "same_ticker_rows": same_ticker_rows,
        "same_family_source_rows": same_family_source_rows,
        "same_family_source_score_catalyst_rows": same_family_source_score_catalyst_rows,
        "same_source_score_rows": same_source_score_rows,
    }


def _fingerprint_distance(observed: dict[str, Any], target: dict[str, Any]) -> int:
    return sum(abs(int(observed.get(key) or 0) - int(target.get(key) or 0)) for key in COUNT_KEYS)


def _format_rows(rows: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    formatted_rows = _attach_outcomes(rows)
    formatted_rows.sort(
        key=lambda row: (
            float(row.get("next_high_return") if row.get("next_high_return") is not None else -999.0),
            float(row.get("next_close_return") if row.get("next_close_return") is not None else -999.0),
            float(row.get("score_target") if row.get("score_target") is not None else -999.0),
            str(row.get("trade_date") or ""),
            str(row.get("ticker") or ""),
        ),
        reverse=True,
    )
    return [
        {
            "trade_date": row.get("trade_date"),
            "ticker": row.get("ticker"),
            "watch_candidate_family": row.get("watch_candidate_family"),
            "candidate_source": row.get("candidate_source"),
            "score_bucket": row.get("score_bucket"),
            "catalyst_bucket": row.get("catalyst_bucket"),
            "decision": row.get("decision"),
            "score_target": round(_safe_float(row.get("score_target")), 4),
            "next_high_return": row.get("next_high_return"),
            "next_close_return": row.get("next_close_return"),
            "t_plus_2_close_return": row.get("t_plus_2_close_return"),
            "report_dir": row.get("report_dir"),
        }
        for row in formatted_rows[:limit]
    ]


def _build_recommendation(best_probe: dict[str, Any], target_prior: dict[str, Any]) -> str:
    if bool(best_probe.get("exact_match")) and list(best_probe.get("same_family_source_score_catalyst_rows") or []):
        top_anchor = best_probe.get("anchor") or {}
        return (
            f"已找到与当前 prior 指纹完全一致的 anchor：{top_anchor.get('ticker')}@{top_anchor.get('trade_date')}。"
            "下一步应直接审计其 same-family-source-score-catalyst peer 的 closed-cycle 质量，再决定是否进入极窄 promotion review。"
        )
    return (
        "当前没有完全重建出 backfilled prior 的原始 anchor，说明这条 carryover 链存在 source/family 漂移或跨报告回收。"
        f" 但最接近的 anchor 与目标指纹距离仅为 {best_probe.get('fingerprint_distance')}，"
        "可先以它为候选链路继续核验 peer 质量，而不是贸然放松选股阈值。"
    )


def analyze_btst_carryover_anchor_probe(
    reports_root: str | Path,
    *,
    ticker: str,
    report_dir: str | Path | None = None,
) -> dict[str, Any]:
    resolved_report_dir = Path(report_dir).expanduser().resolve() if report_dir else _find_latest_target_report_dir(reports_root, ticker)
    rows_by_ticker = load_btst_followup_by_ticker_for_report(resolved_report_dir)
    target_row = dict(rows_by_ticker.get(ticker) or {})
    if not target_row:
        raise ValueError(f"No followup row found for ticker {ticker} in report {resolved_report_dir}")
    target_prior = dict(target_row.get("historical_prior") or {})
    if not target_prior:
        raise ValueError(f"No historical prior available for ticker {ticker} in report {resolved_report_dir}")

    historical_payload = _collect_historical_watch_candidate_rows(resolved_report_dir, str(target_row.get("trade_date") or ""))
    historical_rows = _dedupe_historical_rows(list(historical_payload.get("rows") or []))
    ticker_rows = [row for row in historical_rows if str(row.get("ticker") or "") == ticker]
    if not ticker_rows:
        raise ValueError(f"No historical anchor candidates found for ticker {ticker}")

    probes: list[dict[str, Any]] = []
    for anchor in ticker_rows:
        summarized = _summarize_anchor(anchor, historical_rows)
        fingerprint_distance = _fingerprint_distance(summarized["fingerprint"], target_prior)
        probes.append(
            {
                "anchor": {
                    key: summarized["anchor"].get(key)
                    for key in ("trade_date", "ticker", "watch_candidate_family", "candidate_source", "score_bucket", "catalyst_bucket", "decision", "score_target")
                },
                "fingerprint": summarized["fingerprint"],
                "fingerprint_distance": fingerprint_distance,
                "exact_match": fingerprint_distance == 0,
                "same_family_source_surface_summary": build_surface_summary(_attach_outcomes(summarized["same_family_source_rows"]), next_high_hit_threshold=0.02),
                "same_family_source_score_catalyst_surface_summary": build_surface_summary(
                    _attach_outcomes(summarized["same_family_source_score_catalyst_rows"]),
                    next_high_hit_threshold=0.02,
                ),
                "same_source_score_surface_summary": build_surface_summary(_attach_outcomes(summarized["same_source_score_rows"]), next_high_hit_threshold=0.02),
                "same_family_source_rows": _format_rows(summarized["same_family_source_rows"]),
                "same_family_source_score_catalyst_rows": _format_rows(summarized["same_family_source_score_catalyst_rows"]),
                "same_source_score_rows": _format_rows(summarized["same_source_score_rows"]),
            }
        )

    probes.sort(
        key=lambda probe: (
            int(probe.get("fingerprint_distance") or 999),
            -int((probe.get("same_family_source_score_catalyst_surface_summary") or {}).get("total_count") or 0),
            -int((probe.get("same_family_source_surface_summary") or {}).get("total_count") or 0),
            -_safe_float((probe.get("anchor") or {}).get("score_target"), default=-999.0),
            str((probe.get("anchor") or {}).get("trade_date") or ""),
        )
    )
    best_probe = probes[0]

    return {
        "ticker": ticker,
        "report_dir": str(resolved_report_dir),
        "target_row": {
            key: target_row.get(key)
            for key in ("ticker", "decision", "candidate_source", "preferred_entry_mode", "historical_execution_quality_label", "historical_entry_timing_bias")
        },
        "target_prior_fingerprint": {key: int(target_prior.get(key) or 0) for key in COUNT_KEYS},
        "historical_candidate_count": len(historical_rows),
        "ticker_anchor_candidate_count": len(ticker_rows),
        "probes": probes[:5],
        "recommendation": _build_recommendation(best_probe, target_prior),
    }


def render_btst_carryover_anchor_probe_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Carryover Anchor Probe")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- ticker: {analysis.get('ticker')}")
    lines.append(f"- report_dir: {analysis.get('report_dir')}")
    lines.append(f"- target_row: {analysis.get('target_row')}")
    lines.append(f"- target_prior_fingerprint: {analysis.get('target_prior_fingerprint')}")
    lines.append(f"- historical_candidate_count: {analysis.get('historical_candidate_count')}")
    lines.append(f"- ticker_anchor_candidate_count: {analysis.get('ticker_anchor_candidate_count')}")
    lines.append("")
    lines.append("## Top Probes")
    for probe in list(analysis.get("probes") or []):
        lines.append(
            f"- anchor={probe.get('anchor')} fingerprint={probe.get('fingerprint')} "
            f"fingerprint_distance={probe.get('fingerprint_distance')} exact_match={probe.get('exact_match')}"
        )
        lines.append(f"  - same_family_source_surface_summary={probe.get('same_family_source_surface_summary')}")
        lines.append(f"  - same_family_source_score_catalyst_surface_summary={probe.get('same_family_source_score_catalyst_surface_summary')}")
        lines.append(f"  - same_source_score_surface_summary={probe.get('same_source_score_surface_summary')}")
        lines.append(f"  - same_family_source_score_catalyst_rows={probe.get('same_family_source_score_catalyst_rows')}")
    if not list(analysis.get("probes") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe likely historical anchor chains for BTST carryover selected priors.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR))
    parser.add_argument("--ticker", default="002001")
    parser.add_argument("--report-dir", default=None)
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_carryover_anchor_probe(args.reports_root, ticker=args.ticker, report_dir=args.report_dir)
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_carryover_anchor_probe_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
