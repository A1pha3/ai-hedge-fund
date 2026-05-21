from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.btst_trend_continuation_rollout_helpers import (
    build_trend_continuation_rollout_assessment,
    render_trend_continuation_rollout_assessment_markdown,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a governed rollout assessment for BTST trend continuation strength variants.")
    parser.add_argument("--input-json", required=True, help="Path to the multi-window validation JSON")
    parser.add_argument("--diagnostics-json", default=None, help="Optional activation-delta diagnostics JSON")
    parser.add_argument("--calibration-json", default=None, help="Optional activation-delta calibration JSON")
    parser.add_argument("--output-json", required=True, help="Path to write the rollout assessment JSON")
    parser.add_argument("--output-md", required=True, help="Path to write the rollout assessment Markdown")
    args = parser.parse_args(argv)

    analysis = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    diagnostics = json.loads(Path(args.diagnostics_json).read_text(encoding="utf-8")) if args.diagnostics_json else None
    calibration = json.loads(Path(args.calibration_json).read_text(encoding="utf-8")) if args.calibration_json else None
    payload = build_trend_continuation_rollout_assessment(
        analysis,
        activation_delta_diagnostics=diagnostics,
        activation_delta_calibration=calibration,
    )

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    output_md.write_text(render_trend_continuation_rollout_assessment_markdown(payload), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
