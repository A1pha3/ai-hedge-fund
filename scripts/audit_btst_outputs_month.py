from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_DATE_YYYYMMDD = r"\d{8}"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _extract_report_refs(text: str) -> set[str]:
    refs: set[str] = set()
    for match in re.findall(r"data/reports/[A-Za-z0-9_./\-]+", text):
        cleaned = match.rstrip(")].,;:\"'`")
        if cleaned:
            refs.add(cleaned)
    return refs


def _extract_filename_dates(filename: str) -> set[str]:
    return {match for match in re.findall(rf"{_DATE_YYYYMMDD}", str(filename or ""))}


def _extract_dates(text: str) -> tuple[set[str], set[str]]:
    signal_dates: set[str] = set()
    next_dates: set[str] = set()

    head = "\n".join(text.splitlines()[:40])

    # Patterns: "(YYYYMMDD -> YYYYMMDD)" or "（YYYYMMDD -> YYYYMMDD）" (prefer header region)
    for s, n in re.findall(
        rf"[（(]\s*({_DATE_YYYYMMDD})\s*->\s*({_DATE_YYYYMMDD})\s*[）)]",
        head,
    ):
        signal_dates.add(s)
        next_dates.add(n)

    # Bullet formats: 信号日 / 下一交易日
    for s in re.findall(rf"信号日\s*[:：]\s*`?({_DATE_YYYYMMDD})`?", text):
        signal_dates.add(s)
    for n in re.findall(rf"(?:下一交易日|次日交易日|下一真实交易日)\s*[:：]\s*`?({_DATE_YYYYMMDD})`?", text):
        next_dates.add(n)

    # ISO date bullets: 信号日: 2026-05-19
    for s in re.findall(r"信号日\s*[:：]\s*`?(\d{4}-\d{2}-\d{2})`?", text):
        signal_dates.add(s.replace("-", ""))
    for n in re.findall(
        r"(?:下一交易日|次日交易日|下一真实交易日|次交易日|执行日|执行日期|目标交易日|目标日)\s*[:：]\s*`?(\d{4}-\d{2}-\d{2})`?",
        text,
    ):
        next_dates.add(n.replace("-", ""))

    # Checklist header: "对应 YYYYMMDD 开盘" (with optional backticks)
    for n in re.findall(rf"对应\s*`?({_DATE_YYYYMMDD})`?\s*开盘", text):
        next_dates.add(n)

    # Alternate wording: "目标日"
    for n in re.findall(rf"目标日\s*[:：]\s*`?({_DATE_YYYYMMDD})`?", text):
        next_dates.add(n)

    # Fallback: arrow pattern in header region only (avoid picking up tables)
    if not signal_dates and not next_dates:
        match = re.search(rf"({_DATE_YYYYMMDD})\s*->\s*({_DATE_YYYYMMDD})", head)
        if match:
            signal_dates.add(match.group(1))
            next_dates.add(match.group(2))

    return signal_dates, next_dates


@dataclass
class FolderAudit:
    folder: str
    md_files: list[str]
    filename_dates: list[str]
    signal_dates: list[str]
    next_dates: list[str]
    referenced_paths: list[str]
    missing_paths: list[str]
    metadata_consistent: bool
    folder_date_role: str
    next_date_matches_folder: bool | None
    filename_date_matches_folder: bool | None
    is_date_folder: bool


