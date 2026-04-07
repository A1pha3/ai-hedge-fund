from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPORTS_DIR = Path("data/reports")
DEFAULT_DEFAULT_MERGE_REVIEW_PATH = REPORTS_DIR / "btst_default_merge_review_latest.json"
DEFAULT_OBJECTIVE_MONITOR_PATH = REPORTS_DIR / "btst_tplus1_tplus2_objective_monitor_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_default_merge_historical_counterfactual_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_default_merge_historical_counterfactual_latest.md"


def _load_optional_json(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return {}
    return json.loads(resolved.read_text(encoding="utf-8"))


def _resolve_focus_dossier_path(reports_dir: Path, focus_ticker: str) -> Path | None:
    if not focus_ticker:
        return None
    candidate_path = reports_dir / f"btst_tplus2_candidate_dossier_{focus_ticker}_latest.json"
    return candidate_path if candidate_path.exists() else None


def _weighted_average(primary_value: float | None, primary_count: int, secondary_value: float | None, secondary_count: int) -> float | None:
    if primary_value is None or secondary_value is None or primary_count <= 0 or secondary_count <= 0:
        return None
    total_count = primary_count + secondary_count
    if total_count <= 0:
        return None
    return round((float(primary_value) * primary_count + float(secondary_value) * secondary_count) / total_count, 4)


def generate_btst_default_merge_historical_counterfactual(
    *,
    default_merge_review_path: str | Path = DEFAULT_DEFAULT_MERGE_REVIEW_PATH,
    objective_monitor_path: str | Path = DEFAULT_OBJECTIVE_MONITOR_PATH,
) -> dict[str, Any]:
    default_merge_review = _load_optional_json(default_merge_review_path)
    objective_monitor = _load_optional_json(objective_monitor_path)
    focus_ticker = str(default_merge_review.get("focus_ticker") or "").strip()
    reports_dir = Path(default_merge_review_path).expanduser().resolve().parent
    focus_dossier = _load_optional_json(_resolve_focus_dossier_path(reports_dir, focus_ticker))
    focus_support = dict(focus_dossier.get("governance_objective_support") or {})
    default_surface = dict(objective_monitor.get("tradeable_surface") or {})

    focus_closed_cycle_count = int(focus_support.get("closed_cycle_count") or 0)
    default_closed_cycle_count = int(default_surface.get("closed_cycle_count") or 0)
    focus_positive_rate = focus_support.get("t_plus_2_positive_rate")
    default_positive_rate = default_surface.get("t_plus_2_positive_rate")
    focus_mean_return = focus_support.get("mean_t_plus_2_return")
    default_mean_return = default_surface.get("mean_t_plus_2_return")

    merged_closed_cycle_count = focus_closed_cycle_count + default_closed_cycle_count
    merged_positive_rate = _weighted_average(focus_positive_rate, focus_closed_cycle_count, default_positive_rate, default_closed_cycle_count)
    merged_mean_return = _weighted_average(focus_mean_return, focus_closed_cycle_count, default_mean_return, default_closed_cycle_count)
    merged_positive_rate_uplift = round(float(merged_positive_rate) - float(default_positive_rate), 4) if merged_positive_rate is not None and default_positive_rate is not None else None
    merged_mean_return_uplift = round(float(merged_mean_return) - float(default_mean_return), 4) if merged_mean_return is not None and default_mean_return is not None else None

    if (
        str(default_merge_review.get("merge_review_verdict") or "").strip() == "ready_for_default_btst_merge_review"
        and merged_positive_rate_uplift is not None
        and merged_mean_return_uplift is not None
        and merged_positive_rate_uplift > 0
        and merged_mean_return_uplift > 0
    ):
        counterfactual_verdict = "merged_default_btst_uplift_positive"
    elif merged_positive_rate_uplift is None or merged_mean_return_uplift is None:
        counterfactual_verdict = "insufficient_historical_counterfactual_data"
    else:
        counterfactual_verdict = "merged_default_btst_uplift_mixed"

    recommendation = (
        f"若把 {focus_ticker} 代表的 continuation edge 按历史 closed-cycle 近似并入 default BTST，"
        f" merged_t_plus_2_positive_rate={merged_positive_rate}, merged_mean_t_plus_2_return={merged_mean_return},"
        f" uplift_positive_rate={merged_positive_rate_uplift}, uplift_mean_return={merged_mean_return_uplift}。"
        " 这是一份基于历史 surface 的加权近似，不替代最终治理审阅，但足以作为是否推进 merge 的赔率参考。"
        if focus_ticker
        else "当前没有 focus_ticker，无法构建 default BTST historical merge counterfactual。"
    )

    return {
        "focus_ticker": focus_ticker or None,
        "counterfactual_verdict": counterfactual_verdict,
        "merge_review_verdict": default_merge_review.get("merge_review_verdict"),
        "default_btst_surface": {
            "closed_cycle_count": default_closed_cycle_count,
            "t_plus_2_positive_rate": default_positive_rate,
            "mean_t_plus_2_return": default_mean_return,
        },
        "focus_candidate_surface": {
            "closed_cycle_count": focus_closed_cycle_count,
            "t_plus_2_positive_rate": focus_positive_rate,
            "mean_t_plus_2_return": focus_mean_return,
            "support_verdict": focus_support.get("support_verdict"),
        },
        "merged_counterfactual_surface": {
            "closed_cycle_count": merged_closed_cycle_count,
            "t_plus_2_positive_rate": merged_positive_rate,
            "mean_t_plus_2_return": merged_mean_return,
        },
        "uplift_vs_default_btst": {
            "t_plus_2_positive_rate_uplift": merged_positive_rate_uplift,
            "mean_t_plus_2_return_uplift": merged_mean_return_uplift,
        },
        "assumption_note": "Weighted historical blend assumes the focus continuation surface can be added to default BTST as an approximate incremental sleeve and does not de-duplicate overlapping samples.",
        "recommendation": recommendation,
        "source_reports": {
            "default_merge_review": str(Path(default_merge_review_path).expanduser().resolve()),
            "objective_monitor": str(Path(objective_monitor_path).expanduser().resolve()),
            "focus_dossier": str(_resolve_focus_dossier_path(reports_dir, focus_ticker)) if _resolve_focus_dossier_path(reports_dir, focus_ticker) else None,
        },
    }


def render_btst_default_merge_historical_counterfactual_markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "# BTST Default Merge Historical Counterfactual",
        "",
        "## Overview",
        f"- focus_ticker: {analysis.get('focus_ticker')}",
        f"- counterfactual_verdict: {analysis.get('counterfactual_verdict')}",
        f"- merge_review_verdict: {analysis.get('merge_review_verdict')}",
        f"- default_btst_surface: {analysis.get('default_btst_surface')}",
        f"- focus_candidate_surface: {analysis.get('focus_candidate_surface')}",
        f"- merged_counterfactual_surface: {analysis.get('merged_counterfactual_surface')}",
        f"- uplift_vs_default_btst: {analysis.get('uplift_vs_default_btst')}",
        f"- assumption_note: {analysis.get('assumption_note')}",
        "",
        "## Recommendation",
        f"- {analysis.get('recommendation')}",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a historical default-BTST merge counterfactual for the current continuation focus ticker.")
    parser.add_argument("--default-merge-review-path", default=str(DEFAULT_DEFAULT_MERGE_REVIEW_PATH))
    parser.add_argument("--objective-monitor-path", default=str(DEFAULT_OBJECTIVE_MONITOR_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = generate_btst_default_merge_historical_counterfactual(
        default_merge_review_path=args.default_merge_review_path,
        objective_monitor_path=args.objective_monitor_path,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_default_merge_historical_counterfactual_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
