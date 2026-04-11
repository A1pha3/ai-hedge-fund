from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any


ResolveOutputPaths = Callable[..., dict[str, Path]]
GenerateManifestArtifacts = Callable[..., dict[str, Any]]
BuildNightlyPayload = Callable[[dict[str, Any]], dict[str, Any]]
LoadArchivedPayloads = Callable[[Path], list[tuple[dict[str, Any], Path | None]]]
BuildOpenReadyDeltaPayload = Callable[..., dict[str, Any]]
RenderMarkdown = Callable[..., str]
GenerateCloseValidationArtifacts = Callable[..., dict[str, Any]]
ArchiveNightlyPayload = Callable[[dict[str, Any], Path], str | None]


def _write_json_artifact(output_path: Path, payload: dict[str, Any]) -> None:
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_markdown_artifact(output_path: Path, markdown: str) -> None:
    output_path.write_text(markdown, encoding="utf-8")


def _write_nightly_artifact_bundle(
    *,
    payload: dict[str, Any],
    delta_payload: dict[str, Any],
    output_json: Path,
    output_md: Path,
    delta_output_json: Path,
    delta_output_md: Path,
    render_btst_open_ready_delta_markdown: RenderMarkdown,
    render_btst_nightly_control_tower_markdown: RenderMarkdown,
) -> None:
    _write_json_artifact(delta_output_json, delta_payload)
    _write_markdown_artifact(
        delta_output_md,
        render_btst_open_ready_delta_markdown(delta_payload, output_parent=delta_output_md.parent),
    )
    _write_json_artifact(output_json, payload)
    _write_markdown_artifact(
        output_md,
        render_btst_nightly_control_tower_markdown(payload, output_parent=output_md.parent),
    )


def resolve_nightly_control_tower_output_paths(
    *,
    resolved_reports_root: Path,
    output_json: str | Path | None,
    output_md: str | Path | None,
    delta_output_json: str | Path | None,
    delta_output_md: str | Path | None,
    close_validation_output_json: str | Path | None,
    close_validation_output_md: str | Path | None,
    history_dir: str | Path | None,
    default_output_json: Path,
    default_output_md: Path,
    default_delta_json: Path,
    default_delta_md: Path,
    default_close_validation_json: Path,
    default_close_validation_md: Path,
    default_history_dir: Path,
    reports_dir: Path,
) -> dict[str, Path]:
    return {
        "resolved_output_json": Path(output_json).expanduser().resolve() if output_json else (resolved_reports_root / default_output_json.name).resolve(),
        "resolved_output_md": Path(output_md).expanduser().resolve() if output_md else (resolved_reports_root / default_output_md.name).resolve(),
        "resolved_delta_output_json": Path(delta_output_json).expanduser().resolve() if delta_output_json else (resolved_reports_root / default_delta_json.name).resolve(),
        "resolved_delta_output_md": Path(delta_output_md).expanduser().resolve() if delta_output_md else (resolved_reports_root / default_delta_md.name).resolve(),
        "resolved_close_validation_output_json": Path(close_validation_output_json).expanduser().resolve() if close_validation_output_json else (resolved_reports_root / default_close_validation_json.name).resolve(),
        "resolved_close_validation_output_md": Path(close_validation_output_md).expanduser().resolve() if close_validation_output_md else (resolved_reports_root / default_close_validation_md.name).resolve(),
        "resolved_history_dir": Path(history_dir).expanduser().resolve() if history_dir else (resolved_reports_root / default_history_dir.relative_to(reports_dir)).resolve(),
    }


