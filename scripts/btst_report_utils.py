from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def safe_load_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return {}
    return json.loads(resolved.read_text(encoding="utf-8"))


def normalize_trade_date(value: Any) -> str | None:
    if value is None:
        return None
    digits = "".join(ch for ch in str(value).strip() if ch.isdigit())
    if len(digits) != 8:
        return None
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"


def looks_like_report_dir(path: Path) -> bool:
    return path.is_dir() and (path / "session_summary.json").exists() and (path / "selection_artifacts").exists()


def discover_report_dirs(
    input_path: str | Path,
    *,
    report_name_contains: str | None = None,
    report_name_prefix: str | None = None,
) -> list[Path]:
    resolved = Path(input_path).expanduser().resolve()
    if looks_like_report_dir(resolved):
        return [resolved]
    if not resolved.is_dir():
        raise FileNotFoundError(f"Input path does not exist: {resolved}")

    return sorted(
        candidate
        for candidate in resolved.iterdir()
        if looks_like_report_dir(candidate)
        and (report_name_contains is None or report_name_contains in candidate.name)
        and (report_name_prefix is None or candidate.name.startswith(report_name_prefix))
    )


def discover_nested_report_dirs(report_root_dirs: list[str | Path], *, report_name_contains: str = "") -> list[Path]:
    discovered: set[Path] = set()
    name_filter = str(report_name_contains or "").strip()
    for root in [Path(path).expanduser().resolve() for path in report_root_dirs]:
        if not root.exists():
            continue
        for snapshot_path in root.rglob("selection_snapshot.json"):
            report_dir = snapshot_path.parent.parent.parent
            if not (report_dir / "selection_artifacts").exists():
                continue
            if name_filter and name_filter not in report_dir.name:
                continue
            discovered.add(report_dir)
    return sorted(discovered)