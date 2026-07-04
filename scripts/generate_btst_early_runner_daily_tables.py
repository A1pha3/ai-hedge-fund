from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_btst_early_runner_v1 import analyze_btst_early_runner_v1

REPORTS_DIR = Path("data/reports")
EARLY_RUNNER_JSON = REPORTS_DIR / "btst_early_runner_v1_latest.json"
OUTPUT_DIR = REPORTS_DIR / "early_runner_daily_tables"


def _load_or_build_analysis(reports_root: Path) -> dict[str, Any]:
    """Load the latest early-runner analysis or rebuild it when missing."""
    analysis_path = reports_root / EARLY_RUNNER_JSON.name
    if analysis_path.exists():
        try:
            return json.loads(analysis_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return analyze_btst_early_runner_v1(reports_root)


def _slugify(label: str) -> str:
    """Normalize a board label into a stable filesystem token."""
    return str(label or "").strip().lower().replace(" ", "_")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON with stable UTF-8 formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _render_table_markdown(payload: dict[str, Any]) -> str:
    """Render one daily early-runner table as markdown."""
    lines = [f"# {payload.get('table_label')}", ""]
    lines.append(f"- trade_date: {payload.get('trade_date')}")
    lines.append(f"- entry_count: {payload.get('entry_count')}")
    lines.append(f"- gate_action: {payload.get('gate_action')}")
    lines.append(f"- deployment_mode: {payload.get('deployment_mode')}")
    lines.append("")
    lines.append("## Entries")
    entries = list(payload.get("entries") or [])
    if not entries:
        lines.append("- none")
        return "\n".join(lines) + "\n"
    for row in entries:
        lines.append(f"- {row.get('ticker')}: pre_score={row.get('pre_score')} confirm_score={row.get('confirm_score')} candidate_source={row.get('candidate_source')} hot_theme_board={row.get('hot_theme_board')} entry_status={row.get('entry_status')}")
    return "\n".join(lines) + "\n"


def _build_table_payload(board: dict[str, Any], *, table_key: str, table_label: str) -> dict[str, Any]:
    """Build one serializable daily-table payload from a board section."""
    entries = [dict(entry or {}) for entry in list(board.get(table_key) or [])]
    return {
        "artifact_version": "v1",
        "trade_date": board.get("trade_date"),
        "table_key": table_key,
        "table_label": table_label,
        "gate_action": board.get("gate_action"),
        "deployment_mode": board.get("deployment_mode"),
        "entry_count": len(entries),
        "entries": entries,
    }


def generate_btst_early_runner_daily_tables(
    reports_root: str | Path,
    *,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Generate trade-date keyed early-runner daily table artifacts."""
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    resolved_output_dir = Path(output_dir).expanduser().resolve() if output_dir else (resolved_reports_root / OUTPUT_DIR.name).resolve()
    analysis = _load_or_build_analysis(resolved_reports_root)
    generated_tables: list[dict[str, Any]] = []
    for board in [dict(item or {}) for item in list(analysis.get("daily_boards") or [])]:
        trade_date = str(board.get("trade_date") or "").strip()
        if not trade_date:
            continue
        for table_key, table_label in [
            ("early_runner_watchlist", "BTST Early Runner Watchlist"),
            ("early_runner_priority", "BTST Early Runner Priority"),
            ("second_entry_reentry", "BTST Second Entry Reentry"),
        ]:
            payload = _build_table_payload(board, table_key=table_key, table_label=table_label)
            file_stem = f"btst_{_slugify(table_key)}_{trade_date}"
            json_path = resolved_output_dir / f"{file_stem}.json"
            md_path = resolved_output_dir / f"{file_stem}.md"
            _write_json(json_path, payload)
            md_path.write_text(_render_table_markdown(payload), encoding="utf-8")
            generated_tables.append(
                {
                    "trade_date": trade_date,
                    "table_key": table_key,
                    "entry_count": payload["entry_count"],
                    "json_path": json_path.as_posix(),
                    "markdown_path": md_path.as_posix(),
                }
            )
    latest_trade_date = max((str(item.get("trade_date") or "") for item in generated_tables), default="")
    latest_tables = [dict(item) for item in generated_tables if str(item.get("trade_date") or "") == latest_trade_date]
    return {
        "status": "refreshed" if generated_tables else "skipped_no_daily_boards",
        "reports_root": resolved_reports_root.as_posix(),
        "output_dir": resolved_output_dir.as_posix(),
        "table_count": len(generated_tables),
        "trade_date_count": len({str(item.get("trade_date") or "") for item in generated_tables}),
        "latest_trade_date": latest_trade_date or None,
        "latest_tables": latest_tables,
        "tables": generated_tables,
    }


def main() -> None:
    """CLI entrypoint for generating early-runner daily tables."""
    parser = argparse.ArgumentParser(description="Generate per-trade-date early-runner daily tables.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR))
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()
    result = generate_btst_early_runner_daily_tables(
        args.reports_root,
        output_dir=args.output_dir or None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