def audit_btst_outputs_month(
    *,
    month: str,
    outputs_dir: str | Path = "outputs",
    repo_root: str | Path = ".",
) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve()
    outputs_root = (root / outputs_dir / str(month)).resolve()

    folders: list[FolderAudit] = []
    missing_total: set[str] = set()
    mismatched_folders: list[str] = []

    role_counts: dict[str, int] = {}
    inconsistent_folders: list[str] = []
    non_canonical_folders: list[str] = []
    filename_mismatch_folders: list[str] = []
    unknown_role_folders: list[str] = []

    if not outputs_root.exists():
        return {
            "month": str(month),
            "outputs_root": str(outputs_root),
            "folder_count": 0,
            "folders": [],
            "missing_paths": [],
            "mismatched_folders": [],
            "folder_role_counts": {},
            "inconsistent_folders": [],
            "unknown_role_folders": [],
            "non_canonical_folders": [],
            "filename_mismatch_folders": [],
        }

    for day_dir in sorted([p for p in outputs_root.iterdir() if p.is_dir()]):
        md_paths = sorted(day_dir.glob("*.md"))
        referenced: set[str] = set()
        filename_dates: set[str] = set()
        signal_dates: set[str] = set()
        next_dates: set[str] = set()

        for md_path in md_paths:
            filename_dates |= _extract_filename_dates(md_path.name)
            text = _read_text(md_path)
            referenced |= _extract_report_refs(text)
            s_dates, n_dates = _extract_dates(text)
            signal_dates |= s_dates
            next_dates |= n_dates

        missing = sorted(
            {
                ref
                for ref in referenced
                if not (root / ref).exists()
            }
        )
        missing_total |= set(missing)

        metadata_consistent = len(signal_dates) <= 1 and len(next_dates) <= 1

        base_date: str | None = None
        match = re.match(rf"^({_DATE_YYYYMMDD})", day_dir.name)
        if match:
            base_date = match.group(1)

        next_date_matches_folder: bool | None = None
        if next_dates and base_date:
            next_date_matches_folder = base_date in next_dates
        elif next_dates:
            next_date_matches_folder = day_dir.name in next_dates

        is_date_folder = base_date is not None

        folder_date_role = "unknown"
        if not is_date_folder:
            folder_date_role = "special_folder"
        elif signal_dates or next_dates:
            if base_date in next_dates:
                folder_date_role = "next_date"
            elif base_date in signal_dates:
                folder_date_role = "signal_date"
            else:
                folder_date_role = "mismatch"
                mismatched_folders.append(day_dir.name)

        role_counts[folder_date_role] = int(role_counts.get(folder_date_role) or 0) + 1

        filename_date_matches_folder: bool | None = None
        if filename_dates and base_date:
            filename_date_matches_folder = filename_dates == {base_date}

        if is_date_folder and folder_date_role == "unknown":
            unknown_role_folders.append(day_dir.name)

        if is_date_folder and folder_date_role not in {"signal_date", "special_folder"}:
            non_canonical_folders.append(day_dir.name)

        if is_date_folder and filename_date_matches_folder is False:
            filename_mismatch_folders.append(day_dir.name)

        if is_date_folder and (
            folder_date_role in {"unknown", "mismatch"} or not metadata_consistent
        ):
            inconsistent_folders.append(day_dir.name)

        folders.append(
            FolderAudit(
                folder=day_dir.name,
                md_files=[p.name for p in md_paths],
                filename_dates=sorted(filename_dates),
                signal_dates=sorted(signal_dates),
                next_dates=sorted(next_dates),
                referenced_paths=sorted(referenced),
                missing_paths=missing,
                metadata_consistent=metadata_consistent,
                folder_date_role=folder_date_role,
                next_date_matches_folder=next_date_matches_folder,
                filename_date_matches_folder=filename_date_matches_folder,
                is_date_folder=is_date_folder,
            )
        )

    return {
        "month": str(month),
        "outputs_root": str(outputs_root),
        "folder_count": len(folders),
        "folders": [f.__dict__ for f in folders],
        "missing_paths": sorted(missing_total),
        "mismatched_folders": sorted(set(mismatched_folders)),
        "folder_role_counts": dict(role_counts),
        "inconsistent_folders": sorted(set(inconsistent_folders)),
        "unknown_role_folders": sorted(set(unknown_role_folders)),
        "non_canonical_folders": sorted(set(non_canonical_folders)),
        "filename_mismatch_folders": sorted(set(filename_mismatch_folders)),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit outputs/<month> BTST markdown references against data/reports.")
    parser.add_argument("--month", required=True, help="YYYYMM, e.g. 202605")
    parser.add_argument("--outputs-dir", default="outputs")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if missing paths or mismatched/unknown dates exist")
    parser.add_argument(
        "--strict-canonical",
        action="store_true",
        help="Also exit non-zero if outputs folders are not canonical signal-date folders (or filename dates do not match folder date)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = audit_btst_outputs_month(month=args.month, outputs_dir=args.outputs_dir, repo_root=args.repo_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if args.strict:
        missing = result.get("missing_paths") or []
        mismatched = result.get("mismatched_folders") or []
        inconsistent = result.get("inconsistent_folders") or []
        if missing or mismatched or inconsistent:
            raise SystemExit(1)

    if args.strict_canonical:
        missing = result.get("missing_paths") or []
        non_canonical = result.get("non_canonical_folders") or []
        filename_mismatch = result.get("filename_mismatch_folders") or []
        if missing or non_canonical or filename_mismatch:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