def generate_btst_nightly_control_tower_artifacts(
    reports_root: str | Path,
    *,
    output_json: str | Path | None = None,
    output_md: str | Path | None = None,
    delta_output_json: str | Path | None = None,
    delta_output_md: str | Path | None = None,
    close_validation_output_json: str | Path | None = None,
    close_validation_output_md: str | Path | None = None,
    history_dir: str | Path | None = None,
    resolve_output_paths: ResolveOutputPaths,
    generate_reports_manifest_artifacts: GenerateManifestArtifacts,
    build_btst_nightly_control_tower_payload: BuildNightlyPayload,
    load_archived_nightly_payloads: LoadArchivedPayloads,
    build_btst_open_ready_delta_payload: BuildOpenReadyDeltaPayload,
    render_btst_open_ready_delta_markdown: RenderMarkdown,
    render_btst_nightly_control_tower_markdown: RenderMarkdown,
    generate_btst_latest_close_validation_artifacts: GenerateCloseValidationArtifacts,
    archive_nightly_payload: ArchiveNightlyPayload,
) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    output_paths = resolve_output_paths(
        resolved_reports_root=resolved_reports_root,
        output_json=output_json,
        output_md=output_md,
        delta_output_json=delta_output_json,
        delta_output_md=delta_output_md,
        close_validation_output_json=close_validation_output_json,
        close_validation_output_md=close_validation_output_md,
        history_dir=history_dir,
    )
    resolved_output_json = output_paths["resolved_output_json"]
    resolved_output_md = output_paths["resolved_output_md"]
    resolved_delta_output_json = output_paths["resolved_delta_output_json"]
    resolved_delta_output_md = output_paths["resolved_delta_output_md"]
    resolved_close_validation_output_json = output_paths["resolved_close_validation_output_json"]
    resolved_close_validation_output_md = output_paths["resolved_close_validation_output_md"]
    resolved_history_dir = output_paths["resolved_history_dir"]

    pre_manifest_result = generate_reports_manifest_artifacts(reports_root=resolved_reports_root)
    bootstrap_payload = build_btst_nightly_control_tower_payload(pre_manifest_result["manifest"])
    historical_payload_candidates = load_archived_nightly_payloads(resolved_history_dir)
    previous_payload, previous_payload_path = historical_payload_candidates[0] if historical_payload_candidates else ({}, None)
    bootstrap_delta_payload = build_btst_open_ready_delta_payload(
        bootstrap_payload,
        reports_root=resolved_reports_root,
        current_nightly_json_path=resolved_output_json,
        previous_payload=previous_payload,
        previous_payload_path=previous_payload_path,
        historical_payload_candidates=historical_payload_candidates,
    )
    _write_nightly_artifact_bundle(
        payload=bootstrap_payload,
        delta_payload=bootstrap_delta_payload,
        output_json=resolved_output_json,
        output_md=resolved_output_md,
        delta_output_json=resolved_delta_output_json,
        delta_output_md=resolved_delta_output_md,
        render_btst_open_ready_delta_markdown=render_btst_open_ready_delta_markdown,
        render_btst_nightly_control_tower_markdown=render_btst_nightly_control_tower_markdown,
    )

    post_manifest_result = generate_reports_manifest_artifacts(reports_root=resolved_reports_root)
    payload = build_btst_nightly_control_tower_payload(post_manifest_result["manifest"])
    delta_payload = build_btst_open_ready_delta_payload(
        payload,
        reports_root=resolved_reports_root,
        current_nightly_json_path=resolved_output_json,
        previous_payload=previous_payload,
        previous_payload_path=previous_payload_path,
        historical_payload_candidates=historical_payload_candidates,
    )
    _write_nightly_artifact_bundle(
        payload=payload,
        delta_payload=delta_payload,
        output_json=resolved_output_json,
        output_md=resolved_output_md,
        delta_output_json=resolved_delta_output_json,
        delta_output_md=resolved_delta_output_md,
        render_btst_open_ready_delta_markdown=render_btst_open_ready_delta_markdown,
        render_btst_nightly_control_tower_markdown=render_btst_nightly_control_tower_markdown,
    )

    close_validation_result = generate_btst_latest_close_validation_artifacts(
        nightly_payload=payload,
        delta_payload=delta_payload,
        nightly_json_path=resolved_output_json,
        delta_json_path=resolved_delta_output_json,
        output_json=resolved_close_validation_output_json,
        output_md=resolved_close_validation_output_md,
    )
    history_json_path = archive_nightly_payload(payload, resolved_history_dir)
    final_manifest_result = generate_reports_manifest_artifacts(reports_root=resolved_reports_root)

    return {
        "payload": payload,
        "delta_payload": delta_payload,
        "json_path": resolved_output_json.as_posix(),
        "markdown_path": resolved_output_md.as_posix(),
        "delta_json_path": resolved_delta_output_json.as_posix(),
        "delta_markdown_path": resolved_delta_output_md.as_posix(),
        "close_validation_json_path": close_validation_result["json_path"],
        "close_validation_markdown_path": close_validation_result["markdown_path"],
        "history_json_path": history_json_path,
        "catalyst_theme_frontier_json": dict(payload.get("latest_btst_snapshot") or {}).get("catalyst_theme_frontier_json_path"),
        "catalyst_theme_frontier_markdown": dict(payload.get("latest_btst_snapshot") or {}).get("catalyst_theme_frontier_markdown_path"),
        "manifest_json": final_manifest_result["json_path"],
        "manifest_markdown": final_manifest_result["markdown_path"],
    }
