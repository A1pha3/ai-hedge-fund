# isort: skip_file
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.analyze_btst_5d_15pct_boundary_contract_inspection import (
    DEFAULT_OUTPUT_JSON as DEFAULT_BOUNDARY_OUTPUT_JSON,
    DEFAULT_OUTPUT_MD as DEFAULT_BOUNDARY_OUTPUT_MD,
    analyze_btst_5d_15pct_boundary_contract_inspection,
    render_btst_5d_15pct_boundary_contract_inspection_markdown,
)
from scripts.analyze_btst_5d_15pct_trend_gate_oos_validation import (
    DEFAULT_OUTPUT_JSON as DEFAULT_TREND_OUTPUT_JSON,
    DEFAULT_OUTPUT_MD as DEFAULT_TREND_OUTPUT_MD,
    analyze_btst_5d_15pct_trend_gate_oos_validation,
    render_btst_5d_15pct_trend_gate_oos_validation_markdown,
)


def refresh_btst_5d_15pct_priors(
    reports_root: str | Path,
    *,
    boundary_output_json: str | Path = DEFAULT_BOUNDARY_OUTPUT_JSON,
    boundary_output_md: str | Path = DEFAULT_BOUNDARY_OUTPUT_MD,
    trend_output_json: str | Path = DEFAULT_TREND_OUTPUT_JSON,
    trend_output_md: str | Path = DEFAULT_TREND_OUTPUT_MD,
) -> dict[str, Any]:
    """Refresh the 5D/+15% runtime prior artifacts consumed by BTST reporting.

    This is a convenience wrapper that runs both:
      - boundary contract inspection
      - trend gate OOS validation

    and writes their *_latest.json/*.md outputs.
    """

    resolved_root = Path(reports_root).expanduser().resolve()
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    boundary = analyze_btst_5d_15pct_boundary_contract_inspection(resolved_root)
    trend = analyze_btst_5d_15pct_trend_gate_oos_validation(resolved_root)

    boundary_json = Path(boundary_output_json).expanduser().resolve()
    boundary_md = Path(boundary_output_md).expanduser().resolve()
    trend_json = Path(trend_output_json).expanduser().resolve()
    trend_md = Path(trend_output_md).expanduser().resolve()

    for path in (boundary_json, boundary_md, trend_json, trend_md):
        path.parent.mkdir(parents=True, exist_ok=True)

    boundary_json.write_text(json.dumps(boundary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    boundary_md.write_text(render_btst_5d_15pct_boundary_contract_inspection_markdown(boundary), encoding="utf-8")

    trend_json.write_text(json.dumps(trend, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    trend_md.write_text(render_btst_5d_15pct_trend_gate_oos_validation_markdown(trend), encoding="utf-8")

    return {
        "report_type": "refresh_btst_5d_15pct_priors",
        "generated_at": generated_at,
        "reports_root": str(resolved_root),
        "artifacts": {
            "boundary": {
                "json_path": str(boundary_json),
                "md_path": str(boundary_md),
                "boundary_row_count": boundary.get("boundary_row_count"),
            },
            "trend_gate_oos": {
                "json_path": str(trend_json),
                "md_path": str(trend_md),
                "candidate_unique_closed_cycle_count": (trend.get("candidate_summary") or {}).get("closed_cycle_count"),
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh BTST 5D/+15% prior artifacts (boundary + trend gate) into *_latest.json/*.md."
    )
    parser.add_argument("--reports-root", default="data/reports")
    parser.add_argument("--boundary-output-json", default=str(DEFAULT_BOUNDARY_OUTPUT_JSON))
    parser.add_argument("--boundary-output-md", default=str(DEFAULT_BOUNDARY_OUTPUT_MD))
    parser.add_argument("--trend-output-json", default=str(DEFAULT_TREND_OUTPUT_JSON))
    parser.add_argument("--trend-output-md", default=str(DEFAULT_TREND_OUTPUT_MD))
    args = parser.parse_args()

    payload = refresh_btst_5d_15pct_priors(
        args.reports_root,
        boundary_output_json=args.boundary_output_json,
        boundary_output_md=args.boundary_output_md,
        trend_output_json=args.trend_output_json,
        trend_output_md=args.trend_output_md,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
