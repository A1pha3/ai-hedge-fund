from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


def _generate_analysis_artifacts(
    *,
    input_path: str | Path | dict[str, Any],
    output_dir: str | Path,
    trade_date: str | None,
    next_trade_date: str | None,
    file_stem: str | None,
    analyze: Callable[..., dict[str, Any]],
    render_markdown: Callable[[dict[str, Any]], str],
    resolve_default_stem: Callable[[dict[str, Any]], str],
    write_analysis_artifacts: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    analysis = analyze(input_path=input_path, trade_date=trade_date, next_trade_date=next_trade_date)
    resolved_output_dir = Path(output_dir).expanduser().resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    stem = file_stem or resolve_default_stem(analysis)
    return write_analysis_artifacts(
        payload=analysis,
        render_markdown=render_markdown,
        resolved_output_dir=resolved_output_dir,
        stem=stem,
    )


def generate_btst_next_day_trade_brief_artifacts(
    *,
    input_path: str | Path,
    output_dir: str | Path,
    trade_date: str | None,
    next_trade_date: str | None,
    file_stem: str | None,
    analyze_btst_next_day_trade_brief: Callable[..., dict[str, Any]],
    render_btst_next_day_trade_brief_markdown: Callable[[dict[str, Any]], str],
    build_output_file_stem: Callable[[str, str | None, str | None], str],
    write_analysis_artifacts: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    return _generate_analysis_artifacts(
        input_path=input_path,
        output_dir=output_dir,
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        file_stem=file_stem,
        analyze=analyze_btst_next_day_trade_brief,
        render_markdown=render_btst_next_day_trade_brief_markdown,
        resolve_default_stem=lambda analysis: build_output_file_stem(
            "btst_next_day_trade_brief",
            analysis.get("trade_date"),
            analysis.get("next_trade_date"),
        ),
        write_analysis_artifacts=write_analysis_artifacts,
    )


def generate_btst_premarket_execution_card_artifacts(
    *,
    input_path: str | Path | dict[str, Any],
    output_dir: str | Path,
    trade_date: str | None,
    next_trade_date: str | None,
    file_stem: str | None,
    analyze_btst_premarket_execution_card: Callable[..., dict[str, Any]],
    render_btst_premarket_execution_card_markdown: Callable[[dict[str, Any]], str],
    build_output_file_stem: Callable[[str, str | None, str | None], str],
    write_analysis_artifacts: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    return _generate_analysis_artifacts(
        input_path=input_path,
        output_dir=output_dir,
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        file_stem=file_stem,
        analyze=analyze_btst_premarket_execution_card,
        render_markdown=render_btst_premarket_execution_card_markdown,
        resolve_default_stem=lambda analysis: build_output_file_stem(
            "btst_premarket_execution_card",
            analysis.get("trade_date"),
            analysis.get("next_trade_date"),
        ),
        write_analysis_artifacts=write_analysis_artifacts,
    )


def generate_btst_opening_watch_card_artifacts(
    *,
    input_path: str | Path | dict[str, Any],
    output_dir: str | Path,
    trade_date: str | None,
    next_trade_date: str | None,
    file_stem: str | None,
    analyze_btst_opening_watch_card: Callable[..., dict[str, Any]],
    render_btst_opening_watch_card_markdown: Callable[[dict[str, Any]], str],
    build_next_trade_date_file_stem: Callable[[str, str | None], str],
    write_analysis_artifacts: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    return _generate_analysis_artifacts(
        input_path=input_path,
        output_dir=output_dir,
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        file_stem=file_stem,
        analyze=analyze_btst_opening_watch_card,
        render_markdown=render_btst_opening_watch_card_markdown,
        resolve_default_stem=lambda analysis: build_next_trade_date_file_stem(
            "btst_opening_watch_card",
            analysis.get("next_trade_date"),
        ),
        write_analysis_artifacts=write_analysis_artifacts,
    )


def generate_btst_next_day_priority_board_artifacts(
    *,
    input_path: str | Path | dict[str, Any],
    output_dir: str | Path,
    trade_date: str | None,
    next_trade_date: str | None,
    file_stem: str | None,
    analyze_btst_next_day_priority_board: Callable[..., dict[str, Any]],
    render_btst_next_day_priority_board_markdown: Callable[[dict[str, Any]], str],
    build_next_trade_date_file_stem: Callable[[str, str | None], str],
    write_analysis_artifacts: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    return _generate_analysis_artifacts(
        input_path=input_path,
        output_dir=output_dir,
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        file_stem=file_stem,
        analyze=analyze_btst_next_day_priority_board,
        render_markdown=render_btst_next_day_priority_board_markdown,
        resolve_default_stem=lambda analysis: build_next_trade_date_file_stem(
            "btst_next_day_priority_board",
            analysis.get("next_trade_date"),
        ),
        write_analysis_artifacts=write_analysis_artifacts,
    )


def resolve_followup_artifact_context(
    *,
    report_dir: str | Path,
    trade_date: str | None,
    next_trade_date: str | None,
    brief_file_stem: str,
    normalize_trade_date: Callable[[str | None], str | None],
    infer_next_trade_date: Callable[[str | None], str | None],
    generate_btst_next_day_trade_brief_artifacts: Callable[..., dict[str, Any]],
) -> tuple[Path, str | None, str | None, dict[str, Any]]:
    resolved_report_dir = Path(report_dir).expanduser().resolve()
    resolved_trade_date = normalize_trade_date(trade_date)
    resolved_next_trade_date = normalize_trade_date(next_trade_date) or infer_next_trade_date(resolved_trade_date)
    brief_result = generate_btst_next_day_trade_brief_artifacts(
        input_path=resolved_report_dir,
        output_dir=resolved_report_dir,
        trade_date=resolved_trade_date,
        next_trade_date=resolved_next_trade_date,
        file_stem=brief_file_stem,
    )

    if not resolved_trade_date:
        resolved_trade_date = normalize_trade_date(brief_result["analysis"].get("trade_date"))

    if not resolved_next_trade_date:
        resolved_next_trade_date = normalize_trade_date(brief_result["analysis"].get("next_trade_date")) or infer_next_trade_date(resolved_trade_date)
        if resolved_next_trade_date:
            brief_result = generate_btst_next_day_trade_brief_artifacts(
                input_path=resolved_report_dir,
                output_dir=resolved_report_dir,
                trade_date=resolved_trade_date,
                next_trade_date=resolved_next_trade_date,
                file_stem=brief_file_stem,
            )

    return resolved_report_dir, resolved_trade_date, resolved_next_trade_date, brief_result


def register_btst_followup_artifacts(
    *,
    report_dir: str | Path,
    trade_date: str | None,
    next_trade_date: str | None,
    brief_json_path: str | Path,
    brief_markdown_path: str | Path,
    card_json_path: str | Path,
    card_markdown_path: str | Path,
    opening_card_json_path: str | Path,
    opening_card_markdown_path: str | Path,
    priority_board_json_path: str | Path,
    priority_board_markdown_path: str | Path,
    load_json: Callable[[str | Path], dict[str, Any]],
    resolve_followup_trade_dates: Callable[..., tuple[str | None, str | None]],
    sync_text_artifact_alias: Callable[[str | Path, str | Path], str],
    write_json: Callable[[str | Path, dict[str, Any]], None],
) -> dict[str, Any]:
    resolved_report_dir = Path(report_dir).expanduser().resolve()
    summary_path = resolved_report_dir / "session_summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"session_summary.json not found under: {resolved_report_dir}")

    summary = load_json(summary_path)
    resolved_trade_date, resolved_next_trade_date = resolve_followup_trade_dates(
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        brief_json_path=brief_json_path,
        card_json_path=card_json_path,
    )
    followup_manifest = _build_followup_manifest_paths(
        resolved_report_dir=resolved_report_dir,
        resolved_trade_date=resolved_trade_date,
        resolved_next_trade_date=resolved_next_trade_date,
        brief_json_path=brief_json_path,
        brief_markdown_path=brief_markdown_path,
        card_json_path=card_json_path,
        card_markdown_path=card_markdown_path,
        opening_card_json_path=opening_card_json_path,
        opening_card_markdown_path=opening_card_markdown_path,
        priority_board_json_path=priority_board_json_path,
        priority_board_markdown_path=priority_board_markdown_path,
        sync_text_artifact_alias=sync_text_artifact_alias,
    )
    summary["btst_followup"] = followup_manifest
    artifacts = dict(summary.get("artifacts") or {})
    artifacts.update(_build_followup_summary_artifacts(followup_manifest))
    summary["artifacts"] = artifacts
    write_json(summary_path, summary)
    return followup_manifest


def _build_followup_manifest_paths(
    *,
    resolved_report_dir: Path,
    resolved_trade_date: str | None,
    resolved_next_trade_date: str | None,
    brief_json_path: str | Path,
    brief_markdown_path: str | Path,
    card_json_path: str | Path,
    card_markdown_path: str | Path,
    opening_card_json_path: str | Path,
    opening_card_markdown_path: str | Path,
    priority_board_json_path: str | Path,
    priority_board_markdown_path: str | Path,
    sync_text_artifact_alias: Callable[[str | Path, str | Path], str],
) -> dict[str, Any]:
    return {
        "trade_date": resolved_trade_date,
        "next_trade_date": resolved_next_trade_date,
        "brief_json": sync_text_artifact_alias(brief_json_path, resolved_report_dir / "btst_next_day_trade_brief_latest.json"),
        "brief_markdown": sync_text_artifact_alias(brief_markdown_path, resolved_report_dir / "btst_next_day_trade_brief_latest.md"),
        "execution_card_json": sync_text_artifact_alias(card_json_path, resolved_report_dir / "btst_premarket_execution_card_latest.json"),
        "execution_card_markdown": sync_text_artifact_alias(card_markdown_path, resolved_report_dir / "btst_premarket_execution_card_latest.md"),
        "opening_watch_card_json": sync_text_artifact_alias(opening_card_json_path, resolved_report_dir / "btst_opening_watch_card_latest.json"),
        "opening_watch_card_markdown": sync_text_artifact_alias(opening_card_markdown_path, resolved_report_dir / "btst_opening_watch_card_latest.md"),
        "priority_board_json": sync_text_artifact_alias(priority_board_json_path, resolved_report_dir / "btst_next_day_priority_board_latest.json"),
        "priority_board_markdown": sync_text_artifact_alias(priority_board_markdown_path, resolved_report_dir / "btst_next_day_priority_board_latest.md"),
    }


def _build_followup_summary_artifacts(followup_manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "btst_next_day_trade_brief_json": followup_manifest["brief_json"],
        "btst_next_day_trade_brief_markdown": followup_manifest["brief_markdown"],
        "btst_premarket_execution_card_json": followup_manifest["execution_card_json"],
        "btst_premarket_execution_card_markdown": followup_manifest["execution_card_markdown"],
        "btst_opening_watch_card_json": followup_manifest["opening_watch_card_json"],
        "btst_opening_watch_card_markdown": followup_manifest["opening_watch_card_markdown"],
        "btst_next_day_priority_board_json": followup_manifest["priority_board_json"],
        "btst_next_day_priority_board_markdown": followup_manifest["priority_board_markdown"],
    }


def _build_followup_generation_payload(
    *,
    brief_result: dict[str, Any],
    card_result: dict[str, Any],
    opening_card_result: dict[str, Any],
    priority_board_result: dict[str, Any],
    followup_manifest: dict[str, Any],
) -> dict[str, Any]:
    return {
        "analysis": brief_result["analysis"],
        "execution_card": card_result["analysis"],
        "opening_watch_card": opening_card_result["analysis"],
        "priority_board": priority_board_result["analysis"],
        **followup_manifest,
    }


def generate_and_register_btst_followup_artifacts(
    *,
    report_dir: str | Path,
    trade_date: str | None,
    next_trade_date: str | None,
    brief_file_stem: str,
    card_file_stem: str,
    opening_card_file_stem: str | None,
    priority_board_file_stem: str | None,
    build_next_trade_date_file_stem: Callable[[str, str | None], str],
    resolve_followup_artifact_context: Callable[..., tuple[Path, str | None, str | None, dict[str, Any]]],
    generate_btst_premarket_execution_card_artifacts: Callable[..., dict[str, Any]],
    generate_btst_opening_watch_card_artifacts: Callable[..., dict[str, Any]],
    generate_btst_next_day_priority_board_artifacts: Callable[..., dict[str, Any]],
    register_btst_followup_artifacts: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    resolved_report_dir, resolved_trade_date, resolved_next_trade_date, brief_result = resolve_followup_artifact_context(
        report_dir=report_dir,
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        brief_file_stem=brief_file_stem,
    )

    card_result = generate_btst_premarket_execution_card_artifacts(
        input_path=brief_result["analysis"],
        output_dir=resolved_report_dir,
        trade_date=resolved_trade_date,
        next_trade_date=resolved_next_trade_date,
        file_stem=card_file_stem,
    )
    opening_card_result = generate_btst_opening_watch_card_artifacts(
        input_path=brief_result["analysis"],
        output_dir=resolved_report_dir,
        trade_date=resolved_trade_date,
        next_trade_date=resolved_next_trade_date,
        file_stem=opening_card_file_stem or build_next_trade_date_file_stem("btst_opening_watch_card", resolved_next_trade_date),
    )
    priority_board_result = generate_btst_next_day_priority_board_artifacts(
        input_path=brief_result["analysis"],
        output_dir=resolved_report_dir,
        trade_date=resolved_trade_date,
        next_trade_date=resolved_next_trade_date,
        file_stem=priority_board_file_stem or build_next_trade_date_file_stem("btst_next_day_priority_board", resolved_next_trade_date),
    )
    followup_manifest = register_btst_followup_artifacts(
        report_dir=resolved_report_dir,
        trade_date=resolved_trade_date,
        next_trade_date=resolved_next_trade_date,
        brief_json_path=brief_result["json_path"],
        brief_markdown_path=brief_result["markdown_path"],
        card_json_path=card_result["json_path"],
        card_markdown_path=card_result["markdown_path"],
        opening_card_json_path=opening_card_result["json_path"],
        opening_card_markdown_path=opening_card_result["markdown_path"],
        priority_board_json_path=priority_board_result["json_path"],
        priority_board_markdown_path=priority_board_result["markdown_path"],
    )
    return _build_followup_generation_payload(
        brief_result=brief_result,
        card_result=card_result,
        opening_card_result=opening_card_result,
        priority_board_result=priority_board_result,
        followup_manifest=followup_manifest,
    )
