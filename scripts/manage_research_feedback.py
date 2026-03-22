from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from src.research.feedback import append_research_feedback, summarize_research_feedback
from src.research.models import RESEARCH_FEEDBACK_LABEL_VERSION, ResearchFeedbackRecord


def _normalize_trade_date(trade_date: str) -> str:
    normalized = str(trade_date).strip()
    if len(normalized) == 8 and normalized.isdigit():
        return f"{normalized[:4]}-{normalized[4:6]}-{normalized[6:8]}"
    return normalized


def _resolve_feedback_path(*, feedback_file: str | None, artifact_dir: str | None, trade_date: str | None) -> Path:
    if feedback_file:
        return Path(feedback_file)
    if not artifact_dir:
        raise ValueError("Either --feedback-file or --artifact-dir must be provided")
    if not trade_date:
        raise ValueError("--trade-date is required when using --artifact-dir")
    return Path(artifact_dir) / _normalize_trade_date(trade_date) / "research_feedback.jsonl"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Append and summarize research_feedback.jsonl artifacts.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    append_parser = subparsers.add_parser("append", help="Append one structured research feedback record")
    append_parser.add_argument("--feedback-file", default=None, help="Direct path to research_feedback.jsonl")
    append_parser.add_argument("--artifact-dir", default=None, help="selection_artifacts root directory")
    append_parser.add_argument("--trade-date", required=True, help="Trade date in YYYY-MM-DD or YYYYMMDD format")
    append_parser.add_argument("--run-id", required=True)
    append_parser.add_argument("--symbol", required=True)
    append_parser.add_argument("--reviewer", required=True)
    append_parser.add_argument("--primary-tag", required=True)
    append_parser.add_argument("--research-verdict", required=True)
    append_parser.add_argument("--tag", action="append", default=[], help="Additional tag; may be passed multiple times")
    append_parser.add_argument("--review-status", default="draft")
    append_parser.add_argument("--review-scope", default="watchlist")
    append_parser.add_argument("--confidence", type=float, default=0.0)
    append_parser.add_argument("--notes", default="")
    append_parser.add_argument("--artifact-version", default="v1")
    append_parser.add_argument("--feedback-version", default="v1")
    append_parser.add_argument("--label-version", default=RESEARCH_FEEDBACK_LABEL_VERSION)
    append_parser.add_argument("--created-at", default=None, help="ISO timestamp; default is current local time")

    summarize_parser = subparsers.add_parser("summarize", help="Summarize a research_feedback.jsonl file")
    summarize_parser.add_argument("--feedback-file", default=None, help="Direct path to research_feedback.jsonl")
    summarize_parser.add_argument("--artifact-dir", default=None, help="selection_artifacts root directory")
    summarize_parser.add_argument("--trade-date", default=None, help="Trade date in YYYY-MM-DD or YYYYMMDD format")
    summarize_parser.add_argument("--skip-invalid", action="store_true")
    summarize_parser.add_argument("--output", default=None, help="Optional path to save summary JSON")
    return parser


def _append_command(args: argparse.Namespace) -> dict:
    feedback_path = _resolve_feedback_path(feedback_file=args.feedback_file, artifact_dir=args.artifact_dir, trade_date=args.trade_date)
    record = ResearchFeedbackRecord(
        feedback_version=args.feedback_version,
        artifact_version=args.artifact_version,
        label_version=args.label_version,
        run_id=args.run_id,
        trade_date=_normalize_trade_date(args.trade_date),
        symbol=args.symbol,
        review_scope=args.review_scope,
        reviewer=args.reviewer,
        review_status=args.review_status,
        primary_tag=args.primary_tag,
        tags=list(args.tag or []),
        confidence=args.confidence,
        research_verdict=args.research_verdict,
        notes=args.notes,
        created_at=args.created_at or datetime.now().astimezone().isoformat(timespec="seconds"),
    )
    append_research_feedback(file_path=feedback_path, record=record)
    return {
        "command": "append",
        "feedback_file": str(feedback_path),
        "record": record.model_dump(mode="json"),
    }


def _summarize_command(args: argparse.Namespace) -> dict:
    feedback_path = _resolve_feedback_path(feedback_file=args.feedback_file, artifact_dir=args.artifact_dir, trade_date=args.trade_date)
    summary = summarize_research_feedback(file_path=feedback_path, skip_invalid=args.skip_invalid)
    payload = summary.model_dump(mode="json")
    payload["feedback_file"] = str(feedback_path)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if args.command == "append":
        result = _append_command(args)
    else:
        result = _summarize_command(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()